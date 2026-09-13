import threading
import time
import unittest
from unittest.mock import patch

from app.monitor.action_handler import (
    ActionContext,
    ActionHandlerFactory,
    CommandActionHandler,
    RemoteActionHandler,
)


def make_context(event_type="created", src_path="/tmp/file.txt", dest_path="", is_directory=False):
    return ActionContext(
        event_type=event_type,
        src_path=src_path,
        dest_path=dest_path,
        is_directory=is_directory,
    )


class TestCommandActionHandler(unittest.TestCase):
    def test_empty_command_raises(self):
        with self.assertRaises(ValueError):
            CommandActionHandler(command="   ")

    def test_build_values(self):
        handler = CommandActionHandler(command="echo hi", monitor_name="MyMonitor", profile_name="MyProfile")
        values = handler._build_values(
            make_context(event_type="moved", src_path="/tmp/a")
        )
        self.assertEqual(values["event_name"], "moved")
        self.assertEqual(values["src_path"], "/tmp/a")
        self.assertEqual(values["monitor_name"], "MyMonitor")
        self.assertEqual(values["profile_name"], "MyProfile")

    def test_build_values_empty_dest(self):
        handler = CommandActionHandler(command="echo hi", monitor_name="M", profile_name="P")
        values = handler._build_values(make_context())
        self.assertEqual(values["src_path"], "/tmp/file.txt")
        self.assertEqual(values["event_name"], "created")

    def test_build_argv_substitutes_placeholders(self):
        handler = CommandActionHandler(command="notify {event_name} {src_path} {profile_name}")
        argv = handler._build_argv(
            {"event_name": "created", "src_path": "/tmp/my file.txt", "profile_name": "P1", "monitor_name": "M1"}
        )
        self.assertEqual(argv, ["notify", "created", "/tmp/my file.txt", "P1"])

    def test_substitute_shell_quotes_placeholders(self):
        handler = CommandActionHandler(command="notify {src_path}")
        cmd = handler._substitute_shell({"src_path": "/tmp/my file.txt", "event_name": "created", "profile_name": "P", "monitor_name": "M"})
        self.assertIn("'/tmp/my file.txt'", cmd)

    def test_handle_action_filters_events(self):
        handler = CommandActionHandler(command="echo hi", events=["created", "modified"])
        with patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="deleted"))
            dispatch_mock.assert_not_called()

    def test_handle_action_cooldown_suppresses_repeat(self):
        handler = CommandActionHandler(command="echo hi", cooldown="1h")
        with patch("time.time", return_value=100.0), patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="created"))
            dispatch_mock.assert_called_once()

        # Second firing is within the cooldown window (1h = 3600s).
        with patch("time.time", return_value=100.0 + 60), patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="created"))
            dispatch_mock.assert_not_called()

    def test_handle_action_cooldown_suppresses_different_event_type(self):
        handler = CommandActionHandler(command="echo hi", cooldown="10s")
        with patch("time.time", return_value=100.0), patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="created"))
            dispatch_mock.assert_called_once()

        # Different event type ('modified') within 10s cooldown window should also be suppressed.
        with patch("time.time", return_value=100.0 + 2), patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="modified"))
            dispatch_mock.assert_not_called()

    def test_handle_action_zero_cooldown_fires_all_events(self):
        handler = CommandActionHandler(command="echo hi", cooldown="0s")
        with patch("time.time", return_value=100.0), patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="created"))
            dispatch_mock.assert_called_once()

        with patch("time.time", return_value=100.0 + 0.1), patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="modified"))
            dispatch_mock.assert_called_once()

    def test_handle_action_fires_after_cooldown_expires(self):
        handler = CommandActionHandler(command="echo hi", cooldown="1h")
        with patch("time.time", return_value=100.0), patch.object(handler, "_dispatch"):
            handler.handle_action(make_context(event_type="created"))

        # After the cooldown window has elapsed it should fire again.
        with patch("time.time", return_value=100.0 + 3601), patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="created"))
            dispatch_mock.assert_called_once()

    def test_handle_action_dispatches_on_first_fire(self):
        handler = CommandActionHandler(command="echo hi", cooldown="1h")
        with patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="created"))
            dispatch_mock.assert_called_once()

    def test_default_cooldown_is_zero(self):
        handler = CommandActionHandler(command="echo hi")
        self.assertEqual(handler.cooldown_seconds, 0)

    def test_handle_action_timer_event_fires_when_listed(self):
        handler = CommandActionHandler(command="echo hi", events=["timer"])
        with patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="timer"))
            dispatch_mock.assert_called_once()

    def test_handle_action_timer_event_skipped_when_not_listed(self):
        handler = CommandActionHandler(command="echo hi", events=["created"])
        with patch.object(handler, "_dispatch") as dispatch_mock:
            handler.handle_action(make_context(event_type="timer"))
            dispatch_mock.assert_not_called()

    # ------------------------------------------------------------------
    # Bounded command executor
    # ------------------------------------------------------------------

    def test_max_workers_default_and_clamping(self):
        self.assertEqual(CommandActionHandler(command="echo hi").max_workers, 100)
        self.assertEqual(CommandActionHandler(command="echo hi", max_workers=0).max_workers, 1)
        self.assertEqual(CommandActionHandler(command="echo hi", max_workers=-5).max_workers, 1)
        self.assertEqual(CommandActionHandler(command="echo hi", max_workers=5000).max_workers, 1000)
        self.assertEqual(CommandActionHandler(command="echo hi", max_workers="abc").max_workers, 100)
        self.assertEqual(CommandActionHandler(command="echo hi", max_workers="250").max_workers, 250)

    def test_executor_is_bounded_by_max_workers(self):
        handler = CommandActionHandler(command="echo hi", cooldown="0s", max_workers=3)
        release = threading.Event()
        running: list[int] = []
        running_lock = threading.Lock()

        def fake_run(values):
            with running_lock:
                running.append(1)
            release.wait(5)
            with running_lock:
                running.pop()

        try:
            with patch.object(handler, "_run_command", side_effect=fake_run):
                for i in range(10):
                    handler.handle_action(make_context(src_path=f"/tmp/f{i}"))
                time.sleep(0.3)
                with running_lock:
                    self.assertGreater(len(running), 0)
                    self.assertLessEqual(len(running), 3)
                release.set()
                deadline = time.time() + 5
                while handler.pending_commands > 0 and time.time() < deadline:
                    time.sleep(0.01)
        finally:
            release.set()
            handler.stop()

        self.assertEqual(handler.pending_commands, 0)

    def test_all_submitted_commands_run_when_exceeding_workers(self):
        """A bound on concurrency must never drop events: every command runs."""
        handler = CommandActionHandler(command="echo hi", cooldown="0s", max_workers=2)
        executed: list[str] = []
        executed_lock = threading.Lock()

        def fake_run(values):
            with executed_lock:
                executed.append(values["src_path"])
            time.sleep(0.01)

        try:
            with patch.object(handler, "_run_command", side_effect=fake_run):
                for i in range(6):
                    handler.handle_action(make_context(src_path=f"/tmp/f{i}"))
                deadline = time.time() + 5
                while handler.pending_commands > 0 and time.time() < deadline:
                    time.sleep(0.01)
        finally:
            handler.stop()

        self.assertEqual(len(executed), 6)
        self.assertEqual(set(executed), {f"/tmp/f{i}" for i in range(6)})

    def test_stop_cancels_queued_commands(self):
        handler = CommandActionHandler(command="echo hi", cooldown="0s", max_workers=1)
        started = threading.Event()
        release = threading.Event()
        executed: list[str] = []
        executed_lock = threading.Lock()

        def fake_run(values):
            with executed_lock:
                executed.append(values["src_path"])
            started.set()
            release.wait(5)

        with patch.object(handler, "_run_command", side_effect=fake_run):
            for i in range(5):
                handler.handle_action(make_context(src_path=f"/tmp/f{i}"))
            self.assertTrue(started.wait(5))
            handler.stop(wait=False, cancel_futures=True)
        release.set()
        time.sleep(0.1)

        # Only the single running command executed; the queued ones were cancelled.
        self.assertEqual(len(executed), 1)
        self.assertIsNone(handler._executor)

    def test_dispatch_after_stop_is_ignored(self):
        handler = CommandActionHandler(command="echo hi", cooldown="0s")
        with patch.object(handler, "_run_command") as run_mock:
            handler.handle_action(make_context(src_path="/tmp/first"))
            deadline = time.time() + 2
            while run_mock.call_count == 0 and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(run_mock.call_count, 1)

            handler.stop()
            handler.handle_action(make_context(src_path="/tmp/late"))
            time.sleep(0.05)
            self.assertEqual(run_mock.call_count, 1)

    def test_stop_is_idempotent(self):
        handler = CommandActionHandler(command="echo hi")
        handler.stop()
        handler.stop()
        self.assertIsNone(handler._executor)

    def test_backlog_warning_logged_once_when_saturated(self):
        handler = CommandActionHandler(command="echo hi", cooldown="0s", max_workers=1)
        release = threading.Event()
        started = threading.Event()

        def fake_run(values):
            started.set()
            release.wait(5)

        try:
            with (
                patch.object(handler, "_run_command", side_effect=fake_run),
                patch.object(handler.logger, "warning") as warn_mock,
            ):
                for i in range(4):
                    handler.handle_action(make_context(src_path=f"/tmp/f{i}"))
                self.assertTrue(started.wait(5))
                # One warning per overload episode, not one per queued event.
                self.assertEqual(warn_mock.call_count, 1)
        finally:
            release.set()
            handler.stop()

    def test_run_command_nonzero_return_code(self):
        handler = CommandActionHandler(command="false")

        class DummyResult:
            returncode = 1
            stdout = ""
            stderr = "boom"

        with (
            patch("subprocess.run", return_value=DummyResult()) as run_mock,
            patch.object(handler.logger, "warning") as warn_mock
            ):
                handler._run_command(
                    {"event_name": "created", "src_path": "/tmp/x", "profile_name": "P", "monitor_name": "M"}
                )
                run_mock.assert_called_once()
                warn_mock.assert_called_once()

    def test_run_command_success(self):
        handler = CommandActionHandler(command="true")

        class DummyResult:
            returncode = 0
            stdout = ""
            stderr = ""

        with (
            patch("subprocess.run", return_value=DummyResult()) as run_mock,
            patch.object(handler.logger, "warning") as warn_mock
            ):
                handler._run_command(
                    {"event_name": "created", "src_path": "/tmp/x", "profile_name": "P", "monitor_name": "M"}
                )
                run_mock.assert_called_once()
                warn_mock.assert_not_called()


