"""Guard the release workflows: both binaries must be built and published.

CI is the one place a mistake is expensive and invisible - the GUI binary was
silently absent from the artifacts because the workflow only ran the default
build target.
"""

import unittest
from pathlib import Path

import yaml

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
LINUX = WORKFLOW_DIR / "build-linux.yml"
WINDOWS = WORKFLOW_DIR / "build-windows.yml"


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


class TestBothTargetsAreBuilt(unittest.TestCase):
    def test_linux_builds_the_cli_and_the_gui(self):
        commands = run_commands(LINUX)
        self.assertIn("build_project.py cli", commands)
        self.assertIn("build_project.py gui", commands)

    def test_windows_builds_the_cli_and_the_gui(self):
        commands = run_commands(WINDOWS)
        self.assertIn("build_project.py cli", commands)
        self.assertIn("build_project.py gui", commands)


class TestBothBinariesArePublished(unittest.TestCase):
    def _uploaded(self, workflow_path: Path) -> list[str]:
        upload = step_named(workflow_path, "Upload artifact")
        return upload["with"]["path"].split()

    def _released(self, workflow_path: Path) -> list[str]:
        release = step_named(workflow_path, "Attach to GitHub Release")
        return release["with"]["files"].split()

    def test_linux_uploads_and_releases_both_binaries(self):
        for files in (self._uploaded(LINUX), self._released(LINUX)):
            self.assertIn("dist/mhub", files)
            self.assertIn("dist/mhub.sha256", files)
            self.assertIn("dist/mhub-gui", files)
            self.assertIn("dist/mhub-gui.sha256", files)

    def test_windows_uploads_and_releases_both_executables(self):
        for files in (self._uploaded(WINDOWS), self._released(WINDOWS)):
            self.assertIn("dist/mhub.exe", files)
            self.assertIn("dist/mhub.exe.sha256", files)
            self.assertIn("dist/mhub-gui.exe", files)
            self.assertIn("dist/mhub-gui.exe.sha256", files)


class TestChecksumsCoverBothBinaries(unittest.TestCase):
    def test_linux_checksums_both_binaries(self):
        command = step_named(LINUX, "Generate SHA256 checksums")["run"]
        self.assertIn("sha256sum mhub > mhub.sha256", command)
        self.assertIn("sha256sum mhub-gui > mhub-gui.sha256", command)

    def test_windows_checksums_both_executables(self):
        command = step_named(WINDOWS, "Generate SHA256 checksums")["run"]
        self.assertIn("mhub", command)
        self.assertIn("mhub-gui", command)
        self.assertIn(".exe.sha256", command)


if __name__ == "__main__":
    unittest.main()
