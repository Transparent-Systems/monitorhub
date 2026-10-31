"""Tests for the shared monitor validation rules."""

import tempfile
import unittest
from pathlib import Path

from app.utils.monitor_validator import (
    has_remote_profile,
    monitor_path_is_valid,
    profiles_required_error,
    remote_path_required_error,
)
from app.utils.project_paths import project_root

REMOTE_PROFILE = {"id": 1, "name": "s3-test", "profile_type": "s3"}
COMMAND_PROFILE = {"id": 2, "name": "cmd-test", "profile_type": "event_command"}


class TestHasRemoteProfile(unittest.TestCase):
    def test_remote_profile_is_detected(self) -> None:
        self.assertTrue(has_remote_profile([REMOTE_PROFILE]))

    def test_command_profile_is_not_remote(self) -> None:
        self.assertFalse(has_remote_profile([COMMAND_PROFILE]))

    def test_mixed_profiles_are_remote(self) -> None:
        self.assertTrue(has_remote_profile([COMMAND_PROFILE, REMOTE_PROFILE]))

    def test_empty_or_none_is_not_remote(self) -> None:
        self.assertFalse(has_remote_profile([]))
        self.assertFalse(has_remote_profile(None))


class TestRemotePathRequiredError(unittest.TestCase):
    def test_remote_profile_without_remote_path_is_rejected(self) -> None:
        self.assertEqual(
            remote_path_required_error("", [REMOTE_PROFILE]),
            "Remote path is required because profile 's3-test' is a remote profile.",
        )
        self.assertEqual(
            remote_path_required_error(None, [REMOTE_PROFILE]),
            "Remote path is required because profile 's3-test' is a remote profile.",
        )
        self.assertEqual(
            remote_path_required_error("   ", [REMOTE_PROFILE]),
            "Remote path is required because profile 's3-test' is a remote profile.",
        )

    def test_remote_profile_with_remote_path_is_accepted(self) -> None:
        self.assertIsNone(remote_path_required_error("remote:dest", [REMOTE_PROFILE]))

    def test_command_only_monitor_needs_no_remote_path(self) -> None:
        """A command profile runs a command and never touches a remote path."""
        self.assertIsNone(remote_path_required_error("", [COMMAND_PROFILE]))
        self.assertIsNone(remote_path_required_error(None, [COMMAND_PROFILE]))
        self.assertIsNone(remote_path_required_error("", []))
        self.assertIsNone(remote_path_required_error("", None))

    def test_mixed_profiles_still_require_a_remote_path(self) -> None:
        self.assertEqual(
            remote_path_required_error("", [COMMAND_PROFILE, REMOTE_PROFILE]),
            "Remote path is required because profile 's3-test' is a remote profile.",
        )


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
