"""Unit tests for the workflow action auditor (utils/check_actions.py).

The network layer (``fetch_text``) is always mocked: these tests must not
depend on GitHub being reachable.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils import check_actions
from utils.check_actions import (
    EXIT_CANNOT_CHECK,
    EXIT_NEEDS_UPGRADE,
    EXIT_OK,
    REQUIRED_RUNTIME,
    ActionCheckError,
    ActionRef,
    CheckResult,
    action_refs,
    check_ref,
    format_report,
    main,
    parse_action_ref,
    runtime_from_metadata,
)

WORKFLOW = """\
name: test
on: [workflow_dispatch]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/upload-artifact@v5
      - uses: ./local-action
      - uses: docker://alpine:3
      - run: echo hello
"""


def metadata(runtime: str) -> str:
    return f"runs:\n  using: '{runtime}'\n  main: 'dist/index.js'\n"


def fake_fetch(routes: dict[str, str]):
    """Return a fetch_text stand-in that answers from routes (substring match)."""

    def fetch(url: str) -> str:
        for pattern, body in routes.items():
            if pattern in url:
                return body
        raise ActionCheckError(f"unexpected URL {url}")

    return fetch


def write_workflow(text: str) -> tuple[tempfile.TemporaryDirectory, Path]:
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "workflow.yml"
    path.write_text(text, encoding="utf-8")
    return directory, path


class TestParseActionRef(unittest.TestCase):
    def test_splits_the_slug_and_the_ref(self):
        ref = parse_action_ref("actions/upload-artifact@v7.0.2")
        self.assertEqual(ref.slug, "actions/upload-artifact")
        self.assertEqual(ref.ref, "v7.0.2")
        self.assertEqual(ref.major, 7)

    def test_a_plain_major_is_read(self):
        self.assertEqual(parse_action_ref("actions/checkout@v5").major, 5)

    def test_a_branch_or_sha_pin_has_no_major(self):
        self.assertIsNone(parse_action_ref("owner/repo@main").major)
        self.assertIsNone(parse_action_ref("owner/repo@abc1234").major)

    def test_local_and_docker_actions_are_skipped(self):
        for raw in ("./local-action", "../shared/action", "docker://alpine:3"):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_action_ref(raw))

    def test_a_malformed_reference_raises(self):
        for raw in ("no-at-sign", "owner/repo@", "@v1", "norepo@v1"):
            with self.subTest(raw=raw), self.assertRaises(ActionCheckError):
                parse_action_ref(raw)


class TestActionRefs(unittest.TestCase):
    def test_collects_unique_references_and_skips_local_ones(self):
        directory, path = write_workflow(WORKFLOW)
        self.addCleanup(directory.cleanup)

        refs = action_refs([path])

        self.assertEqual(
            [ref.raw for ref in refs],
            ["actions/checkout@v5", "actions/upload-artifact@v5"],
        )

    def test_duplicates_across_workflows_are_merged(self):
        first = write_workflow(WORKFLOW)
        second = write_workflow(WORKFLOW)
        self.addCleanup(first[0].cleanup)
        self.addCleanup(second[0].cleanup)

        self.assertEqual(len(action_refs([first[1], second[1]])), 2)

    def test_an_unreadable_workflow_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir, self.assertRaises(
            ActionCheckError
        ):
            action_refs([Path(tmp_dir) / "missing.yml"])

    def test_invalid_yaml_raises(self):
        directory, path = write_workflow("jobs: [unclosed\n")
        self.addCleanup(directory.cleanup)

        with self.assertRaises(ActionCheckError):
            action_refs([path])


class TestRuntimeFromMetadata(unittest.TestCase):
    def test_reads_the_declared_runtime(self):
        for runtime in ("node20", "node24", "composite", "docker"):
            with self.subTest(runtime=runtime):
                self.assertEqual(runtime_from_metadata(metadata(runtime)), runtime)

    def test_missing_or_broken_metadata_returns_none(self):
        for body in ("", "name: x\n", "runs:\n", "runs: [1, 2]\n", "runs:\n  using: []\n"):
            with self.subTest(body=body):
                self.assertIsNone(runtime_from_metadata(body))


class TestCheckResult(unittest.TestCase):
    def _result(self, runtime: str | None) -> CheckResult:
        return CheckResult(ref=ActionRef("a/b@v1", "a/b", "v1"), runtime=runtime)

    def test_a_current_node_action_is_ok(self):
        result = self._result(REQUIRED_RUNTIME)
        self.assertEqual(result.verdict, "ok")
        self.assertFalse(result.needs_upgrade)
        self.assertTrue(result.is_node_action)

    def test_an_older_node_action_needs_upgrading(self):
        result = self._result("node20")
        self.assertEqual(result.verdict, "UPGRADE")
        self.assertTrue(result.needs_upgrade)

    def test_a_non_node_action_is_not_applicable(self):
        result = self._result("composite")
        self.assertEqual(result.verdict, "n/a")
        self.assertFalse(result.needs_upgrade)
        self.assertFalse(result.cannot_check)

    def test_an_unreadable_runtime_is_unknown(self):
        result = self._result(None)
        self.assertEqual(result.verdict, "unknown")
        self.assertTrue(result.cannot_check)
        self.assertFalse(result.needs_upgrade)


class TestCheckRef(unittest.TestCase):
    REF = "actions/upload-artifact@v5"
    ACTION = parse_action_ref(REF)

    def test_a_current_action_is_reported_without_a_suggestion(self):
        with mock.patch.object(
            check_actions,
            "fetch_text",
            side_effect=fake_fetch({"upload-artifact/v5/": metadata("node24")}),
        ) as fetch:
            result = check_ref(self.ACTION)

        self.assertEqual(result.runtime, "node24")
        self.assertIsNone(result.suggestion)
        # Only the pinned metadata is needed when nothing is wrong.
        self.assertEqual(fetch.call_count, 1)

    def test_an_outdated_action_suggests_the_latest_release(self):
        routes = {
            "releases/latest": json.dumps({"tag_name": "v7.0.2"}),
            "upload-artifact/v5/": metadata("node20"),
            "upload-artifact/v7.0.2/": metadata("node24"),
        }
        with mock.patch.object(check_actions, "fetch_text", side_effect=fake_fetch(routes)):
            result = check_ref(self.ACTION)

        self.assertEqual(result.runtime, "node20")
        self.assertEqual(result.suggestion, "v7.0.2 (node24)")
        self.assertTrue(result.needs_upgrade)

    def test_a_failed_lookup_is_reported_as_unknown(self):
        with mock.patch.object(
            check_actions, "fetch_text", side_effect=ActionCheckError("boom")
        ):
            result = check_ref(self.ACTION)

        self.assertIsNone(result.runtime)
        self.assertTrue(result.cannot_check)

    def test_a_failed_release_lookup_leaves_the_suggestion_empty(self):
        routes = {"upload-artifact/v5/": metadata("node20")}
        with mock.patch.object(check_actions, "fetch_text", side_effect=fake_fetch(routes)):
            result = check_ref(self.ACTION)

        self.assertEqual(result.runtime, "node20")
        self.assertIsNone(result.suggestion)


class TestFormatReport(unittest.TestCase):
    def test_renders_an_aligned_table(self):
        results = [
            CheckResult(parse_action_ref("actions/checkout@v5"), "node24"),
            CheckResult(
                parse_action_ref("actions/upload-artifact@v5"),
                "node20",
                suggestion="v7.0.2 (node24)",
            ),
        ]

        lines = format_report(results).splitlines()

        self.assertTrue(lines[0].startswith("Action"))
        self.assertIn("Runtime", lines[0])
        self.assertIn("node24", lines[1])
        self.assertIn("UPGRADE", lines[2])
        self.assertIn("v7.0.2 (node24)", lines[2])
        # Every row lines up with the header's columns.
        self.assertEqual(lines[0].index("Runtime"), lines[1].index("node24"))


class TestMain(unittest.TestCase):
    def _run(self, argv: list[str], routes: dict[str, str]) -> tuple[int, str]:
        output = io.StringIO()
        with mock.patch.object(
            check_actions, "fetch_text", side_effect=fake_fetch(routes)
        ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = main(argv)
        return code, output.getvalue()

    def test_all_current_actions_pass(self):
        directory, path = write_workflow(WORKFLOW)
        self.addCleanup(directory.cleanup)
        routes = {
            "checkout/v5/": metadata("node24"),
            "upload-artifact/v5/": metadata("node24"),
        }

        code, output = self._run(["--workflow", str(path)], routes)

        self.assertEqual(code, EXIT_OK)
        self.assertIn("All 2 Node actions declare node24.", output)

    def test_an_outdated_action_fails_the_run(self):
        directory, path = write_workflow(WORKFLOW)
        self.addCleanup(directory.cleanup)
        routes = {
            "checkout/v5/": metadata("node24"),
            "upload-artifact/v5/": metadata("node20"),
            "releases/latest": json.dumps({"tag_name": "v7.0.2"}),
            "upload-artifact/v7.0.2/": metadata("node24"),
        }

        code, output = self._run(["--workflow", str(path)], routes)

        self.assertEqual(code, EXIT_NEEDS_UPGRADE)
        self.assertIn("Needs upgrading: actions/upload-artifact@v5", output)

    def test_an_unfetchable_action_cannot_be_checked(self):
        directory, path = write_workflow(WORKFLOW)
        self.addCleanup(directory.cleanup)

        code, output = self._run(["--workflow", str(path)], {})

        self.assertEqual(code, EXIT_CANNOT_CHECK)
        self.assertIn("Could not be checked: actions/checkout@v5", output)

    def test_an_unreadable_workflow_is_an_error(self):
        code, output = self._run(["--workflow", "/nonexistent/workflow.yml"], {})

        self.assertEqual(code, EXIT_CANNOT_CHECK)
        self.assertIn("Error:", output)

    def test_the_repository_workflows_are_all_current(self):
        # Guards the real .github/workflows: with the network stubbed out this
        # still exercises the default discovery, and an action that declares an
        # older runtime fails here as well as in CI.
        routes = {
            "checkout/v": metadata(REQUIRED_RUNTIME),
            "setup-python/v": metadata(REQUIRED_RUNTIME),
            "upload-artifact/v": metadata(REQUIRED_RUNTIME),
            "action-gh-release/v": metadata(REQUIRED_RUNTIME),
            "releases/latest": json.dumps({"tag_name": "v1"}),
        }

        code, output = self._run([], routes)

        self.assertEqual(code, EXIT_OK, output)
        self.assertIn("All 4 Node actions declare node24.", output)


if __name__ == "__main__":
    unittest.main()
