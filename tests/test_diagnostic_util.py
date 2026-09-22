"""Unit tests for :mod:`app.cli.diagnostic_util`.

Covers the ``DiagnosticUtil`` constructor contract: when ``logger=None`` the
instance must fall back to the shared module logger without mutating it (no
handler stacking / no duplicate logging, no forced level override), and an
explicitly injected logger must be honoured.  These tests are late regressions
for the constructor previously creating a fresh ``StreamHandler`` and forcing
``DEBUG`` on ``logging.getLogger(__name__)`` on every construction.
"""

import logging
import unittest
from unittest import mock

from app.cli.diagnostic_util import DiagnosticUtil

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
    """``check_rclone_dependency`` must route by ``profile_type``.

    Regression: it previously read a ``config["handler"]`` key that nothing in
    the application writes any more, so every profile was skipped and the check
    silently reported success even when an rclone-backed profile existed.
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
                {"name": "s3-test", "profile_type": "s3", "config": {}},
                {"name": "cmd", "profile_type": "event_command", "config": {}},
            ]
        )
        with mock.patch.object(
            util, "_check_rclone_exists", return_value=False
        ) as check:
            self.assertTrue(util.check_rclone_dependency())
        check.assert_not_called()

    def test_legacy_handler_key_is_ignored(self):
        # A stale config["handler"] must not force an rclone check for a native
        # profile type: routing is driven by profile_type.
        util = self._make(
            [
                {
                    "name": "s3-test",
                    "profile_type": "s3",
                    "config": {"handler": "rclone"},
                }
            ]
        )
        with mock.patch.object(
            util, "_check_rclone_exists", return_value=False
        ) as check:
            self.assertTrue(util.check_rclone_dependency())
        check.assert_not_called()

    def test_no_profiles_returns_true(self):
        util = self._make([])
        self.assertTrue(util.check_rclone_dependency())


if __name__ == "__main__":
    unittest.main()