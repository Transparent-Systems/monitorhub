"""Unit tests for :mod:`app.cli.diagnostic_util`.

Covers the ``DiagnosticUtil`` constructor contract: when ``logger=None`` the
instance must fall back to the shared module logger without mutating it (no
handler stacking / no duplicate logging, no forced level override), and an
explicitly injected logger must be honoured.  These tests are late regressions
for the constructor previously creating a fresh ``StreamHandler`` and forcing
``DEBUG`` on ``logging.getLogger(__name__)`` on every construction.
"""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.cli.diagnostic_util import DiagnosticUtil
from app.utils import reference_data
from tests.mock_prompt_service import MockPromptService

MODULE_LOGGER_NAME = "app.cli.diagnostic_util"


class DiagnosticUtilConstructorTest(unittest.TestCase):
    """The constructor must not mutate the shared module logger."""

    def setUp(self):
        self.module_logger = logging.getLogger(MODULE_LOGGER_NAME)
        self.handlers_before = list(self.module_logger.handlers)
        self.level_before = self.module_logger.level

    def tearDown(self):
        # Leave the module logger exactly as found, even on test failure.
        self.module_logger.handlers[:] = self.handlers_before
        self.module_logger.setLevel(self.level_before)

    def _make(self, logger=None):
        return DiagnosticUtil(sqlite_handler=mock.Mock(), logger=logger)

    def test_logger_none_does_not_add_handlers(self):
        self._make(logger=None)
        self._make(logger=None)

        self.assertEqual(self.module_logger.handlers, self.handlers_before)

    def test_logger_none_uses_shared_module_logger(self):
        first = self._make(logger=None)
        second = self._make(logger=None)

        self.assertIs(first.logger, self.module_logger)
        self.assertIs(second.logger, self.module_logger)
        self.assertIs(first.logger, second.logger)

    def test_logger_none_does_not_force_debug_level(self):
        self._make(logger=None)

        self.assertEqual(self.module_logger.level, self.level_before)

    def test_explicit_logger_is_used(self):
        custom_logger = logging.getLogger("tests.custom.diagnostic_util")

        instance = self._make(logger=custom_logger)

        self.assertIs(instance.logger, custom_logger)


class DiagnosticUtilRcloneDependencyTest(unittest.TestCase):
    """``check_rclone_dependency`` must route by the ``remote_handler`` key.

    Regression: it previously read a ``config["handler"]`` key that nothing in
    the application wrote, so every profile was skipped and the check silently
    reported success even when an rclone-backed profile existed.  Routing is now
    the same ``remote_handler`` resolution used by ``handler_factory``, so a
    native profile type switched to rclone (e.g. s3) is checked too.
    """

    def _make(self, profiles):
        sqlite_handler = mock.Mock()
        sqlite_handler.get_profiles.return_value = profiles
        return DiagnosticUtil(sqlite_handler=sqlite_handler, logger=mock.Mock())

    def test_rclone_profile_triggers_dependency_check(self):
        util = self._make([{"name": "ftp-test", "profile_type": "ftp", "config": {}}])
        with mock.patch.object(
            util, "_check_rclone_exists", return_value=True
        ) as check:
            self.assertTrue(util.check_rclone_dependency())
        check.assert_called_once()

    def test_missing_rclone_reports_failure(self):
        util = self._make([{"name": "ftp-test", "profile_type": "ftp", "config": {}}])
        with mock.patch.object(util, "_check_rclone_exists", return_value=False):
            self.assertFalse(util.check_rclone_dependency())
        self.assertFalse(util.check_rclone_dependency_result)

    def test_native_and_command_profiles_do_not_need_rclone(self):
        util = self._make(
            [
                {
                    "name": "s3-test",
                    "profile_type": "s3",
                    "config": {reference_data.CONFIG_REMOTE_HANDLER: "s3"},
                },
                {"name": "cmd", "profile_type": "event_command", "config": {}},
            ]
        )
        with mock.patch.object(
            util, "_check_rclone_exists", return_value=False
        ) as check:
            self.assertTrue(util.check_rclone_dependency())
        check.assert_not_called()

    def test_native_profile_routed_to_rclone_needs_rclone(self):
        # An s3 profile switched to the rclone handler must trigger the check.
        util = self._make(
            [
                {
                    "name": "s3-test",
                    "profile_type": "s3",
                    "config": {
                        reference_data.CONFIG_REMOTE_HANDLER: reference_data.RCLONE_REMOTE_HANDLER
                    },
                }
            ]
        )
        with mock.patch.object(
            util, "_check_rclone_exists", return_value=True
        ) as check:
            self.assertTrue(util.check_rclone_dependency())
        check.assert_called_once()

    def test_no_profiles_returns_true(self):
        util = self._make([])
        self.assertTrue(util.check_rclone_dependency())


