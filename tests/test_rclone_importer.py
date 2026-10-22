"""Unit tests for :mod:`app.monitor.rclone_importer`.

Covers the shared rclone -> MonitorHub import machinery used by both the CLI
import action and the web GUI profiles page: reading, corruption detection,
importable filtering, and the section -> profile mapping.
"""

import tempfile
import unittest
from pathlib import Path

from app.monitor import rclone_importer
from app.utils import reference_data


class ReadRcloneConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)

    def _write(self, text: str, name: str = "rclone.conf") -> Path:
        path = self.tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_config_returns_sections(self):
        config = rclone_importer.read_rclone_config(
            self._write("[alpha]\ntype = s3\nprovider = AWS\n")
        )

        self.assertTrue(config.is_usable)
        self.assertEqual(
            config.sections, {"alpha": {"type": "s3", "provider": "AWS"}}
        )

    def test_missing_config_reports_not_found(self):
        config = rclone_importer.read_rclone_config(self.tmp_path / "missing.conf")

        self.assertFalse(config.is_usable)
        self.assertEqual(config.sections, {})
        self.assertIn("No profiles found in", config.errors[0])

    def test_corrupt_config_is_refused_wholesale(self):
        config = rclone_importer.read_rclone_config(
            self._write('[gamma]\ntype = drive\ntoken = {"a":"1"}\n{"a":"2"}\n')
        )

        self.assertFalse(config.is_usable)
        self.assertEqual(config.sections, {})
        self.assertTrue(any("Corrupt rclone config" in e for e in config.errors))
        self.assertIn("No profiles imported from", config.errors[-1])

    def test_empty_config_reports_not_found(self):
        config = rclone_importer.read_rclone_config(self._write(""))

        self.assertFalse(config.is_usable)
        self.assertIn("No profiles found in", config.errors[0])

    def test_percent_in_value_is_kept_literal(self):
        config = rclone_importer.read_rclone_config(
            self._write("[delta]\ntype = ftp\nhost = example.com\npass = p%40ss\n")
        )

        self.assertEqual(config.sections["delta"]["pass"], "p%40ss")


class FindCorruptLinesTest(unittest.TestCase):
    def test_wrapped_value_line_is_corrupt(self):
        text = '[gamma]\ntype = drive\ntoken = {"a":"1"}\n{"a":"2"}\n'

        self.assertEqual(
            rclone_importer.find_corrupt_lines(text),
            [(4, "gamma", '{"a":"2"}')],
        )

    def test_sections_blanks_and_comments_are_valid(self):
        text = "# comment\n\n[a]\ntype = ftp\nhost = example.com\n"

        self.assertEqual(rclone_importer.find_corrupt_lines(text), [])


class ImportableProfileNamesTest(unittest.TestCase):
    def test_excludes_already_imported_names(self):
        sections = {"alpha": {}, "beta": {}}

        self.assertEqual(
            rclone_importer.importable_profile_names(sections, {"alpha"}),
            ["beta"],
        )

    def test_empty_existing_names_returns_all(self):
        sections = {"alpha": {}, "beta": {}}

        self.assertEqual(
            rclone_importer.importable_profile_names(sections, set()),
            ["alpha", "beta"],
        )


class BuildProfileTest(unittest.TestCase):
    def test_type_and_remote_handler_are_set(self):
        section = {"type": "s3", "provider": "AWS", "access_key_id": "key"}

        profile_type, config, skipped = rclone_importer.build_profile(
            "s3-test", section
        )

        self.assertEqual(profile_type, "s3")
        self.assertEqual(config["provider"], "AWS")
        self.assertEqual(config["access_key_id"], "key")
        self.assertEqual(
            config[reference_data.CONFIG_REMOTE_HANDLER],
            reference_data.RCLONE_REMOTE_HANDLER,
        )
        self.assertEqual(skipped, [])

    def test_invalid_option_name_is_skipped(self):
        section = {"type": "ftp", "host": "example.com", "9bogus": "value"}

        profile_type, config, skipped = rclone_importer.build_profile(
            "ftp-test", section
        )

        self.assertNotIn("9bogus", config)
        self.assertEqual(skipped, ["9bogus"])


if __name__ == "__main__":
    unittest.main()
