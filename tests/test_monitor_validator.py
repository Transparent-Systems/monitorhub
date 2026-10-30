"""Tests for the shared monitor validation rules."""

import tempfile
import unittest
from pathlib import Path

from app.utils.monitor_validator import monitor_path_is_valid, profiles_required_error
from app.utils.project_paths import project_root


class TestProfilesRequiredError(unittest.TestCase):
    def test_no_profiles_is_rejected(self) -> None:
        expected = "Attach at least one profile: a monitor needs a profile to run."
        self.assertEqual(profiles_required_error([]), expected)
        self.assertEqual(profiles_required_error(None), expected)

    def test_one_profile_is_accepted(self) -> None:
        self.assertIsNone(profiles_required_error([{"id": 1, "name": "s3-test"}]))

    def test_many_profiles_are_accepted(self) -> None:
        self.assertIsNone(
            profiles_required_error(
                [{"id": 1, "name": "s3-test"}, {"id": 2, "name": "cmd-test"}]
            )
        )


class TestMonitorPathIsValid(unittest.TestCase):
    def test_existing_directory_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertIsNone(monitor_path_is_valid(temp_dir))

    def test_empty_path_is_rejected(self) -> None:
        self.assertEqual(
            monitor_path_is_valid(""), "Monitor path cannot be empty."
        )
        self.assertEqual(
            monitor_path_is_valid("   "), "Monitor path cannot be empty."
        )

    def test_missing_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = str(Path(temp_dir) / "missing")
            self.assertEqual(
                monitor_path_is_valid(missing),
                f"Monitor path '{missing}' does not exist.",
            )

    def test_file_path_is_rejected(self) -> None:
        file_path = str(Path(__file__).resolve())
        self.assertEqual(
            monitor_path_is_valid(file_path),
            f"Monitor path '{file_path}' is not a directory.",
        )

    def test_relative_path_is_resolved_against_project_root(self) -> None:
        # A relative path is resolved against the project root, so the probe has
        # to live there. tempfile creates it there, which keeps the test off a
        # directory that only exists on a developer's machine.
        with tempfile.TemporaryDirectory(dir=project_root()) as temp_dir:
            relative = Path(temp_dir).name
            self.assertIsNone(monitor_path_is_valid(relative))
            missing = f"{relative}-missing"
            self.assertEqual(
                monitor_path_is_valid(missing),
                f"Monitor path '{missing}' does not exist.",
            )


if __name__ == "__main__":
    unittest.main()