class TestFoldWrappedValues(unittest.TestCase):
    """``_fold_wrapped_values`` joins wrapped config lines into their value."""

    def test_unindented_wrap_is_folded(self):
        text = (
            "[gamma]\n"
            "type = drive\n"
            'token = {"access_token":"AAA",\n'
            '"token_type":"Bearer",\n'
            '"expiry":"2026-01-01"}\n'
            "scope = drive\n"
        )

        folded, wrapped = DiagnosticUtil._fold_wrapped_values(text)

        self.assertEqual(
            folded,
            "[gamma]\n"
            "type = drive\n"
            'token = {"access_token":"AAA","token_type":"Bearer","expiry":"2026-01-01"}\n'
            "scope = drive",
        )
        self.assertEqual(wrapped, [("gamma", "token")])

    def test_indented_wrap_is_folded(self):
        text = '[a]\ntoken = {"x":"1",\n  "y":"2"}\n'

        folded, wrapped = DiagnosticUtil._fold_wrapped_values(text)

        self.assertEqual(folded, '[a]\ntoken = {"x":"1","y":"2"}')
        self.assertEqual(wrapped, [("a", "token")])

    def test_sections_blanks_and_comments_are_preserved(self):
        text = "[a]\n# comment\n\n[b]\nhost = example.com\n"

        folded, wrapped = DiagnosticUtil._fold_wrapped_values(text)

        self.assertEqual(folded.splitlines(), text.splitlines())
        self.assertEqual(wrapped, [])

    def test_each_wrapped_value_is_reported_once(self):
        text = '[a]\ntoken = {"x":"1",\n"y":"2"}\nsecret = ab\ncd\n'

        folded, wrapped = DiagnosticUtil._fold_wrapped_values(text)

        self.assertEqual(wrapped, [("a", "token"), ("a", "secret")])
        self.assertIn("secret = abcd", folded)


