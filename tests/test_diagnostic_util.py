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
from app.cli.profile_importer import ProfileImporter
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
        sqlite_handler = mock.Mock()
        return DiagnosticUtil(
            sqlite_handler=sqlite_handler,
            profile_importer=ProfileImporter(
                sqlite_handler=sqlite_handler, logger=logger
            ),
            logger=logger,
        )

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
        return DiagnosticUtil(
            sqlite_handler=sqlite_handler,
            profile_importer=ProfileImporter(
                sqlite_handler=sqlite_handler, logger=mock.Mock()
            ),
            logger=mock.Mock(),
        )

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
class DiagnosticUtilCheckProfileImportTest(unittest.TestCase):
    """``check_profile_import`` reports availability without importing.

    Importing is a CLI action (``mhub profile import``), so the diagnostic
    check must only notify: it never writes to the database and stays silent
    when there is nothing to import.
    """

    RCLONE_CONF = "[alpha]\ntype = ftp\nhost = example.com\n"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.conf_path = Path(self._tmpdir.name) / "rclone.conf"
        self.conf_path.write_text(self.RCLONE_CONF, encoding="utf-8")

    def _make(self, existing_names=None):
        sqlite_handler = mock.Mock()
        sqlite_handler.get_profiles.return_value = [
            {"name": name} for name in (existing_names or [])
        ]
        prompt = MockPromptService(inputs=[])
        logger = mock.Mock()
        importer = ProfileImporter(
            sqlite_handler=sqlite_handler, logger=logger, prompt=prompt
        )
        util = DiagnosticUtil(
            sqlite_handler=sqlite_handler,
            profile_importer=importer,
            logger=logger,
            prompt=prompt,
        )
        return util, sqlite_handler, prompt, logger

    def test_notifies_available_profiles_without_importing(self):
        util, sqlite_handler, prompt, logger = self._make()

        self.assertTrue(util.check_profile_import(rclone_config_path=self.conf_path))

        self.assertTrue(util.check_profile_import_result)
        sqlite_handler.add_profile.assert_not_called()
        logger.info.assert_called_once()
        self.assertIn("alpha", logger.info.call_args.args[0])
        self.assertIn("mhub profile import", prompt.output_text)

    def test_silent_when_nothing_to_import(self):
        util, sqlite_handler, prompt, logger = self._make(existing_names=["alpha"])

        self.assertTrue(util.check_profile_import(rclone_config_path=self.conf_path))

        sqlite_handler.add_profile.assert_not_called()
        logger.info.assert_not_called()
        self.assertEqual(prompt.outputs, [])

    def test_missing_config_is_silent(self):
        util, sqlite_handler, prompt, logger = self._make()

        self.assertTrue(
            util.check_profile_import(
                rclone_config_path=Path(self._tmpdir.name) / "missing.conf"
            )
        )

        sqlite_handler.add_profile.assert_not_called()
        logger.info.assert_not_called()
        self.assertEqual(prompt.outputs, [])

    def test_corrupt_config_offers_nothing_to_import(self):
        corrupt = Path(self._tmpdir.name) / "corrupt.conf"
        corrupt.write_text(
            '[alpha]\ntype = drive\ntoken = {"a":"1"}\n{"a":"2"}\n',
            encoding="utf-8",
        )
        util, sqlite_handler, prompt, logger = self._make()

        self.assertTrue(util.check_profile_import(rclone_config_path=corrupt))

        sqlite_handler.add_profile.assert_not_called()
        logger.info.assert_not_called()
        self.assertEqual(prompt.outputs, [])




if __name__ == "__main__":
    unittest.main()