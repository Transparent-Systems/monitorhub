"""Guard the CI workflows.

CI is the one place a mistake is expensive and invisible: the GUI binary was
once missing from the artifacts, and a manual run must never publish a release.
The unit-test workflow is guarded too: it is the only check a Dependabot pull
request ever gets.
"""

import unittest
from pathlib import Path

import yaml

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
LINUX = WORKFLOW_DIR / "build-linux.yml"
WINDOWS = WORKFLOW_DIR / "build-windows.yml"
UNIT_TESTS = WORKFLOW_DIR / "test.yml"

# The GUI ships as a single onefile binary on Linux, and as a versioned zip of
# the onedir folder on Windows.
LINUX_GUI = "dist/mhub-gui"
WINDOWS_GUI_ZIP = "dist/mhub-gui-${{ env.VERSION }}-windows.zip"


def steps(workflow_path: Path) -> list[dict]:
    """Return every step of every job in a workflow file."""
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def run_commands(workflow_path: Path) -> str:
    return "\n".join(step.get("run", "") for step in steps(workflow_path))


def step_named(workflow_path: Path, name: str) -> dict:
    for step in steps(workflow_path):
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in {workflow_path.name}")


def triggers(workflow_path: Path) -> dict:
    """Return a workflow's ``on:`` block.

    PyYAML implements YAML 1.1, where the bare key ``on`` parses as the boolean
    ``True``, so the block is looked up under both spellings.
    """
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    return workflow.get("on", workflow.get(True)) or {}


def _entries(value: str) -> list[str]:
    """Split a workflow path/files block into its entries.

    One entry per line: the entries can contain spaces (``${{ env.VERSION }}``),
    so splitting on whitespace would tear them apart.
    """
    return [line.strip() for line in value.splitlines() if line.strip()]


class TestBothTargetsAreBuilt(unittest.TestCase):
    def test_linux_builds_both_targets_as_onefile(self):
        commands = run_commands(LINUX)
        self.assertIn("build_project.py cli", commands)
        self.assertIn("build_project.py gui", commands)
        # onefile is the default, so Linux names no layout at all.
        self.assertNotIn("--layout", commands)

    def test_windows_builds_the_cli_and_an_onedir_gui(self):
        commands = run_commands(WINDOWS)
        self.assertIn("build_project.py cli", commands)
        self.assertIn("build_project.py gui --layout onedir", commands)


class TestBothBinariesArePublished(unittest.TestCase):
    def _uploaded(self, workflow_path: Path) -> list[str]:
        return _entries(step_named(workflow_path, "Upload artifact")["with"]["path"])

    def _released(self, workflow_path: Path) -> list[str]:
        return _entries(
            step_named(workflow_path, "Attach to GitHub Release")["with"]["files"]
        )

    def test_linux_uploads_and_releases_both_binaries(self):
        for files in (self._uploaded(LINUX), self._released(LINUX)):
            for expected in (
                "dist/mhub",
                "dist/mhub.sha256",
                LINUX_GUI,
                f"{LINUX_GUI}.sha256",
            ):
                with self.subTest(expected=expected):
                    self.assertIn(expected, files)

    def test_windows_uploads_and_releases_the_cli_and_the_gui_zip(self):
        for files in (self._uploaded(WINDOWS), self._released(WINDOWS)):
            for expected in (
                "dist/mhub.exe",
                "dist/mhub.exe.sha256",
                WINDOWS_GUI_ZIP,
                f"{WINDOWS_GUI_ZIP}.sha256",
            ):
                with self.subTest(expected=expected):
                    self.assertIn(expected, files)

    def test_windows_never_publishes_a_onefile_gui(self):
        # The onedir build has no dist/mhub-gui.exe; a stale path would make the
        # release step publish nothing (or fail).
        self.assertNotIn("mhub-gui.exe", WINDOWS.read_text(encoding="utf-8"))