class DiagnosticUtilProfileImportTest(unittest.TestCase):
    """``check_profile_import`` selection and legacy confirmation modes.

    ``select=True`` (used by ``profile import``) lets the user choose none,
    all, or individual rclone profiles; the default ``select=False`` (used by
    ``config test``) keeps the original all-or-nothing Y/n confirmation.
    """

    RCLONE_CONF = (
        "[alpha]\n"
        "type = s3\n"
        "provider = AWS\n"
        "\n"
        "[beta]\n"
        "type = ftp\n"
        "host = example.com\n"
    )

    # A token wrapped across unindented lines: configparser would turn the
    # extra lines into bogus keys before the folding fix.
    WRAPPED_RCLONE_CONF = (
        "[gamma]\n"
        "type = drive\n"
        'token = {"access_token":"AAA",\n'
        '"token_type":"Bearer",\n'
        '"expiry":"2026-01-01"}\n'
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
        util = DiagnosticUtil(
            sqlite_handler=sqlite_handler, logger=mock.Mock(), prompt=prompt
        )
        return util, sqlite_handler, prompt

    def _imported_names(self, sqlite_handler):
        return [call.kwargs["name"] for call in sqlite_handler.add_profile.call_args_list]

    def test_select_all_imports_every_profile(self):
        util, sqlite_handler, _ = self._make(["0"])

        util.check_profile_import(
            select=True, rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF)
        )

        self.assertEqual(self._imported_names(sqlite_handler), ["alpha", "beta"])

    def test_select_single_imports_only_that_profile(self):
        util, sqlite_handler, _ = self._make(["1", ""])

        util.check_profile_import(
            select=True, rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF)
        )

        self.assertEqual(self._imported_names(sqlite_handler), ["alpha"])

    def test_select_none_imports_nothing(self):
        util, sqlite_handler, prompt = self._make([""])

        util.check_profile_import(
            select=True, rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF)
        )

        sqlite_handler.add_profile.assert_not_called()
        self.assertIn("No profiles selected", prompt.output_text)

    def test_config_test_mode_yes_imports_all(self):
        util, sqlite_handler, _ = self._make(["y"])

        util.check_profile_import(
            rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF)
        )

        self.assertEqual(self._imported_names(sqlite_handler), ["alpha", "beta"])

    def test_config_test_mode_no_cancels(self):
        util, sqlite_handler, prompt = self._make(["n"])

        util.check_profile_import(
            rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF)
        )

        sqlite_handler.add_profile.assert_not_called()
        self.assertIn("Profile import cancelled", prompt.output_text)

    def test_already_imported_profiles_are_excluded(self):
        util, sqlite_handler, _ = self._make(["0"], existing_names=["alpha"])

        util.check_profile_import(
            select=True, rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF)
        )

        self.assertEqual(self._imported_names(sqlite_handler), ["beta"])

    def test_no_importable_profiles(self):
        util, sqlite_handler, prompt = self._make(
            [], existing_names=["alpha", "beta"]
        )

        util.check_profile_import(
            select=True, rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF)
        )

        sqlite_handler.add_profile.assert_not_called()
        self.assertIn("No profiles to import", prompt.output_text)

    def test_missing_config_path_reports_not_found(self):
        util, sqlite_handler, prompt = self._make([])

        util.check_profile_import(
            select=True, rclone_config_path=self.tmp_path / "missing.conf"
        )

        sqlite_handler.add_profile.assert_not_called()
        self.assertIn("No profiles found in", prompt.output_text)

    def test_import_maps_type_sets_rclone_route_and_adds_hints(self):
        util, sqlite_handler, _ = self._make(["0"])

        util.check_profile_import(
            select=True, rclone_config_path=self._write_rclone_conf(self.RCLONE_CONF)
        )

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

    def test_wrapped_value_is_folded_into_one_key(self):
        util, sqlite_handler, _ = self._make(["1"])

        util.check_profile_import(
            select=True,
            rclone_config_path=self._write_rclone_conf(self.WRAPPED_RCLONE_CONF),
        )

        call = sqlite_handler.add_profile.call_args_list[0]
        config = call.kwargs["config"]
        # ``type`` becomes the profile type, not a config key.
        self.assertEqual(call.kwargs["profile_type"], "drive")
        self.assertEqual(
            config["token"],
            '{"access_token":"AAA","token_type":"Bearer","expiry":"2026-01-01"}',
        )
        self.assertEqual(config["scope"], "drive")
        # The wrapped lines must not become bogus keys.
        self.assertNotIn('{"access_token"', config)
        self.assertNotIn('"token_type"', config)

    def test_wrapped_value_warning_is_printed(self):
        util, _, prompt = self._make(["1"])

        util.check_profile_import(
            select=True,
            rclone_config_path=self._write_rclone_conf(self.WRAPPED_RCLONE_CONF),
        )

        self.assertIn("wrapped across lines", prompt.output_text)
        self.assertIn("[gamma]", prompt.output_text)

    def test_percent_in_value_is_kept_literal(self):
        conf = "[delta]\ntype = ftp\nhost = example.com\npass = p%40ss%20word\n"
        util, sqlite_handler, _ = self._make(["1"])

        util.check_profile_import(
            select=True, rclone_config_path=self._write_rclone_conf(conf)
        )

        self.assertEqual(
            self._first_imported_config(sqlite_handler)["pass"], "p%40ss%20word"
        )

    def test_unexpected_key_is_skipped_with_warning(self):
        conf = "[epsilon]\ntype = ftp\nhost = example.com\n9bogus = value\n"
        util, sqlite_handler, prompt = self._make(["1"])

        util.check_profile_import(
            select=True, rclone_config_path=self._write_rclone_conf(conf)
        )

        config = self._first_imported_config(sqlite_handler)
        self.assertEqual(config["host"], "example.com")
        self.assertNotIn("9bogus", config)
        self.assertIn("skipping unexpected key", prompt.output_text)


if __name__ == "__main__":
    unittest.main()