"""Unit tests for :mod:`app.cli.profile_importer`.

Covers the rclone -> MonitorHub import: which profiles are found, the
interactive selection, the corruption detection that refuses a malformed
rclone.conf instead of repairing it, and the quiet read-only lookup used by the
diagnostic check.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.cli.profile_importer import ProfileImporter
from app.utils import reference_data
from tests.mock_prompt_service import MockPromptService


class TestFindCorruptLines(unittest.TestCase):
    """``_find_corrupt_lines`` flags lines that do not start with a key."""

    def test_wrapped_value_line_is_corrupt(self):
        text = (
            "[gamma]\n"
            "type = drive\n"
            'token = {"access_token":"AAA"}\n'
            '{"access_token":"BBB","token_type":"Bearer"}\n'
            "scope = drive\n"
        )

        corrupt = ProfileImporter._find_corrupt_lines(text)

        self.assertEqual(
            corrupt,
            [(4, "gamma", '{"access_token":"BBB","token_type":"Bearer"}')],
        )

    def test_stray_line_without_key_is_corrupt(self):
        text = "[a]\nhost = example.com\nnot a key line\n"

        self.assertEqual(
            ProfileImporter._find_corrupt_lines(text), [(3, "a", "not a key line")]
        )

    def test_keyless_line_before_any_section_reports_empty_section(self):
        text = "orphan line\n[a]\nhost = example.com\n"

        self.assertEqual(
            ProfileImporter._find_corrupt_lines(text), [(1, "", "orphan line")]
        )

    def test_sections_blanks_and_comments_are_valid(self):
        text = "# comment\n\n[a]\ntype = ftp\nhost = example.com\n"

        self.assertEqual(ProfileImporter._find_corrupt_lines(text), [])

    def test_every_offending_line_is_reported(self):
        text = "[a]\nbad one\nhost = x\nbad two\n"

        self.assertEqual(
            ProfileImporter._find_corrupt_lines(text),
            [(2, "a", "bad one"), (4, "a", "bad two")],
        )


class ProfileImporterImportTest(unittest.TestCase):
    """``import_profiles`` selection, mapping, and quiet lookup."""

    RCLONE_CONF = (
        "[alpha]\n"
        "type = s3\n"
        "provider = AWS\n"
        "\n"
        "[beta]\n"
        "type = ftp\n"
        "host = example.com\n"
    )

    # A token wrapped across unindented lines: the continuation line has no key,
    # so the config is corrupt and must not be imported (never repaired).
    CORRUPT_RCLONE_CONF = (
        "[gamma]\n"
        "type = drive\n"
        'token = {"access_token":"AAA"}\n'
        '{"access_token":"BBB","token_type":"Bearer"}\n'
        "scope = drive\n"
    )

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)

    def _write_rclone_conf(self, text: str) -> Path:
        path = self.tmp_path / "rclone.conf"
        path.write_text(text, encoding="utf-8")
        return path

    def _make(self, inputs, existing_names=None):
        sqlite_handler = mock.Mock()
        sqlite_handler.get_profiles.return_value = [
            {"name": name} for name in (existing_names or [])
        ]
        sqlite_handler.add_profile.return_value = 1
        prompt = MockPromptService(inputs=inputs)
        importer = ProfileImporter(
            sqlite_handler=sqlite_handler, logger=mock.Mock(), prompt=prompt
        )
        return importer, sqlite_handler, prompt

    def _imported_names(self, sqlite_handler):
        return [call.kwargs["name"] for call in sqlite_handler.add_profile.call_args_list]

    def test_select_all_imports_every_profile(self):
        importer, sqlite_handler, _ = self._make(["0"])

        importer.import_profiles(rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF))

        self.assertEqual(self._imported_names(sqlite_handler), ["alpha", "beta"])

    def test_select_single_imports_only_that_profile(self):
        importer, sqlite_handler, _ = self._make(["1", ""])

        importer.import_profiles(rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF))

        self.assertEqual(self._imported_names(sqlite_handler), ["alpha"])

    def test_select_none_imports_nothing(self):
        importer, sqlite_handler, prompt = self._make([""])

        importer.import_profiles(rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF))

        sqlite_handler.add_profile.assert_not_called()
        self.assertIn("No profiles selected", prompt.output_text)

    def test_already_imported_profiles_are_excluded(self):
        importer, sqlite_handler, _ = self._make(["0"], existing_names=["alpha"])

        importer.import_profiles(rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF))

        self.assertEqual(self._imported_names(sqlite_handler), ["beta"])

    def test_no_importable_profiles(self):
        importer, sqlite_handler, prompt = self._make([], existing_names=["alpha", "beta"])

        importer.import_profiles(rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF))

        sqlite_handler.add_profile.assert_not_called()
        self.assertIn("No profiles to import", prompt.output_text)

    def test_missing_config_path_reports_not_found(self):
        importer, sqlite_handler, prompt = self._make([])

        importer.import_profiles(rclone_config_path=self.tmp_path / "missing.conf")

        sqlite_handler.add_profile.assert_not_called()
        self.assertIn("No profiles found in", prompt.output_text)

    def test_import_maps_type_sets_rclone_route_and_adds_hints(self):
        importer, sqlite_handler, _ = self._make(["0"])

        importer.import_profiles(rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF))

        first_call = sqlite_handler.add_profile.call_args_list[0]
        self.assertEqual(first_call.kwargs["profile_type"], "s3")
        self.assertEqual(first_call.kwargs["config"]["provider_name"], "AWS")
        # MonitorHub owns the profile config now: no rclone.conf display hints.
        self.assertNotIn("comment", first_call.kwargs["config"])
        self.assertNotIn("important", first_call.kwargs["config"])
        # Imported profiles are rclone-managed, so they are routed to rclone
        # even though their type (s3) has a native handler.
        self.assertEqual(
            first_call.kwargs["config"][reference_data.CONFIG_REMOTE_HANDLER],
            reference_data.RCLONE_REMOTE_HANDLER,
        )

    def _first_imported_config(self, sqlite_handler) -> dict:
        return sqlite_handler.add_profile.call_args_list[0].kwargs["config"]

    def test_corrupt_config_imports_nothing(self):
        importer, sqlite_handler, prompt = self._make(["0"])

        imported = importer.import_profiles(
            rclone_config_path=self._write_rclone_conf(self.CORRUPT_RCLONE_CONF)
        )

        self.assertEqual(imported, [])
        sqlite_handler.add_profile.assert_not_called()
        self.assertIn("Corrupt rclone config", prompt.output_text)
        self.assertIn("No profiles imported", prompt.output_text)

    def test_corrupt_config_warning_names_section_and_line(self):
        importer, _, prompt = self._make(["1"])

        importer.import_profiles(
            rclone_config_path=self._write_rclone_conf(self.CORRUPT_RCLONE_CONF)
        )

        self.assertIn("line 4", prompt.output_text)
        self.assertIn("[gamma]", prompt.output_text)

    def test_percent_in_value_is_kept_literal(self):
        conf = "[delta]\ntype = ftp\nhost = example.com\npass = p%40ss%20word\n"
        importer, sqlite_handler, _ = self._make(["1"])

        importer.import_profiles(rclone_config_path=self._write_rclone_conf(conf))

        self.assertEqual(
            self._first_imported_config(sqlite_handler)["pass"], "p%40ss%20word"
        )

    def test_unexpected_key_is_skipped_with_warning(self):
        conf = "[epsilon]\ntype = ftp\nhost = example.com\n9bogus = value\n"
        importer, sqlite_handler, prompt = self._make(["1"])

        importer.import_profiles(rclone_config_path=self._write_rclone_conf(conf))

        config = self._first_imported_config(sqlite_handler)
        self.assertEqual(config["host"], "example.com")
        self.assertNotIn("9bogus", config)
        self.assertIn("skipping unexpected key", prompt.output_text)


class ProfileImporterFindTest(unittest.TestCase):
    """``find_importable_profiles`` is the quiet, read-only lookup."""

    RCLONE_CONF = "[alpha]\ntype = ftp\nhost = example.com\n"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)
        self.conf_path = self.tmp_path / "rclone.conf"
        self.conf_path.write_text(self.RCLONE_CONF, encoding="utf-8")

    def _make(self, existing_names=None):
        sqlite_handler = mock.Mock()
        sqlite_handler.get_profiles.return_value = [
            {"name": name} for name in (existing_names or [])
        ]
        prompt = MockPromptService(inputs=[])
        importer = ProfileImporter(
            sqlite_handler=sqlite_handler, logger=mock.Mock(), prompt=prompt
        )
        return importer, prompt

    def test_returns_names_not_yet_in_the_database(self):
        importer, _ = self._make()

        self.assertEqual(
            importer.find_importable_profiles(self.conf_path), ["alpha"]
        )

    def test_excludes_already_imported_names(self):
        importer, _ = self._make(existing_names=["alpha"])

        self.assertEqual(importer.find_importable_profiles(self.conf_path), [])

    def test_is_quiet_and_writes_nothing(self):
        importer, prompt = self._make()

        importer.find_importable_profiles(self.conf_path)

        self.assertEqual(prompt.outputs, [])
        importer.sqlite_handler.add_profile.assert_not_called()

    def test_missing_config_returns_empty_and_is_quiet(self):
        importer, prompt = self._make()

        self.assertEqual(
            importer.find_importable_profiles(self.tmp_path / "missing.conf"), []
        )
        self.assertEqual(prompt.outputs, [])


if __name__ == "__main__":
    unittest.main()


