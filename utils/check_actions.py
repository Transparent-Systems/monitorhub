"""
Script: check_actions.py
Description:
    Report the Node.js runtime that every GitHub Action used by the workflows
    declares.

    The runner reads each action's ``action.yml`` and runs it on the runtime in
    its ``runs.using`` field. Node 20 was removed from the GitHub-hosted runners
    on 2026-09-23, so an action that still declares ``node20`` is force-migrated
    to node24 and warns on every run. This script reads the truth from upstream
    - the same file the runner reads - rather than relying on that warning,
    which only names actions that actually executed in a given run.

    Actions pinned to a branch or a commit SHA cannot be compared, and local
    (``./...``) or ``docker://`` actions have no Node runtime; those are skipped
    or reported as ``n/a``.

Usage:
    .venv/bin/python utils/check_actions.py
    .venv/bin/python utils/check_actions.py --workflow .github/workflows/build-windows.yml

Exit codes:
    0  every Node action declares the required runtime
    1  at least one action needs upgrading
    2  something could not be checked (unreadable workflow, failed request)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DEFAULT_WORKFLOW_GLOB = "*.yml"

# The runtime every action must declare. Node 20 is gone from the runners, so
# anything older is force-migrated and warns on every run.
REQUIRED_RUNTIME = "node24"

# Runtimes that are not Node-based: there is nothing to upgrade.
NON_NODE_RUNTIMES = frozenset({"composite", "docker"})

METADATA_URL = "https://raw.githubusercontent.com/{slug}/{ref}/action.yml"
LATEST_RELEASE_URL = "https://api.github.com/repos/{slug}/releases/latest"
HTTP_TIMEOUT_SECONDS = 20
USER_AGENT = "monitorhub-check-actions"

EXIT_OK = 0
EXIT_NEEDS_UPGRADE = 1
EXIT_CANNOT_CHECK = 2


class ActionCheckError(RuntimeError):
    """Raised when a workflow or an action's metadata cannot be read."""


@dataclass(frozen=True)
class ActionRef:
    """One ``uses:`` reference, e.g. ``actions/upload-artifact@v7``."""

    raw: str
    slug: str
    ref: str

    @property
    def major(self) -> int | None:
        """The major version, or None when pinned to a branch or a SHA."""
        candidate = self.ref.lstrip("v").split(".")[0]
        return int(candidate) if candidate.isdigit() else None


@dataclass(frozen=True)
class CheckResult:
    """What the check found for one action."""

    ref: ActionRef
    runtime: str | None
    suggestion: str | None = None

    @property
    def is_node_action(self) -> bool:
        return self.runtime is not None and self.runtime not in NON_NODE_RUNTIMES

    @property
    def needs_upgrade(self) -> bool:
        return self.is_node_action and self.runtime != REQUIRED_RUNTIME

    @property
    def cannot_check(self) -> bool:
        return self.runtime is None

    @property
    def verdict(self) -> str:
        if self.cannot_check:
            return "unknown"
        if not self.is_node_action:
            return "n/a"
        return "UPGRADE" if self.needs_upgrade else "ok"


def parse_action_ref(raw: str) -> ActionRef | None:
    """Parse a ``uses:`` value; return None for local or docker actions."""
    raw = raw.strip()
    if raw.startswith(("./", "../", "docker://")):
        return None

    slug, separator, ref = raw.partition("@")
    if not separator or "/" not in slug or not ref:
        raise ActionCheckError(f"Cannot parse action reference '{raw}'")
    return ActionRef(raw=raw, slug=slug, ref=ref)


def workflow_steps(workflow: object) -> list[dict]:
    """Return every step of every job in a parsed workflow document."""
    if not isinstance(workflow, dict):
        return []
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return []
    return [
        step
        for job in jobs.values()
        if isinstance(job, dict)
        for step in (job.get("steps") or [])
        if isinstance(step, dict)
    ]


def action_refs(workflow_paths: list[Path]) -> list[ActionRef]:
    """Return the unique action references used by the given workflows, sorted."""
    found: dict[str, ActionRef] = {}
    for path in workflow_paths:
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ActionCheckError(f"Cannot read {path}: {error}") from error

        for step in workflow_steps(workflow):
            uses = step.get("uses")
            if not isinstance(uses, str) or not uses.strip():
                continue
            parsed = parse_action_ref(uses)
            if parsed is not None:
                found.setdefault(parsed.raw, parsed)

    return [found[raw] for raw in sorted(found)]