class TestActionHandlerFactory(unittest.TestCase):
    def test_factory_creates_command_action_handler(self):
        monitor = {"name": "test-mon", "monitor_path": "/tmp/mon"}
        profile = {
            "name": "cmd-prof",
            "profile_type": "event_command",
            "config": {
                "command": "echo {src_path}",
                "command_events": ["created", "modified"],
                "command_cooldown": "5m",
            },
        }
        handler = ActionHandlerFactory.get_handler(monitor=monitor, profile=profile)
        self.assertIsInstance(handler, CommandActionHandler)
        assert isinstance(handler, CommandActionHandler)
        self.assertEqual(handler.command, "echo {src_path}")
        self.assertEqual(handler.events, ["created", "modified"])
        self.assertEqual(handler.cooldown_seconds, 300)

    def test_factory_creates_command_action_handler_for_event_command(self):
        monitor = {"name": "test-mon", "monitor_path": "/tmp/mon"}
        profile = {
            "name": "file-event-prof",
            "profile_type": "event_command",
            "config": {
                "command": "sh process.sh {src_path}",
                "command_events": ["closed"],
                "command_cooldown": "10s",
            },
        }
        handler = ActionHandlerFactory.get_handler(monitor=monitor, profile=profile)
        self.assertIsInstance(handler, CommandActionHandler)
        assert isinstance(handler, CommandActionHandler)
        self.assertEqual(handler.command, "sh process.sh {src_path}")
        self.assertEqual(handler.events, ["closed"])
        self.assertEqual(handler.cooldown_seconds, 10)

    def test_factory_creates_command_action_handler_with_explicit_category(self):
        monitor = {"name": "test-mon", "monitor_path": "/tmp/mon"}
        profile = {
            "name": "custom-cmd-prof",
            "profile_type": "custom_type",
            "category": "command",
            "config": {
                "command": "notify.sh {event_name}",
            },
        }
        handler = ActionHandlerFactory.get_handler(monitor=monitor, profile=profile)
        self.assertIsInstance(handler, CommandActionHandler)
        assert isinstance(handler, CommandActionHandler)
        self.assertEqual(handler.command, "notify.sh {event_name}")

    def test_factory_reads_command_max_workers(self):
        monitor = {"name": "test-mon", "monitor_path": "/tmp/mon"}
        profile = {
            "name": "cmd-prof",
            "profile_type": "event_command",
            "config": {
                "command": "echo hi",
                "command_max_workers": 250,
            },
        }
        handler = ActionHandlerFactory.get_handler(monitor=monitor, profile=profile)
        assert isinstance(handler, CommandActionHandler)
        self.assertEqual(handler.max_workers, 250)

    def test_factory_creates_remote_action_handler_for_rclone(self):
        monitor = {"name": "test-mon", "monitor_path": "/tmp/mon", "remote_path": "remote:dest"}
        profile = {
            "name": "rclone-prof",
            "profile_type": "s3",
            "config": {},
        }
        handler = ActionHandlerFactory.get_handler(monitor=monitor, profile=profile)
        self.assertIsInstance(handler, RemoteActionHandler)

    def test_factory_returns_none_for_missing_profile(self):
        monitor = {"name": "test-mon", "monitor_path": "/tmp/mon", "remote_path": "remote:dest"}
        handler = ActionHandlerFactory.get_handler(monitor=monitor, profile=None)
        self.assertIsNone(handler)
        handler_empty = ActionHandlerFactory.get_handler(monitor=monitor, profile={})
        self.assertIsNone(handler_empty)


if __name__ == "__main__":
    unittest.main()
