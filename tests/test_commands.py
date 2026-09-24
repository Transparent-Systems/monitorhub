"""Mock-data driven unit tests for the monitor and profile commands.

These tests exercise the interactive command flows (``monitor.new``,
``profile.edit``, etc.) using a :class:`MockPromptService` that supplies
scripted input and captures output, rather than requiring a human at the
keyboard. They run against the dedicated unittest database in
``testdb/unittest`` (independent from ``testdb/dev``).
"""

import datetime
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app.cli.commands import Commands, build_commands
from app.cli.monitor_commands import (
    STALE_HEARTBEAT_SECONDS,
    MonitorCommands,
    validate_monitor_type_number,
)
from app.cli.profile_commands import ProfileCommands
from app.monitor.action_handler import DEFAULT_COMMAND_MAX_WORKERS
from app.utils import reference_data
from app.utils.constants import DB_FILENAME, MONITOR_STATUS_RUNNING, TIMESTAMP_FORMAT
from app.utils.generic_util import parse_timestamp, utc_timestamp_now
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
        dependency_log_level: str | None = None,
        profile_importer: mock.Mock | None = None,
    ) -> tuple[Commands, MockPromptService]:
        """Build a wired ``Commands`` bundle around a scripted mock prompt."""
        mock_prompt = MockPromptService(inputs=inputs)
        commands = build_commands(
            logger=self.logger,
            db_dir=self.db_dir,
            prompt=mock_prompt,
            diagnostic_util=diagnostic_util,
            dependency_log_level=dependency_log_level,
            profile_importer=profile_importer,
        )
        self._commands = commands
        return commands, mock_prompt

    def test_database_info(self):
        commands, mock_prompt = self._make_commands([])
        commands.database.info()
        text = mock_prompt.output_text
        self.assertIn("SQLite database exists", text)
        self.assertIn(str(commands.sqlite_handler.db_path), text)

    def test_database_info_missing_database(self):
        """A missing database is reported by path, and is not created."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_prompt = MockPromptService(inputs=[])
            commands = build_commands(
                logger=self.logger,
                db_dir=tmp_dir,
                prompt=mock_prompt,
            )
            try:
                commands.database.info()
                self.assertFalse(commands.sqlite_handler.db_path.exists())
            finally:
                commands.sqlite_handler.close()

        text = mock_prompt.output_text
        self.assertIn("SQLite database does not exist", text)
        self.assertIn(os.path.join(tmp_dir, DB_FILENAME), text)

    def test_database_version(self):
        commands, mock_prompt = self._make_commands([])
        commands.database.version()
        text = mock_prompt.output_text
        self.assertIn("Version of SQLite database", text)
        self.assertIn("Supported database schema version", text)
        self.assertIn("Database schema is up to date.", text)

    def test_database_version_uninitialised(self):
        """The command reports an uninitialised database; the getter does not."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_prompt = MockPromptService(inputs=[])
            commands = build_commands(
                logger=self.logger,
                db_dir=tmp_dir,
                prompt=mock_prompt,
            )
            try:
                commands.database.version()
            finally:
                commands.sqlite_handler.close()

        self.assertIn("Database is not initialised", mock_prompt.output_text)

    def test_build_commands_no_log_side_effects(self):
        """The wiring factory must not mutate logger levels or propagate flags.

        Console-policy lives in ``setup_logging(quiet_dependencies=...)``, so
        ``build_commands`` must leave the passed-in logger and the third-party
        library loggers untouched - otherwise ``--log-level DEBUG`` would be
        floored back to WARNING (or dropped via ``propagate=False``).
        """
        dependency_loggers = ("boto3", "botocore", "s3transfer", "urllib3")
        original_levels = {
            name: logging.getLogger(name).level for name in dependency_loggers
        }
        probe = logging.getLogger("tests.build_commands_log_probe")
        probe.setLevel(logging.DEBUG)
        probe.propagate = True
        seen: dict = {}
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                mock_prompt = MockPromptService(inputs=[])
                commands = build_commands(
                    logger=probe,
                    db_dir=tmp_dir,
                    prompt=mock_prompt,
                )
                try:
                    # Snapshot the log state immediately after wiring, before
                    # any restoration below.
                    seen["probe_level"] = probe.level
                    seen["probe_propagate"] = probe.propagate
                    seen["dep_levels"] = {
                        name: logging.getLogger(name).level
                        for name in dependency_loggers
                    }
                finally:
                    commands.sqlite_handler.close()
        finally:
            self._commands = None
            probe.setLevel(logging.NOTSET)
            probe.propagate = True
            for name, level in original_levels.items():
                logging.getLogger(name).setLevel(level)

        self.assertEqual(
            seen.get("probe_level"), logging.DEBUG, "factory floored the log level"
        )
        self.assertTrue(seen.get("probe_propagate"), "factory disabled propagation")
        for name, level in original_levels.items():
            self.assertEqual(
                seen.get("dep_levels", {}).get(name),
                level,
                f"factory altered dependency logger {name}",
            )

    def test_database_sample_data_duplicate_monitor_name(self):
        """A duplicate sample monitor is reported as a friendly message."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_prompt = MockPromptService(inputs=[])
            commands = build_commands(
                logger=self.logger,
                db_dir=tmp_dir,
                prompt=mock_prompt,
            )
            try:
                commands.sqlite_handler.create_schema()
                commands.sqlite_handler.add_monitor(
                    name="Example monitor",
                    monitor_path="/tmp/example",
                    remote_path="/example",
                    monitor_type="instant",
                    config={},
                    status="stopped",
                )

                commands.database.sample_data()
            finally:
                commands.sqlite_handler.close()

        self.assertIn(
            "Monitor name: Example monitor already exists", mock_prompt.output_text
        )

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

    def test_monitor_show_by_id(self):
        commands, mock_prompt = self._make_commands([])
        monitors = commands.sqlite_handler.get_monitors()
        target, other = monitors[0], monitors[1]
        commands.monitor.show(monitor_id=target["id"])
        text = mock_prompt.output_text
        self.assertIn(target["name"], text)
        self.assertNotIn(other["name"], text)

    def test_monitor_show_by_name(self):
        commands, mock_prompt = self._make_commands([])
        monitors = commands.sqlite_handler.get_monitors()
        target, other = monitors[0], monitors[1]
        commands.monitor.show(monitor_name=target["name"])
        text = mock_prompt.output_text
        self.assertIn(target["name"], text)
        self.assertNotIn(other["name"], text)

    def test_monitor_show_both_id_and_name(self):
        commands, mock_prompt = self._make_commands([])
        monitors = commands.sqlite_handler.get_monitors()
        target = monitors[0]
        commands.monitor.show(monitor_id=target["id"], monitor_name=target["name"])
        self.assertIn("Cannot specify both --monitor-id and --monitor-name.", mock_prompt.output_text)

    def test_monitor_new(self):
        commands, _ = self._make_commands(
            ["my-monitor", "/tmp/source", "remote:dest", "1", "", ""]
        )
        commands.monitor.new()
        monitor = commands.sqlite_handler.get_monitor(monitor_name="my-monitor")
        self.assertTrue(monitor)
        self.assertEqual(monitor["monitor_type"], "instant")
        self.assertEqual(monitor["config"].get("exclude_patterns"), [])

    def test_monitor_new_adds_selected_profile(self):
        profiles = self.database_test_data.sqlite_handler.get_profiles()
        first_profile_id = profiles[0]["id"]
        second_profile_id = profiles[1]["id"]
        # Inputs: name, paths, type, no exclude patterns, two profile ids, then
        # Enter to stop. Selecting two profiles back-to-back proves there is no
        # per-profile y/N confirmation step in between.
        commands, _ = self._make_commands(
            [
                "my-monitor",
                "/tmp/source",
                "remote:dest",
                "1",
                "",
                str(first_profile_id),
                str(second_profile_id),
                "",
            ]
        )
        commands.monitor.new()
        monitor = commands.sqlite_handler.get_monitor(monitor_name="my-monitor")
        self.assertTrue(monitor)
        linked = commands.sqlite_handler.get_profiles_for_monitor(monitor_id=monitor["id"])
        self.assertEqual(
            {profile["id"] for profile in linked},
            {first_profile_id, second_profile_id},
        )

    def test_monitor_edit(self):
        first_id = self.database_test_data.sqlite_handler.get_monitors()[0]["id"]
        commands, _ = self._make_commands(
            [str(first_id), "renamed-monitor", "", "", "", "", ""]
        )
        commands.monitor.edit()
        monitor = commands.sqlite_handler.get_monitor(monitor_id=first_id)
        self.assertEqual(monitor["name"], "renamed-monitor")

    def test_monitor_edit_by_id(self):
        monitors = self.database_test_data.sqlite_handler.get_monitors()
        target = monitors[0]
        commands, _ = self._make_commands(["renamed-by-id", "", "", "", "", ""])
        commands.monitor.edit(monitor_id=target["id"])
        monitor = commands.sqlite_handler.get_monitor(monitor_id=target["id"])
        self.assertEqual(monitor["name"], "renamed-by-id")

    def test_monitor_edit_by_name(self):
        monitors = self.database_test_data.sqlite_handler.get_monitors()
        target = monitors[0]
        commands, _ = self._make_commands(["renamed-by-name", "", "", "", "", ""])
        commands.monitor.edit(monitor_name=target["name"])
        monitor = commands.sqlite_handler.get_monitor(monitor_id=target["id"])
        self.assertEqual(monitor["name"], "renamed-by-name")

    def test_monitor_edit_preserves_stored_pid(self):
        """Editing a running monitor must not clear its stored pid.

        Regression: ``update_monitor`` defaults ``pid`` to 0, and edit did not
        pass the current pid, so editing a running monitor left status='running'
        with pid=0. ``monitor start`` then treats it as stale and launches a
        duplicate process.
        """
        monitor = self.database_test_data.sqlite_handler.get_monitor(
            monitor_name="Backup Monitor 1"
        )
        self.assertIsNotNone(monitor)
        commands, _ = self._make_commands([])
        commands.sqlite_handler.update_monitor_status(
            monitor_id=monitor["id"], status=MONITOR_STATUS_RUNNING
        )
        commands.sqlite_handler.update_monitor_pid(
            monitor_id=monitor["id"], pid=4242
        )

        # Press Enter through every edit prompt (keep current values). A backup
        # monitor prompts for name, paths, type, interval, excludes, and the
        # linked-profile delete loop.
        commands, _ = self._make_commands(["", "", "", "", "", "", ""])
        commands.monitor.edit(monitor_id=monitor["id"])

        after = commands.sqlite_handler.get_monitor(monitor_id=monitor["id"])
        self.assertEqual(after["pid"], 4242, "edit cleared the stored pid")
        self.assertEqual(after["status"], MONITOR_STATUS_RUNNING)

    def test_monitor_edit_both_id_and_name(self):
        monitors = self.database_test_data.sqlite_handler.get_monitors()
        target = monitors[0]
        commands, mock_prompt = self._make_commands([])
        commands.monitor.edit(monitor_id=target["id"], monitor_name=target["name"])
        self.assertIn("Cannot specify both --monitor-id and --monitor-name.", mock_prompt.output_text)

    def test_monitor_edit_invalid_interval(self):
        # Backup Monitor 1 has an interval config
        monitor = self.database_test_data.sqlite_handler.get_monitor(monitor_name="Backup Monitor 1")
        self.assertIsNotNone(monitor)
        # Inputs: keep name, keep monitor path, keep remote path, keep monitor type,
        # interval: '-1s' (invalid), then '15m' (valid), then keep exclude patterns, no profiles to delete, no profiles to add
        commands, mock_prompt = self._make_commands(
            ["", "", "", "", "-1s", "15m", "", "", ""]
        )
        commands.monitor.edit(monitor_id=monitor["id"])
        self.assertIn("Invalid interval: '-1s'", mock_prompt.output_text)
        self.assertIn("Current backup interval: 1m", mock_prompt.output_text)
        updated_monitor = commands.sqlite_handler.get_monitor(monitor_id=monitor["id"])
        self.assertEqual(updated_monitor["config"]["interval"], "15m")

    def test_monitor_edit_restore_interval_prompt(self):
        monitor = self.database_test_data.sqlite_handler.get_monitor(monitor_name="Restore Monitor 1")
        self.assertIsNotNone(monitor)
        commands, mock_prompt = self._make_commands(
            ["", "", "", "", "20m", "", "", ""]
        )
        commands.monitor.edit(monitor_id=monitor["id"])
        self.assertIn("Current restore interval: 1m", mock_prompt.output_text)
        updated_monitor = commands.sqlite_handler.get_monitor(monitor_id=monitor["id"])
        self.assertEqual(updated_monitor["config"]["interval"], "20m")

    def test_monitor_edit_rejects_non_numeric_monitor_type(self):
        monitor = self.database_test_data.sqlite_handler.get_monitor(
            monitor_name="Backup Monitor 1"
        )
        self.assertIsNotNone(monitor)
        # Inputs: keep name/path/remote, type 'abc' (invalid, retried), type '1'
        # (instant), then the remaining keep/stop prompts.
        commands, mock_prompt = self._make_commands(
            ["", "", "", "abc", "1", "", "", "", ""]
        )
        commands.monitor.edit(monitor_id=monitor["id"])
        self.assertIn(
            "Invalid monitor type number: abc. Please try again.",
            mock_prompt.output_text,
        )
        updated_monitor = commands.sqlite_handler.get_monitor(monitor_id=monitor["id"])
        self.assertEqual(updated_monitor["monitor_type"], "instant")

    def test_monitor_edit_rejects_out_of_range_monitor_type(self):
        monitor = self.database_test_data.sqlite_handler.get_monitor(
            monitor_name="Backup Monitor 1"
        )
        self.assertIsNotNone(monitor)
        # '99' is above the range and '0' would index from the end of the list;
        # both must be rejected before a valid '1' (instant) is accepted.
        commands, mock_prompt = self._make_commands(
            ["", "", "", "99", "0", "1", "", "", "", ""]
        )
        commands.monitor.edit(monitor_id=monitor["id"])
        self.assertIn(
            "Invalid monitor type number: 99. Please try again.",
            mock_prompt.output_text,
        )
        self.assertIn(
            "Invalid monitor type number: 0. Please try again.",
            mock_prompt.output_text,
        )
        updated_monitor = commands.sqlite_handler.get_monitor(monitor_id=monitor["id"])
        self.assertEqual(updated_monitor["monitor_type"], "instant")

    def test_validate_monitor_type_number(self):
        monitor_types = [("instant", "i"), ("backup", "b"), ("restore", "r")]
        self.assertIsNone(validate_monitor_type_number("1", monitor_types))
        self.assertIsNone(validate_monitor_type_number("3", monitor_types))
        for invalid in ("0", "-1", "4", "abc", "1.0", ""):
            self.assertIsNotNone(validate_monitor_type_number(invalid, monitor_types))

    def test_monitor_edit_adds_profile_and_stops_with_enter(self):
        profiles = self.database_test_data.sqlite_handler.get_profiles()
        first_profile_id = profiles[0]["id"]
        second_profile_id = profiles[1]["id"]
        monitor_id = self.database_test_data.sqlite_handler.add_monitor(
            name="edit-profile-monitor",
            monitor_path="/tmp/edit-source",
            remote_path="remote:edit-dest",
            monitor_type="instant",
            config={"exclude_patterns": []},
            status="stopped",
        )
        # Inputs: keep name/path/remote/type, keep exclude patterns, two profile
        # ids, then Enter to stop. Selecting two profiles back-to-back proves
        # there is no per-profile y/N confirmation step in between.
        commands, _ = self._make_commands(
            [
                "",
                "",
                "",
                "",
                "",
                str(first_profile_id),
                str(second_profile_id),
                "",
            ]
        )
        commands.monitor.edit(monitor_id=monitor_id)
        linked = commands.sqlite_handler.get_profiles_for_monitor(monitor_id=monitor_id)
        self.assertEqual(
            {profile["id"] for profile in linked},
            {first_profile_id, second_profile_id},
        )

    def test_monitor_delete(self):
        first_id = self.database_test_data.sqlite_handler.get_monitors()[0]["id"]
        commands, _ = self._make_commands([str(first_id), str(first_id)])
        commands.monitor.delete()
        monitor = commands.sqlite_handler.get_monitor(monitor_id=first_id)
        self.assertFalse(monitor)

    def test_monitor_delete_by_id(self):
        commands, _ = self._make_commands([])
        monitors = commands.sqlite_handler.get_monitors()
        target = monitors[0]
        commands.monitor.delete(monitor_id=target["id"])
        self.assertFalse(commands.sqlite_handler.get_monitor(monitor_id=target["id"]))

    def test_monitor_delete_by_name(self):
        commands, _ = self._make_commands([])
        monitors = commands.sqlite_handler.get_monitors()
        target = monitors[0]
        commands.monitor.delete(monitor_name=target["name"])
        self.assertFalse(commands.sqlite_handler.get_monitor(monitor_name=target["name"]))

    def test_monitor_delete_both_id_and_name(self):
        commands, mock_prompt = self._make_commands([])
        monitors = commands.sqlite_handler.get_monitors()
        target = monitors[0]
        commands.monitor.delete(monitor_id=target["id"], monitor_name=target["name"])
        self.assertIn("Cannot specify both --monitor-id and --monitor-name.", mock_prompt.output_text)

    def test_profile_show(self):
        commands, mock_prompt = self._make_commands([])
        commands.profile.show()
        text = mock_prompt.output_text
        self.assertIn("Profile id:", text)
        self.assertIn("s3-test", text)
        self.assertIn("command-test", text)

    def test_profile_show_by_id(self):
        commands, mock_prompt = self._make_commands([])
        profiles = commands.sqlite_handler.get_profiles()
        target, other = profiles[0], profiles[1]
        commands.profile.show(profile_id=target["id"])
        text = mock_prompt.output_text
        self.assertIn(target["name"], text)
        self.assertNotIn(other["name"], text)

    def test_profile_show_by_name(self):
        commands, mock_prompt = self._make_commands([])
        profiles = commands.sqlite_handler.get_profiles()
        target, other = profiles[0], profiles[1]
        commands.profile.show(profile_name=target["name"])
        text = mock_prompt.output_text
        self.assertIn(target["name"], text)
        self.assertNotIn(other["name"], text)

    def test_profile_show_both_id_and_name(self):
        commands, mock_prompt = self._make_commands([])
        profiles = commands.sqlite_handler.get_profiles()
        target = profiles[0]
        commands.profile.show(profile_id=target["id"], profile_name=target["name"])
        self.assertIn("Cannot specify both --profile-id and --profile-name.", mock_prompt.output_text)

    def _set_profile_config_value(self, profile_name: str, key: str, value) -> int:
        """Set one config value on a profile, returning its id."""
        profile = self.database_test_data.sqlite_handler.get_profile(
            profile_name=profile_name
        )
        config = dict(profile["config"])
        config[key] = value
        self.database_test_data.sqlite_handler.update_profile(
            profile_id=profile["id"],
            name=profile["name"],
            profile_type=profile["profile_type"],
            config=config,
        )
        return profile["id"]

    def test_profile_show_masks_secret_values(self):
        self._set_profile_config_value("ftp-test", "pass", "super-secret-pass")
        commands, mock_prompt = self._make_commands([])
        commands.profile.show(profile_name="ftp-test")
        text = mock_prompt.output_text
        self.assertIn("pass: ********", text)
        self.assertNotIn("super-secret-pass", text)
        # Non-secret properties stay visible.
        self.assertIn("host:", text)

    def test_profile_edit_s3_masks_current_secret(self):
        profile = self.database_test_data.sqlite_handler.get_profile(
            profile_name="s3-test"
        )
        config = dict(profile["config"])
        config["access_key_id"] = "AKIA-VISIBLE-ID"
        config["access_key_secret"] = "super-secret-key"
        self.database_test_data.sqlite_handler.update_profile(
            profile_id=profile["id"],
            name=profile["name"],
            profile_type=profile["profile_type"],
            config=config,
        )
        commands, mock_prompt = self._make_commands(
            [str(profile["id"]), "", "", "", "n"]
        )
        commands.profile.edit()
        text = mock_prompt.output_text
        # The access key id is an identifier and stays visible; the secret is masked.
        self.assertIn("AKIA-VISIBLE-ID", text)
        self.assertIn("S3 access key secret: ********", text)
        self.assertNotIn("super-secret-key", text)

    def test_profile_edit_rclone_masks_secret_properties(self):
        profile_id = self._set_profile_config_value(
            "ftp-test", "pass", "super-secret-pass"
        )
        commands, mock_prompt = self._make_commands(
            [str(profile_id), "", "", "", ""]
        )
        commands.profile.edit()
        text = mock_prompt.output_text
        self.assertIn("pass: ********", text)
        self.assertNotIn("super-secret-pass", text)
        # Masking is display-only: the stored secret is untouched.
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["pass"], "super-secret-pass")

    def test_profile_new_command(self):
        commands, _ = self._make_commands(
            ["2", "my-cmd-profile", "echo hello", "", "", "", "", "n"]
        )
        commands.profile.new()
        profile = commands.sqlite_handler.get_profile(profile_name="my-cmd-profile")
        self.assertTrue(profile)
        self.assertEqual(profile["profile_type"], "event_command")
        self.assertEqual(profile["config"]["command"], "echo hello")
        self.assertEqual(
            profile["config"]["command_max_workers"], DEFAULT_COMMAND_MAX_WORKERS
        )

    def test_profile_new_command_custom_max_workers(self):
        commands, _ = self._make_commands(
            ["2", "my-cmd-profile", "echo hello", "", "", "", "250", "n"]
        )
        commands.profile.new()
        profile = commands.sqlite_handler.get_profile(profile_name="my-cmd-profile")
        self.assertTrue(profile)
        self.assertEqual(profile["config"]["command_max_workers"], 250)

    def test_profile_new_command_invalid_max_workers_reprompts(self):
        commands, mock_prompt = self._make_commands(
            ["2", "my-cmd-profile", "echo hello", "", "", "", "abc", "0", "5", "n"]
        )
        commands.profile.new()
        profile = commands.sqlite_handler.get_profile(profile_name="my-cmd-profile")
        self.assertTrue(profile)
        self.assertEqual(profile["config"]["command_max_workers"], 5)
        self.assertIn("Invalid number of workers: abc", mock_prompt.output_text)
        self.assertIn("Number of workers must be between 1 and 1000", mock_prompt.output_text)

    def test_profile_new_remote_stores_remote_handler(self):
        # category 1 = remote, provider 3 = IDrive (endpoint prompt path)
        commands, _ = self._make_commands(
            [
                "1",
                "my-s3-profile",
                "3",
                "FAKE_ACCESS_KEY_ID",
                "FAKE_ACCESS_KEY_SECRET",
                "https://example.invalid",
            ]
        )
        commands.profile.new()
        profile = commands.sqlite_handler.get_profile(profile_name="my-s3-profile")
        self.assertTrue(profile)
        self.assertEqual(profile["profile_type"], "s3")
        self.assertEqual(
            profile["config"][reference_data.CONFIG_REMOTE_HANDLER], "s3"
        )

    def test_profile_new_aws_provider_stores_region(self):
        # provider 1 = AWS: the wizard must ask for a region, not an endpoint
        # (regression from renaming the provider to "AWS").
        commands, _ = self._make_commands(
            [
                "1",
                "my-aws-profile",
                "1",
                "FAKE_ACCESS_KEY_ID",
                "FAKE_ACCESS_KEY_SECRET",
                "eu-west-1",
            ]
        )
        commands.profile.new()
        profile = commands.sqlite_handler.get_profile(profile_name="my-aws-profile")
        self.assertTrue(profile)
        self.assertEqual(profile["config"]["provider_name"], "AWS")
        self.assertEqual(profile["config"]["region"], "eu-west-1")
        self.assertEqual(profile["config"]["env_auth"], "false")
        self.assertNotIn("endpoint", profile["config"])

    def test_profile_edit_remote_switches_to_rclone(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="s3-test"
        )["id"]
        # Keep access key, secret and endpoint (empty entries), then answer yes
        # to the rclone routing question.
        commands, _ = self._make_commands([str(profile_id), "", "", "", "y"])
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(
            profile["config"][reference_data.CONFIG_REMOTE_HANDLER],
            reference_data.RCLONE_REMOTE_HANDLER,
        )

    def test_profile_edit_remote_keeps_native_handler(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="s3-test"
        )["id"]
        commands, _ = self._make_commands([str(profile_id), "", "", "", "n"])
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"][reference_data.CONFIG_REMOTE_HANDLER], "s3")

    def _route_s3_profile_through_rclone(self, profile_name: str) -> int:
        """Seed an s3 profile routed through rclone, returning its id."""
        profile = self.database_test_data.sqlite_handler.get_profile(
            profile_name=profile_name
        )
        config = dict(profile["config"])
        config[reference_data.CONFIG_REMOTE_HANDLER] = (
            reference_data.RCLONE_REMOTE_HANDLER
        )
        self.database_test_data.sqlite_handler.update_profile(
            profile_id=profile["id"],
            name=profile["name"],
            profile_type=profile["profile_type"],
            config=config,
        )
        return profile["id"]

    def test_profile_edit_rclone_profile_updates_property(self):
        # ftp-test is an rclone-managed remote: every backend property is
        # offered and Enter keeps the others.
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="ftp-test"
        )["id"]
        commands, _ = self._make_commands(
            [str(profile_id), "192.168.1.99", "", "", ""]
        )
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["host"], "192.168.1.99")
        self.assertEqual(profile["config"]["user"], "ftpuser")
        self.assertEqual(
            profile["config"][reference_data.CONFIG_REMOTE_HANDLER],
            reference_data.RCLONE_REMOTE_HANDLER,
        )

    def test_profile_edit_rclone_profile_keeps_values(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="ftp-test"
        )["id"]
        commands, _ = self._make_commands([str(profile_id), "", "", "", ""])
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["host"], "192.168.1.51")
        self.assertEqual(profile["config"]["user"], "ftpuser")

    def test_profile_edit_rclone_profile_updates_rclone_options(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="ftp-test"
        )["id"]
        commands, _ = self._make_commands(
            [str(profile_id), "", "", "", "transfers=8, s3_chunk_size=16M"]
        )
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(
            profile["config"]["rclone_options"],
            {"transfers": "8", "s3_chunk_size": "16M"},
        )

    def test_profile_edit_rclone_profile_rejects_invalid_options(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="ftp-test"
        )["id"]
        # "transfers" (no value) is rejected and re-asked.
        commands, mock_prompt = self._make_commands(
            [str(profile_id), "", "", "", "transfers", "transfers=8"]
        )
        commands.profile.edit()
        self.assertIn("Invalid rclone option", mock_prompt.output_text)
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["rclone_options"], {"transfers": "8"})

    def test_profile_edit_s3_rclone_profile_updates_property(self):
        # An s3 profile routed through rclone uses the property editor and can
        # switch back to the built-in handler.
        profile_id = self._route_s3_profile_through_rclone("s3-test")
        # Properties: provider_name, access_key_id, access_key_secret, endpoint;
        # then rclone options; then the handler question (answer "n").
        commands, _ = self._make_commands(
            [
                str(profile_id),
                "",
                "",
                "",
                "https://example.invalid",
                "",
                "n",
            ]
        )
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["endpoint"], "https://example.invalid")
        self.assertEqual(profile["config"]["provider_name"], "IDrive")
        self.assertEqual(profile["config"][reference_data.CONFIG_REMOTE_HANDLER], "s3")

    def test_profile_edit_s3_rclone_profile_keeps_rclone_route(self):
        profile_id = self._route_s3_profile_through_rclone("s3-test")
        commands, _ = self._make_commands(
            [str(profile_id), "", "", "", "", "", ""]
        )
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(
            profile["config"][reference_data.CONFIG_REMOTE_HANDLER],
            reference_data.RCLONE_REMOTE_HANDLER,
        )

    def test_profile_test_s3_profile_uses_native_handler(self):
        commands, _ = self._make_commands([])
        with (
            mock.patch("app.monitor.s3_factory.S3Factory.test_connection") as native_test,
            mock.patch(
                "app.cli.profile_commands.RcloneHandler.test_connection"
            ) as rclone_test,
        ):
            result = commands.profile.test(profile_name="s3-test")
        self.assertTrue(result)
        native_test.assert_called_once()
        rclone_test.assert_not_called()

    def test_profile_test_rclone_profile_uses_rclone_handler(self):
        commands, _ = self._make_commands([])
        with (
            mock.patch("app.monitor.s3_factory.S3Factory.test_connection") as native_test,
            mock.patch(
                "app.cli.profile_commands.RcloneHandler.test_connection"
            ) as rclone_test,
        ):
            result = commands.profile.test(profile_name="ftp-test")
        self.assertTrue(result)
        rclone_test.assert_called_once()
        native_test.assert_not_called()
        # The full profile is handed over, so rclone is configured via env.
        passed_profile = rclone_test.call_args.kwargs["profile"]
        self.assertEqual(passed_profile["name"], "ftp-test")
        self.assertEqual(
            passed_profile["config"][reference_data.CONFIG_REMOTE_HANDLER],
            reference_data.RCLONE_REMOTE_HANDLER,
        )

    def test_profile_test_s3_profile_routed_to_rclone(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="s3-test"
        )["id"]
        commands, _ = self._make_commands([])
        stored = commands.sqlite_handler.get_profile(profile_id=profile_id)
        stored["config"][reference_data.CONFIG_REMOTE_HANDLER] = (
            reference_data.RCLONE_REMOTE_HANDLER
        )
        commands.sqlite_handler.update_profile(
            profile_id=profile_id,
            name=stored["name"],
            profile_type=stored["profile_type"],
            config=stored["config"],
        )
        with (
            mock.patch("app.monitor.s3_factory.S3Factory.test_connection") as native_test,
            mock.patch(
                "app.cli.profile_commands.RcloneHandler.test_connection"
            ) as rclone_test,
        ):
            result = commands.profile.test(profile_name="s3-test")
        self.assertTrue(result)
        rclone_test.assert_called_once()
        native_test.assert_not_called()

    def test_profile_edit_command(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-test"
        )["id"]
        commands, _ = self._make_commands(
            [str(profile_id), "echo updated", "", "", "", "", ""]
        )
        commands.profile.edit()
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["command"], "echo updated")

    def test_profile_edit_command_by_id(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-test"
        )["id"]
        commands, _ = self._make_commands(["echo updated", "", "", "", "", ""])
        commands.profile.edit(profile_id=profile_id)
        profile = commands.sqlite_handler.get_profile(profile_id=profile_id)
        self.assertEqual(profile["config"]["command"], "echo updated")

    def test_profile_edit_command_by_name(self):
        commands, _ = self._make_commands(["echo updated", "", "", "", "", ""])
        commands.profile.edit(profile_name="command-test")
        profile = commands.sqlite_handler.get_profile(profile_name="command-test")
        self.assertEqual(profile["config"]["command"], "echo updated")

    def test_profile_edit_both_id_and_name(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-test"
        )["id"]
        commands, mock_prompt = self._make_commands([])
        commands.profile.edit(profile_id=profile_id, profile_name="command-test")
        self.assertIn("Cannot specify both --profile-id and --profile-name.", mock_prompt.output_text)

    def test_profile_delete(self):
        first_id = self.database_test_data.sqlite_handler.get_profiles()[0]["id"]
        commands, _ = self._make_commands([str(first_id), str(first_id)])
        commands.profile.delete()
        profile = commands.sqlite_handler.get_profile(profile_id=first_id)
        self.assertFalse(profile)

    def test_profile_delete_by_id(self):
        commands, _ = self._make_commands([])
        profiles = commands.sqlite_handler.get_profiles()
        target = profiles[0]
        commands.profile.delete(profile_id=target["id"])
        self.assertFalse(commands.sqlite_handler.get_profile(profile_id=target["id"]))

    def test_profile_delete_by_name(self):
        commands, _ = self._make_commands([])
        profiles = commands.sqlite_handler.get_profiles()
        target = profiles[0]
        commands.profile.delete(profile_name=target["name"])
        self.assertFalse(commands.sqlite_handler.get_profile(profile_name=target["name"]))

    def test_profile_delete_both_id_and_name(self):
        commands, mock_prompt = self._make_commands([])
        profiles = commands.sqlite_handler.get_profiles()
        target = profiles[0]
        commands.profile.delete(profile_id=target["id"], profile_name=target["name"])
        self.assertIn("Cannot specify both --profile-id and --profile-name.", mock_prompt.output_text)

    def test_profile_test_command(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-test"
        )["id"]
        commands, mock_prompt = self._make_commands([])
        commands.profile.test(profile_id=profile_id)
        text = mock_prompt.output_text
        self.assertIn("Testing command profile: command-test", text)
        self.assertNotIn("Test failed", text)

    def test_profile_test_by_name(self):
        commands, mock_prompt = self._make_commands([])
        result = commands.profile.test(profile_name="command-test")
        self.assertTrue(result)
        text = mock_prompt.output_text
        self.assertIn("Testing command profile: command-test", text)

    def test_profile_test_both_id_and_name(self):
        profile_id = self.database_test_data.sqlite_handler.get_profile(
            profile_name="command-test"
        )["id"]
        commands, mock_prompt = self._make_commands([])
        result = commands.profile.test(profile_id=profile_id, profile_name="command-test")
        self.assertFalse(result)
        self.assertIn("Cannot specify both --profile-id and --profile-name.", mock_prompt.output_text)

    def test_profile_test_not_found(self):
        commands, mock_prompt = self._make_commands([])
        result = commands.profile.test(profile_id=999999)
        self.assertFalse(result)
        self.assertIn("Profile with id=999999 not found.", mock_prompt.output_text)

        commands, mock_prompt2 = self._make_commands([])
        result = commands.profile.test(profile_name="non-existent-profile")
        self.assertFalse(result)
        self.assertIn("Profile with name='non-existent-profile' not found.", mock_prompt2.output_text)

    def test_profile_import_delegates_to_profile_importer(self):
        """``profile import`` must delegate to the shared ProfileImporter."""
        profile_importer = mock.Mock()
        commands, _ = self._make_commands([], profile_importer=profile_importer)
        commands.profile.import_profiles()
        profile_importer.import_profiles.assert_called_once_with()

    def test_version(self):
        commands, mock_prompt = self._make_commands([])
        commands.app.version()
        self.assertIn("MonitorHub version:", mock_prompt.output_text)

    def test_read_only_commands_do_not_create_the_database(self):
        """Regression: wiring ``version``/``database info`` must not create the DB.

        ``build_commands`` used to construct an eager ``SQLiteHandler``, which
        opened (and therefore created) ``monitorhub.db`` before ``database
        init`` had ever run. These commands only read the version string or the
        database path, so the file must stay absent.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = Path(tmp_dir) / DB_FILENAME
            for action in ("version", "database_info", "database_version"):
                mock_prompt = MockPromptService(inputs=[])
                commands = build_commands(
                    logger=self.logger,
                    db_dir=tmp_dir,
                    prompt=mock_prompt,
                )
                try:
                    if action == "version":
                        commands.app.version()
                    elif action == "database_info":
                        commands.database.info()
                    else:
                        commands.database.version()
                    self.assertFalse(
                        db_file.exists(),
                        f"{action} created the database file",
                    )
                finally:
                    commands.sqlite_handler.close()

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

    def test_config_test_rclone_dependency_checked_once(self):
        """Regression A4: check_rclone_dependency must not be invoked twice."""
        diagnostic_util = mock.Mock()
        diagnostic_util.check_app_env.return_value = True
        diagnostic_util.check_rclone_dependency.return_value = True
        diagnostic_util.check_monitor_config.return_value = True
        commands, _ = self._make_commands([], diagnostic_util=diagnostic_util)
        commands.app.config_test()
        diagnostic_util.check_rclone_dependency.assert_called_once()

    # ------------------------------------------------------------------
    # Monitor start/stop liveness guards (duplicate-process regression)
    # ------------------------------------------------------------------

    def test_monitor_start_refuses_while_still_shutting_down(self):
        """A monitor in the intermediate 'stop' state with a live PID must not restart."""
        commands, mock_prompt = self._make_commands([])
        monitor = commands.sqlite_handler.get_monitors()[0]
        commands.sqlite_handler.update_monitor_status(monitor_id=monitor["id"], status="stop")
        commands.sqlite_handler.update_monitor_pid(monitor_id=monitor["id"], pid=os.getpid())
        with mock.patch.object(commands.monitor.processes, "launch") as launch:
            commands.monitor.start(monitor_id=monitor["id"])
        launch.assert_not_called()
        self.assertIn("still shutting down", mock_prompt.output_text)

    def test_monitor_start_refuses_when_already_running(self):
        commands, mock_prompt = self._make_commands([])
        monitor = commands.sqlite_handler.get_monitors()[0]
        commands.sqlite_handler.update_monitor_status(monitor_id=monitor["id"], status="running")
        commands.sqlite_handler.update_monitor_pid(monitor_id=monitor["id"], pid=os.getpid())
        with mock.patch.object(commands.monitor.processes, "launch") as launch:
            commands.monitor.start(monitor_id=monitor["id"])
        launch.assert_not_called()
        self.assertIn("already running", mock_prompt.output_text)

    def test_monitor_start_clears_stale_running_status(self):
        commands, mock_prompt = self._make_commands([])
        monitor = commands.sqlite_handler.get_monitors()[0]
        # 'running' with no live process (pid 0) is a stale entry.
        commands.sqlite_handler.update_monitor_status(monitor_id=monitor["id"], status="running")
        commands.sqlite_handler.update_monitor_pid(monitor_id=monitor["id"], pid=0)
        with mock.patch.object(
            commands.monitor.processes, "launch", return_value=True
        ) as launch:
            commands.monitor.start(monitor_id=monitor["id"])
        launch.assert_called_once()
        self.assertIn("stale 'running'", mock_prompt.output_text)

    def test_monitor_stop_escalates_when_process_survives(self):
        commands, mock_prompt = self._make_commands([])
        monitor = commands.sqlite_handler.get_monitors()[0]
        commands.sqlite_handler.update_monitor_status(monitor_id=monitor["id"], status="running")
        commands.sqlite_handler.update_monitor_pid(monitor_id=monitor["id"], pid=4242)
        with (
            mock.patch.object(commands.monitor.processes, "wait_for_exit", return_value=False),
            mock.patch.object(commands.monitor.processes, "escalate_stop") as escalate,
        ):
            commands.monitor.stop(monitor_id=monitor["id"])
        escalate.assert_called_once()
        self.assertIn("escalating", mock_prompt.output_text)
        after = commands.sqlite_handler.get_monitor(monitor_id=monitor["id"])
        self.assertEqual(after["status"], "stopped")
        self.assertEqual(after["pid"], 0)

    def test_monitor_stop_no_escalation_when_process_exits(self):
        commands, mock_prompt = self._make_commands([])
        monitor = commands.sqlite_handler.get_monitors()[0]
        commands.sqlite_handler.update_monitor_status(monitor_id=monitor["id"], status="running")
        commands.sqlite_handler.update_monitor_pid(monitor_id=monitor["id"], pid=4242)
        with (
            mock.patch.object(commands.monitor.processes, "wait_for_exit", return_value=True),
            mock.patch.object(commands.monitor.processes, "escalate_stop") as escalate,
        ):
            commands.monitor.stop(monitor_id=monitor["id"])
        escalate.assert_not_called()
        self.assertIn("stopped gracefully", mock_prompt.output_text)

    def test_escalate_stop_sends_sigterm_then_force_kills(self):
        commands, _ = self._make_commands([])
        with (
            mock.patch("app.cli.monitor_process_manager.os.kill") as kill_mock,
            mock.patch.object(commands.monitor.processes, "wait_for_exit", return_value=False),
            mock.patch.object(commands.monitor.processes, "force_kill") as force_mock,
        ):
            commands.monitor.processes.escalate_stop(4242, "test")
        kill_mock.assert_called_once_with(4242, signal.SIGTERM)
        force_mock.assert_called_once_with(4242, "test")

    # ------------------------------------------------------------------
    # Zombie-aware graceful stop / child reaping (interactive-test regression)
    # ------------------------------------------------------------------

    def test_wait_for_exit_uses_tracked_popen_instead_of_pid_check(self):
        """A tracked, exited child is recognised as stopped even if its PID
        still exists (unreaped zombie), proving ``poll`` is preferred."""
        commands, _ = self._make_commands([])
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()  # reaped so the handle reports a return code
        commands.monitor.processes.tracked_processes[7] = child
        with mock.patch(
            "app.cli.monitor_process_manager.is_process_alive", return_value=True
        ) as pid_check:
            self.assertTrue(
                commands.monitor.processes.wait_for_exit(child.pid, timeout=1.0, monitor_id=7)
            )
        pid_check.assert_not_called()

    def test_wait_for_exit_falls_back_to_pid_check_when_untracked(self):
        """Without a tracked handle the generic PID check is still used."""
        commands, _ = self._make_commands([])
        with mock.patch(
            "app.cli.monitor_process_manager.is_process_alive", return_value=False
        ) as pid_check:
            self.assertTrue(
                commands.monitor.processes.wait_for_exit(4242, timeout=1.0, monitor_id=7)
            )
        pid_check.assert_called()

    def test_launch_monitor_process_tracks_child(self):
        """The Popen handle is retained so the child can be reaped later."""
        commands, _ = self._make_commands([])
        fake_process = mock.Mock()
        with mock.patch(
            "app.cli.monitor_process_manager.subprocess.Popen", return_value=fake_process
        ) as popen:
            self.assertTrue(
                commands.monitor.processes.launch({"id": 99, "name": "tracked"})
            )
        popen.assert_called_once()
        self.assertIs(commands.monitor.processes.tracked_processes[99], fake_process)

    def test_launch_forwards_dependency_log_level_to_child(self):
        """--dependency-log-level is forwarded to the monitor child process."""
        commands, _ = self._make_commands([], dependency_log_level="DEBUG")
        fake_process = mock.Mock()
        with mock.patch(
            "app.cli.monitor_process_manager.subprocess.Popen", return_value=fake_process
        ) as popen:
            self.assertTrue(
                commands.monitor.processes.launch({"id": 99, "name": "tracked"})
            )
        cmd = popen.call_args[0][0]
        self.assertIn("--dependency-log-level", cmd)
        self.assertEqual(cmd[cmd.index("--dependency-log-level") + 1], "DEBUG")

    def test_launch_omits_dependency_log_level_when_unset(self):
        """Without --dependency-log-level the child command stays unchanged."""
        commands, _ = self._make_commands([])
        fake_process = mock.Mock()
        with mock.patch(
            "app.cli.monitor_process_manager.subprocess.Popen", return_value=fake_process
        ) as popen:
            self.assertTrue(
                commands.monitor.processes.launch({"id": 99, "name": "tracked"})
            )
        self.assertNotIn("--dependency-log-level", popen.call_args[0][0])

    def test_launch_runs_child_as_module_from_project_root(self):
        """The child runs as `python -m app.monitor.run_monitor` from the root.

        run_monitor.py used to carry a ``sys.path`` preamble so a by-path
        launch could resolve `app.*`; launch() instead runs it as a module
        with the project root as its working directory, so Python provides
        sys.path itself — no preamble, no PYTHONPATH.
        """
        commands, _ = self._make_commands([])
        repo_root = Path(__file__).resolve().parents[1]
        fake_process = mock.Mock()
        with mock.patch(
            "app.cli.monitor_process_manager.subprocess.Popen", return_value=fake_process
        ) as popen:
            self.assertTrue(
                commands.monitor.processes.launch({"id": 99, "name": "tracked"})
            )
        cmd = popen.call_args[0][0]
        kwargs = popen.call_args[1]
        self.assertEqual(cmd[1:3], ["-m", "app.monitor.run_monitor"])
        self.assertEqual(kwargs.get("cwd"), repo_root)
        self.assertIsNone(kwargs.get("env"))  # plain env inheritance

    def test_monitor_stop_graceful_with_tracked_exited_child(self):
        """A tracked child that already exited must stop gracefully, not escalate.

        Reproduces the interactive-test scenario: the monitor child has exited
        but the parent has not reaped it, so os.kill(pid, 0) reports it as alive.
        Using the tracked Popen handle avoids the false escalation.
        """
        commands, mock_prompt = self._make_commands([])
        monitor = commands.sqlite_handler.get_monitors()[0]
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        try:
            commands.sqlite_handler.update_monitor_status(
                monitor_id=monitor["id"], status=MONITOR_STATUS_RUNNING
            )
            commands.sqlite_handler.update_monitor_pid(
                monitor_id=monitor["id"], pid=child.pid
            )
            commands.monitor.processes.tracked_processes[monitor["id"]] = child
            # Let the child exit WITHOUT reaping it (it becomes a zombie).
            time.sleep(0.5)

            with (
                mock.patch.object(commands.monitor.processes, "escalate_stop") as escalate,
                mock.patch("app.cli.monitor_process_manager.os.kill") as kill_mock,
            ):
                commands.monitor.stop(monitor_id=monitor["id"])

            escalate.assert_not_called()
            kill_mock.assert_not_called()
            self.assertIn("stopped gracefully", mock_prompt.output_text)
            self.assertNotIn("escalating", mock_prompt.output_text)
            self.assertIsNotNone(child.returncode)  # reaped by the stop path
            after = commands.sqlite_handler.get_monitor(monitor_id=monitor["id"])
            self.assertEqual(after["status"], "stopped")
            self.assertEqual(after["pid"], 0)
        finally:
            child.wait()

    def test_monitor_start_without_args_starts_all_not_running(self):
        """No id/name starts every monitor that is not already running."""
        commands, mock_prompt = self._make_commands([])
        monitors = commands.sqlite_handler.get_monitors()
        running, stopped_a, stopped_b = monitors[0], monitors[1], monitors[2]
        commands.sqlite_handler.update_monitor_status(
            monitor_id=running["id"], status=MONITOR_STATUS_RUNNING
        )
        commands.sqlite_handler.update_monitor_pid(
            monitor_id=running["id"], pid=os.getpid()
        )
        commands.sqlite_handler.update_monitor_last_heartbeat(
            monitor_id=running["id"], last_heartbeat=utc_timestamp_now()
        )
        for monitor in (stopped_a, stopped_b):
            commands.sqlite_handler.update_monitor_status(
                monitor_id=monitor["id"], status="stopped"
            )
            commands.sqlite_handler.update_monitor_pid(monitor_id=monitor["id"], pid=0)

        with mock.patch.object(
            commands.monitor.processes, "launch", return_value=True
        ) as launch:
            commands.monitor.start()

        self.assertEqual(launch.call_count, 2)
        self.assertIn("already running", mock_prompt.output_text)

    def test_monitor_stop_without_args_stops_all_monitors(self):
        """No id/name stops every monitor, not just one selected interactively."""
        commands, mock_prompt = self._make_commands([])
        monitors = commands.sqlite_handler.get_monitors()
        for monitor in monitors:
            commands.sqlite_handler.update_monitor_status(
                monitor_id=monitor["id"], status=MONITOR_STATUS_RUNNING
            )
            commands.sqlite_handler.update_monitor_pid(monitor_id=monitor["id"], pid=4242)

        with (
            mock.patch.object(commands.monitor.processes, "wait_for_exit", return_value=True),
            mock.patch.object(commands.monitor.processes, "escalate_stop") as escalate,
        ):
            commands.monitor.stop()

        escalate.assert_not_called()
        for monitor in monitors:
            after = commands.sqlite_handler.get_monitor(monitor_id=monitor["id"])
            self.assertEqual(after["status"], "stopped")
            self.assertEqual(after["pid"], 0)
        self.assertIn("status set to 'stopped'", mock_prompt.output_text)

    # ------------------------------------------------------------------
    # Heartbeat / stale-monitor detection (regression A1)
    # ------------------------------------------------------------------

    def test_heartbeat_age_seconds_parses_fresh_heartbeat(self):
        """A heartbeat written by the monitor process must be parseable."""
        age = MonitorCommands._heartbeat_age_seconds(utc_timestamp_now())
        self.assertIsNotNone(age)
        self.assertLess(age, STALE_HEARTBEAT_SECONDS)

    def test_heartbeat_age_seconds_missing_or_invalid(self):
        self.assertIsNone(MonitorCommands._heartbeat_age_seconds(None))
        self.assertIsNone(MonitorCommands._heartbeat_age_seconds(""))
        self.assertIsNone(MonitorCommands._heartbeat_age_seconds("not-a-timestamp"))

    def test_cleanup_stale_monitors_keeps_fresh_monitor(self):
        """A running monitor with a fresh heartbeat must NOT be treated as stale."""
        commands, mock_prompt = self._make_commands([])
        fresh_monitor = {
            "id": 424242,
            "name": "fresh-monitor",
            "status": MONITOR_STATUS_RUNNING,
            "pid": 999999,
            "last_heartbeat": utc_timestamp_now(),
        }
        stale = commands.monitor._cleanup_stale_monitors([fresh_monitor])
        self.assertEqual(stale, [])
        self.assertNotIn("Forcing stop and restart", mock_prompt.output_text)

    def test_cleanup_stale_monitors_flags_old_heartbeat(self):
        """A running monitor with an old heartbeat must be treated as stale."""
        commands, mock_prompt = self._make_commands([])
        parsed = parse_timestamp(utc_timestamp_now())
        self.assertIsNotNone(parsed)
        old_timestamp = (
            parsed - datetime.timedelta(seconds=STALE_HEARTBEAT_SECONDS + 30)
        ).strftime(TIMESTAMP_FORMAT)
        stale_monitor = {
            "id": 424243,
            "name": "old-monitor",
            "status": MONITOR_STATUS_RUNNING,
            # pid 0 so the test never attempts a real kill.
            "pid": 0,
            "last_heartbeat": old_timestamp,
        }
        stale = commands.monitor._cleanup_stale_monitors([stale_monitor])
        self.assertEqual(len(stale), 1)
        self.assertIn("Forcing stop and restart", mock_prompt.output_text)