class TestChecksumsCoverBothArtefacts(unittest.TestCase):
    def test_linux_checksums_both_binaries(self):
        command = step_named(LINUX, "Generate SHA256 checksums")["run"]
        self.assertIn("sha256sum mhub > mhub.sha256", command)
        self.assertIn("sha256sum mhub-gui > mhub-gui.sha256", command)

    def test_windows_checksums_the_cli_and_the_gui_zip(self):
        command = step_named(WINDOWS, "Generate SHA256 checksums")["run"]
        self.assertIn("mhub.exe", command)
        self.assertIn("mhub-gui-$env:VERSION-windows.zip", command)
        self.assertIn(".sha256", command)


class TestVersionedGuiArchive(unittest.TestCase):
    def test_the_version_comes_from_version_py(self):
        command = step_named(WINDOWS, "Read the version")["run"]
        self.assertIn("version.VERSION_STRING", command)
        self.assertIn("GITHUB_ENV", command)

    def test_the_gui_folder_is_the_archive_root(self):
        # -Path <folder> keeps the folder name as the root entry, so extracting
        # the zip produces a clean mhub-gui/ directory.
        command = step_named(WINDOWS, "Package the GUI folder")["run"]
        self.assertIn("Compress-Archive -Path dist/mhub-gui", command)
        self.assertIn("mhub-gui-$env:VERSION-windows.zip", command)


# Every action must declare `runs.using: node24`: Node 20 was removed from the
# runners on 2026-09-23, so older majors (e.g. upload-artifact v5,
# action-gh-release v2) are force-migrated to node24 and warn on every run.
# The values below are the first major of each action that declares node24,
# read from the action.yml the runner itself reads:
#   checkout v4 node20 -> v5, setup-python v5 node20 -> v6,
#   upload-artifact v5 node20 -> v6, action-gh-release v2 node20 -> v3.
# Upgrading later passes; downgrading (or adding an unaudited action) fails.
NODE24_ACTIONS = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
    "softprops/action-gh-release": 3,
}


def action_refs(workflow_path: Path) -> list[str]:
    """Return every ``uses:`` reference in a workflow."""
    return [step["uses"] for step in steps(workflow_path) if "uses" in step]


class TestActionsRunOnNode24(unittest.TestCase):
    """Node 20 was removed from the runners on 2026-09-23."""

    def test_every_action_is_audited(self):
        for workflow_path in (LINUX, WINDOWS, UNIT_TESTS):
            for ref in action_refs(workflow_path):
                with self.subTest(action=ref):
                    self.assertIn(
                        ref.split("@", 1)[0],
                        NODE24_ACTIONS,
                        "action is not in the audited node24 list",
                    )

    def test_no_action_is_pinned_below_its_node24_major(self):
        for workflow_path in (LINUX, WINDOWS, UNIT_TESTS):
            for ref in action_refs(workflow_path):
                name, _, version = ref.partition("@")
                major = version.lstrip("v").split(".")[0]
                if not major.isdigit():
                    # Pinned to a branch or SHA: nothing to compare.
                    continue
                with self.subTest(action=ref):
                    self.assertGreaterEqual(int(major), NODE24_ACTIONS[name])


class TestUnitTestsGateEveryChange(unittest.TestCase):
    """A pull request has to be tested before it can be merged.

    Nothing else reacts to a pull request: the build workflows only run on a v*
    tag, so without this workflow a Dependabot bump would arrive with no checks
    at all.
    """

    def test_the_workflow_exists(self):
        self.assertTrue(UNIT_TESTS.is_file(), UNIT_TESTS)

    def test_it_runs_on_every_pull_request(self):
        self.assertIn("pull_request", triggers(UNIT_TESTS))

    def test_it_runs_on_pushes_to_main(self):
        # The published branch must not be the only branch without a check.
        self.assertEqual(triggers(UNIT_TESTS)["push"]["branches"], ["main"])

    def test_it_runs_the_unit_tests_through_the_makefile(self):
        # A hand-written unittest invocation here would drift from the target a
        # developer runs locally.
        self.assertIn("make test-unit", run_commands(UNIT_TESTS))

    def test_it_creates_the_virtualenv_the_makefile_requires(self):
        # `make test-unit` fails without .venv/bin/python, so a clean runner has
        # to build the virtualenv first.
        self.assertIn("python -m venv .venv", run_commands(UNIT_TESTS))

    def test_it_uses_the_python_version_the_project_requires(self):
        versions = [
            step["with"]["python-version"]
            for step in steps(UNIT_TESTS)
            if "setup-python" in step.get("uses", "")
        ]
        self.assertEqual(versions, ["3.12"])


