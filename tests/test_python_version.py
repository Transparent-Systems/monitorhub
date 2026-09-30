"""Unit tests for :mod:`app.cli.python_version`.

These cover the pure helpers behind ``mhub config python``: the runtime version
read from ``sys.version_info``, locating/parsing the ``.python-version`` marker,
and the uv-style version-request matching.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.cli import python_version


class TestRuntimeVersion(unittest.TestCase):
    def test_reports_the_running_major_minor_patch(self):
        expected = ".".join(str(part) for part in sys.version_info[:3])
        self.assertEqual(python_version.runtime_python_version(), expected)

    def test_executable_is_sys_executable_when_not_frozen(self):
        with mock.patch.object(python_version, "is_frozen", return_value=False):
            self.assertEqual(python_version.runtime_executable(), sys.executable)

    def test_executable_is_labeled_when_frozen(self):
        with mock.patch.object(python_version, "is_frozen", return_value=True):
            self.assertEqual(
                python_version.runtime_executable(),
                python_version._FROZEN_LABEL,
            )


class TestReadPinnedVersion(unittest.TestCase):
    def _write(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".python-version", delete=False, encoding="utf-8"
        )
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        tmp.write(content)
        tmp.close()
        return Path(tmp.name)

    def test_plain_version(self):
        self.assertEqual(python_version.read_pinned_version(self._write("3.12\n")), "3.12")

    def test_skips_blank_lines_and_comments(self):
        content = "# uv pin\n\n   3.12.14   \n"
        self.assertEqual(
            python_version.read_pinned_version(self._write(content)), "3.12.14"
        )

    def test_comment_only_file_returns_none(self):
        self.assertIsNone(python_version.read_pinned_version(self._write("# nothing\n")))

    def test_empty_file_returns_none(self):
        self.assertIsNone(python_version.read_pinned_version(self._write("\n\n")))

    def test_missing_file_returns_none(self):
        missing = Path(tempfile.gettempdir()) / "does-not-exist-python-version"
        self.assertIsNone(python_version.read_pinned_version(missing))


class TestFindPinFile(unittest.TestCase):
    def test_finds_pin_walking_up_from_a_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".python-version").write_text("3.12\n", encoding="utf-8")
            nested = root / "app" / "cli"
            nested.mkdir(parents=True)

            self.assertEqual(
                python_version.find_pin_file(nested),
                root / ".python-version",
            )

    def test_accepts_a_string_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".python-version").write_text("3.12\n", encoding="utf-8")
            self.assertEqual(
                python_version.find_pin_file(str(root)),
                root / ".python-version",
            )

    def test_returns_none_when_no_pin_exists(self):
        # Point the search at a directory whose ancestors are guaranteed to lack
        # a pin by faking the filesystem probe rather than relying on /tmp.
        with mock.patch.object(Path, "is_file", return_value=False):
            self.assertIsNone(python_version.find_pin_file(Path("/nonexistent")))


class TestPinMatches(unittest.TestCase):
    def test_major_minor_pin_matches_patch_runtime(self):
        self.assertTrue(python_version.pin_matches("3.12", "3.12.14"))

    def test_exact_pin_matches_exactly(self):
        self.assertTrue(python_version.pin_matches("3.12.14", "3.12.14"))

    def test_major_only_pin_matches(self):
        self.assertTrue(python_version.pin_matches("3", "3.12.14"))

    def test_patch_difference_is_a_mismatch(self):
        self.assertFalse(python_version.pin_matches("3.12.15", "3.12.14"))

    def test_different_minor_is_a_mismatch(self):
        self.assertFalse(python_version.pin_matches("3.11", "3.12.14"))

    def test_pin_longer_than_runtime_is_a_mismatch(self):
        self.assertFalse(python_version.pin_matches("3.12.14.1", "3.12.14"))

    def test_empty_pin_is_a_mismatch(self):
        self.assertFalse(python_version.pin_matches("", "3.12.14"))


if __name__ == "__main__":
    unittest.main()