def fetch_text(url: str) -> str:
    """GET url and return its body, raising ActionCheckError on failure."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        # Raises the rate limit for the latest-release lookups.
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as error:
        raise ActionCheckError(f"GET {url} failed: {error}") from error


def runtime_from_metadata(metadata: str) -> str | None:
    """Return the ``runs.using`` runtime of an action.yml, or None."""
    try:
        document = yaml.safe_load(metadata)
    except yaml.YAMLError:
        return None
    if not isinstance(document, dict):
        return None
    runs = document.get("runs")
    if not isinstance(runs, dict):
        return None
    runtime = runs.get("using")
    return str(runtime) if runtime else None


def action_runtime(ref: ActionRef) -> str | None:
    """Fetch ref's metadata and return the runtime it declares."""
    try:
        metadata = fetch_text(METADATA_URL.format(slug=ref.slug, ref=ref.ref))
    except ActionCheckError:
        return None
    return runtime_from_metadata(metadata)


def latest_release_ref(ref: ActionRef) -> ActionRef | None:
    """Best-effort: the newest release tag of the action, or None."""
    try:
        payload = json.loads(fetch_text(LATEST_RELEASE_URL.format(slug=ref.slug)))
    except (ActionCheckError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        return None
    return ActionRef(raw=f"{ref.slug}@{tag}", slug=ref.slug, ref=tag)


def check_ref(ref: ActionRef) -> CheckResult:
    """Check one action, looking up what to upgrade to when it is behind."""
    runtime = action_runtime(ref)
    if runtime is None or runtime in NON_NODE_RUNTIMES or runtime == REQUIRED_RUNTIME:
        return CheckResult(ref=ref, runtime=runtime)

    latest = latest_release_ref(ref)
    if latest is None:
        return CheckResult(ref=ref, runtime=runtime)

    latest_runtime = action_runtime(latest)
    return CheckResult(
        ref=ref,
        runtime=runtime,
        suggestion=f"{latest.ref} ({latest_runtime or 'unknown'})",
    )


def format_report(results: list[CheckResult]) -> str:
    """Render the results as an aligned table."""
    rows = [
        (
            result.ref.raw,
            result.ref.ref,
            result.runtime or "?",
            result.verdict,
            result.suggestion or "",
        )
        for result in results
    ]
    headers = ("Action", "Pinned", "Runtime", "Verdict", "Upgrade to")
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]

    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(
            cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
        ).rstrip()

    return "\n".join([line(headers), *(line(row) for row in rows)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report the Node.js runtime every workflow action declares, by "
            "reading the action.yml the runner itself reads."
        )
    )
    parser.add_argument(
        "--workflow",
        action="append",
        default=None,
        metavar="<PATH>",
        help=(
            "Workflow file to check (repeatable; default: every *.yml in "
            f"{WORKFLOW_DIR.relative_to(REPO_ROOT)})"
        ),
    )
    args = parser.parse_args(argv)

    paths = (
        [Path(path) for path in args.workflow]
        if args.workflow
        else sorted(WORKFLOW_DIR.glob(DEFAULT_WORKFLOW_GLOB))
    )

    try:
        refs = action_refs(paths)
    except ActionCheckError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_CANNOT_CHECK

    if not refs:
        print(f"No actions found in {', '.join(str(path) for path in paths)}.")
        return EXIT_OK

    results = [check_ref(ref) for ref in refs]
    print(format_report(results))

    behind = [result for result in results if result.needs_upgrade]
    unknown = [result for result in results if result.cannot_check]
    for result in behind:
        print(
            f"\nNeeds upgrading: {result.ref.raw} declares {result.runtime}, "
            f"but {REQUIRED_RUNTIME} is required."
        )
    for result in unknown:
        print(f"\nCould not be checked: {result.ref.raw}")

    if behind:
        return EXIT_NEEDS_UPGRADE
    if unknown:
        return EXIT_CANNOT_CHECK

    node_actions = [result for result in results if result.is_node_action]
    print(f"\nAll {len(node_actions)} Node actions declare {REQUIRED_RUNTIME}.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

    def needs_upgrade(self) -> bool:
        return self.is_node_action and self.runtime != REQUIRED_RUNTIME

    @property
    def cannot_check(self) -> bool:
        return self.runtime is None

    @property
    def verdict(self) -> str:
        if self.cannot_check:
            return "unknown"
        if not self.is_node_action:
            return "n/a"
        return "UPGRADE" if self.needs_upgrade else "ok"
