"""Tests for the shared monitor validation rules."""

import tempfile
import unittest
from pathlib import Path

from app.utils.monitor_validator import monitor_path_is_valid


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
        self.assertIsNone(
            monitor_path_is_valid("testdata/source/instant-monitor")
        )
        self.assertEqual(
            monitor_path_is_valid("testdata/source/does-not-exist"),
            "Monitor path 'testdata/source/does-not-exist' does not exist.",
        )


if __name__ == "__main__":
    unittest.main()