DEPENDABOT = WORKFLOW_DIR.parent / "dependabot.yml"


class TestDependabotConfig(unittest.TestCase):
    """Dependabot keeps the actions current; a typo here disables it silently."""

    def _config(self) -> dict:
        self.assertTrue(DEPENDABOT.is_file(), DEPENDABOT)
        return yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))

    def test_it_updates_github_actions_on_a_monthly_schedule(self):
        config = self._config()
        self.assertEqual(config["version"], 2)
        updates = config["updates"]
        self.assertEqual(
            [update["package-ecosystem"] for update in updates], ["github-actions"]
        )
        self.assertEqual(updates[0]["directory"], "/")
        self.assertEqual(updates[0]["schedule"]["interval"], "monthly")

    def test_it_does_not_manage_the_generated_requirements_file(self):
        # requirements.txt comes from `uv pip compile --universal`; a pip entry
        # here would fight the release checklist.
        ecosystems = {update["package-ecosystem"] for update in self._config()["updates"]}
        self.assertNotIn("pip", ecosystems)


class TestManualRunsCannotPublish(unittest.TestCase):
    """A workflow_dispatch run must not touch a GitHub Release."""

    def test_release_steps_are_tag_guarded(self):
        for workflow_path in (LINUX, WINDOWS):
            with self.subTest(workflow=workflow_path.name):
                release = step_named(workflow_path, "Attach to GitHub Release")
                self.assertIn("startsWith(github.ref, 'refs/tags/v')", release["if"])


class TestReleaseNotesBody(unittest.TestCase):
    """The release body comes from CHANGELOG.md, so nothing is pasted by hand."""

    BODY_PATH = "dist/release_notes.md"

    def _extract_step(self, workflow_path: Path) -> dict:
        return step_named(workflow_path, "Extract release notes")

    def test_both_workflows_extract_the_body_from_the_changelog(self):
        for workflow_path in (LINUX, WINDOWS):
            with self.subTest(workflow=workflow_path.name):
                command = self._extract_step(workflow_path)["run"]

                self.assertIn("utils/release_notes.py", command)
                self.assertIn('--tag "${{ github.ref_name }}"', command)
                self.assertIn(f"--output {self.BODY_PATH}", command)

    def test_the_extraction_step_is_tag_guarded(self):
        # A workflow_dispatch run must not fail because no tag exists.
        for workflow_path in (LINUX, WINDOWS):
            with self.subTest(workflow=workflow_path.name):
                step = self._extract_step(workflow_path)
                self.assertIn("startsWith(github.ref, 'refs/tags/v')", step["if"])

    def test_the_release_step_uses_the_generated_body(self):
        for workflow_path in (LINUX, WINDOWS):
            with self.subTest(workflow=workflow_path.name):
                release = step_named(workflow_path, "Attach to GitHub Release")

                self.assertEqual(release["with"]["body_path"], self.BODY_PATH)

    def test_the_extraction_runs_before_the_release_step(self):
        # The file must exist when action-gh-release reads body_path.
        for workflow_path in (LINUX, WINDOWS):
            with self.subTest(workflow=workflow_path.name):
                names = [step.get("name") for step in steps(workflow_path)]
                self.assertLess(
                    names.index("Extract release notes"),
                    names.index("Attach to GitHub Release"),
                )



if __name__ == "__main__":
    unittest.main()
