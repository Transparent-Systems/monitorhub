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
from unittest import mock

from app.cli.commands import Commands, build_commands
from app.cli.monitor_commands import STALE_HEARTBEAT_SECONDS, MonitorCommands
from app.monitor.action_handler import DEFAULT_COMMAND_MAX_WORKERS
from app.utils.constants import MONITOR_STATUS_RUNNING, TIMESTAMP_FORMAT
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


if __name__ == "__main__":
    unittest.main()