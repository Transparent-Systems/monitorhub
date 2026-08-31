"""Mock-data driven unit tests for the monitor and profile commands.

These tests exercise the interactive command flows (``monitor_new``,
``profile_edit``, etc.) using a :class:`MockPromptService` that supplies
scripted input and captures output, rather than requiring a human at the
keyboard. They run against the dedicated unittest database in
``testdb/unittest`` (independent from ``testdb/dev``).
"""

import logging
import unittest

from scripts.command_processor import CommandProcessor
from tests.database_test_data import DatabaseTestData
from tests.mock_prompt_service import MockPromptService


class TestCommandProcessorCommands(unittest.TestCase):
    """Mock-driven unit tests for CommandProcessor monitor/profile commands."""

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
        self._processor: CommandProcessor | None = None

    def tearDown(self) -> None:
        if self._processor is not None:
            self._processor.sqlite_handler.close()
        self.database_test_data.remove_test_data()
        self.database_test_data.sqlite_handler.close()

    def _make_processor(self, inputs: list[str]) -> tuple[CommandProcessor, MockPromptService]:
        """Build a CommandProcessor wired to a scripted mock prompt."""
        mock = MockPromptService(inputs=inputs)
        processor = CommandProcessor(
            logger=self.logger,
            db_dir=self.db_dir,
            prompt=mock,
        )
        self._processor = processor
        return processor, mock

    def test_database_info(self):
        processor, mock = self._make_processor([])
        processor.database_info()
        self.assertIn("Location of SQLite database", mock.output_text)

    def test_monitor_show(self):
        processor, mock = self._make_processor([])
        processor.monitor_show()
        text = mock.output_text
        self.assertIn("Instant Monitor 1", text)
        self.assertIn("Backup Monitor 1", text)
        self.assertIn("Restore Monitor 1", text)

    def test_monitor_new(self):
        processor, mock = self._make_processor(
            ["my-monitor", "/tmp/source", "remote:dest", "1", "", ""]
        )
        processor.monitor_new()
        monitor = processor.sqlite_handler.get_monitor(monitor_name="my-monitor")
        self.assertTrue(monitor)
        self.assertEqual(monitor["monitor_type"], "instant")
        self.assertEqual(monitor["config"].get("exclude_patterns"), [])

    def test_monitor_edit(self):
        first_id = self.database_test_data.sqlite_handler.get_monitors()[0]["id"]
        processor, mock = self._make_processor(
            [str(first_id), "renamed-monitor", "", "", "", "", ""]
        )
        processor.monitor_edit()
        monitor = processor.sqlite_handler.get_monitor(monitor_id=first_id)
        self.assertEqual(monitor["name"], "renamed-monitor")

    def test_monitor_delete(self):
        first_id = self.database_test_data.sqlite_handler.get_monitors()[0]["id"]
        processor, mock = self._make_processor([str(first_id), str(first_id)])
        processor.monitor_delete()
        monitor = processor.sqlite_handler.get_monitor(monitor_id=first_id)
        self.assertFalse(monitor)

    def test_profile_show(self):
        processor, mock = self._make_processor([])
        processor.profile_show()
        text = mock.output_text
        self.assertIn("s3-test", text)
        self.assertIn("command-profile-1", text)

    def test_profile_new_command(self):
        processor, mock = self._make_processor(
            ["2", "my-cmd-profile", "echo hello", "", "", "", "n"]
        )
        processor.profile_new()
        profile = processor.sqlite_handler.get_profile(profile_name="my-cmd-profile")
        self.assertTrue(profile)
        self.assertEqual(profile["profile_type"], "event_command")
        self.assertEqual(profile["config"]["command"], "echo hello")

    def test_profile_edit_command(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-profile-1"
        )["id"]
        processor, mock = self._make_processor(
            [str(profile_id), "echo updated", "", "", "", ""]
        )
        processor.profile_edit()
        profile = processor.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["command"], "echo updated")

    def test_profile_delete(self):
        first_id = self.database_test_data.sqlite_handler.get_profiles()[0]["id"]
        processor, mock = self._make_processor([str(first_id), str(first_id)])
        processor.profile_delete()
        profile = processor.sqlite_handler.get_profile(profile_id=first_id)
        self.assertFalse(profile)

    def test_profile_test_command(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-profile-1"
        )["id"]
        processor, mock = self._make_processor([])
        processor.profile_test(profile_id=profile_id)
        text = mock.output_text
        self.assertIn("Testing command profile: command-profile-1", text)
        self.assertNotIn("Test failed", text)


if __name__ == "__main__":
    unittest.main()
