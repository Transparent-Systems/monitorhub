"""Mock-data driven unit tests for the monitor and profile commands.

These tests exercise the interactive command flows (``monitor.new``,
``profile.edit``, etc.) using a :class:`MockPromptService` that supplies
scripted input and captures output, rather than requiring a human at the
keyboard. They run against the dedicated unittest database in
``testdb/unittest`` (independent from ``testdb/dev``).
"""

import logging
import unittest
from unittest import mock

from scripts.commands import Commands, build_commands
from tests.database_test_data import DatabaseTestData
from tests.mock_prompt_service import MockPromptService


class TestCommands(unittest.TestCase):
    """Mock-driven unit tests for the wired command handlers."""

    logger = logging.getLogger(__name__)

    def setUp(self) -> None:
        self.db_dir = "testdb/unittest"
        self.dotenv_path = "testdb/unittest/.env"
        self.database_test_data = DatabaseTestData(
            logger=self.logger,
            db_dir=self.db_dir,
            dotenv_path=self.dotenv_path,
        )
        self.database_test_data.remove_test_data()
        self.database_test_data.load_test_data()
        self._commands: Commands | None = None

    def tearDown(self) -> None:
        if self._commands is not None:
            self._commands.sqlite_handler.close()
        self.database_test_data.remove_test_data()
        self.database_test_data.sqlite_handler.close()

    def _make_commands(
        self,
        inputs: list[str],
        diagnostic_util: mock.Mock | None = None,
    ) -> tuple[Commands, MockPromptService]:
        """Build a wired ``Commands`` bundle around a scripted mock prompt."""
        mock_prompt = MockPromptService(inputs=inputs)
        commands = build_commands(
            logger=self.logger,
            db_dir=self.db_dir,
            prompt=mock_prompt,
            diagnostic_util=diagnostic_util,
        )
        self._commands = commands
        return commands, mock_prompt

    def test_database_info(self):
        commands, mock_prompt = self._make_commands([])
        commands.database.info()
        self.assertIn("Location of SQLite database", mock_prompt.output_text)

    def test_database_version(self):
        commands, mock_prompt = self._make_commands([])
        commands.database.version()
        text = mock_prompt.output_text
        self.assertIn("Version of SQLite database", text)
        self.assertIn("Supported database schema version", text)
        self.assertIn("Database schema is up to date.", text)

    def test_database_upgrade_already_up_to_date(self):
        commands, mock_prompt = self._make_commands([])
        commands.database.upgrade()
        self.assertIn("already up to date", mock_prompt.output_text)

    def test_monitor_show(self):
        commands, mock_prompt = self._make_commands([])
        commands.monitor.show()
        text = mock_prompt.output_text
        self.assertIn("Instant Monitor 1", text)
        self.assertIn("Backup Monitor 1", text)
        self.assertIn("Restore Monitor 1", text)

    def test_monitor_new(self):
        commands, _ = self._make_commands(
            ["my-monitor", "/tmp/source", "remote:dest", "1", "", ""]
        )
        commands.monitor.new()
        monitor = commands.sqlite_handler.get_monitor(monitor_name="my-monitor")
        self.assertTrue(monitor)
        self.assertEqual(monitor["monitor_type"], "instant")
        self.assertEqual(monitor["config"].get("exclude_patterns"), [])

    def test_monitor_edit(self):
        first_id = self.database_test_data.sqlite_handler.get_monitors()[0]["id"]
        commands, _ = self._make_commands(
            [str(first_id), "renamed-monitor", "", "", "", "", ""]
        )
        commands.monitor.edit()
        monitor = commands.sqlite_handler.get_monitor(monitor_id=first_id)
        self.assertEqual(monitor["name"], "renamed-monitor")

    def test_monitor_delete(self):
        first_id = self.database_test_data.sqlite_handler.get_monitors()[0]["id"]
        commands, _ = self._make_commands([str(first_id), str(first_id)])
        commands.monitor.delete()
        monitor = commands.sqlite_handler.get_monitor(monitor_id=first_id)
        self.assertFalse(monitor)

    def test_profile_show(self):
        commands, mock_prompt = self._make_commands([])
        commands.profile.show()
        text = mock_prompt.output_text
        self.assertIn("s3-test", text)
        self.assertIn("command-profile-1", text)

    def test_profile_new_command(self):
        commands, _ = self._make_commands(
            ["2", "my-cmd-profile", "echo hello", "", "", "", "n"]
        )
        commands.profile.new()
        profile = commands.sqlite_handler.get_profile(profile_name="my-cmd-profile")
        self.assertTrue(profile)
        self.assertEqual(profile["profile_type"], "event_command")
        self.assertEqual(profile["config"]["command"], "echo hello")

    def test_profile_edit_command(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-profile-1"
        )["id"]
        commands, _ = self._make_commands(
            [str(profile_id), "echo updated", "", "", "", ""]
        )
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["command"], "echo updated")

    def test_profile_delete(self):
        first_id = self.database_test_data.sqlite_handler.get_profiles()[0]["id"]
        commands, _ = self._make_commands([str(first_id), str(first_id)])
        commands.profile.delete()
        profile = commands.sqlite_handler.get_profile(profile_id=first_id)
        self.assertFalse(profile)

    def test_profile_test_command(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-profile-1"
        )["id"]
        commands, mock_prompt = self._make_commands([])
        commands.profile.test(profile_id=profile_id)
        text = mock_prompt.output_text
        self.assertIn("Testing command profile: command-profile-1", text)
        self.assertNotIn("Test failed", text)

    def test_version(self):
        commands, mock_prompt = self._make_commands([])
        commands.app.version()
        self.assertIn("MonitorHub version:", mock_prompt.output_text)

    def test_config_test(self):
        diagnostic_util = mock.Mock()
        diagnostic_util.check_app_env.return_value = True
        diagnostic_util.check_rclone_dependency.return_value = True
        diagnostic_util.check_monitor_config.return_value = True
        commands, mock_prompt = self._make_commands([], diagnostic_util=diagnostic_util)
        commands.app.config_test()
        diagnostic_util.check_app_env.assert_called_once()
        diagnostic_util.print_overview.assert_called_once()
        self.assertIn("Exiting test mode now", mock_prompt.output_text)


if __name__ == "__main__":
    unittest.main()