class TestCommandProfileValidation(unittest.TestCase):
    """``_test_command_profile`` must accept legacy comma-separated event strings.

    Regression: it iterated ``command_events`` directly, so a legacy string was
    checked character by character and produced bogus "Invalid event(s)" errors.
    """

    logger = logging.getLogger(__name__)

    def _make(self) -> tuple[ProfileCommands, MockPromptService]:
        prompt = MockPromptService(inputs=[])
        commands = ProfileCommands(
            sqlite_handler=mock.Mock(),
            logger=self.logger,
            profile_importer=mock.Mock(),
            prompt=prompt,
        )
        return commands, prompt

    def test_comma_separated_events_are_parsed(self):
        commands, prompt = self._make()
        ok = commands._test_command_profile(
            "cmd-profile",
            {"command": "echo hi", "command_events": "created,modified"},
        )
        self.assertTrue(ok)
        self.assertNotIn("Invalid event(s)", prompt.output_text)

    def test_invalid_event_in_string_is_reported(self):
        commands, prompt = self._make()
        ok = commands._test_command_profile(
            "cmd-profile",
            {"command": "echo hi", "command_events": "created,bogus"},
        )
        self.assertFalse(ok)
        self.assertIn("Invalid event(s): bogus", prompt.output_text)

    def test_event_list_is_accepted(self):
        commands, prompt = self._make()
        ok = commands._test_command_profile(
            "cmd-profile",
            {"command": "echo hi", "command_events": ["created", "timer"]},
        )
        self.assertTrue(ok)
        self.assertNotIn("Invalid event(s)", prompt.output_text)


if __name__ == "__main__":
    unittest.main()