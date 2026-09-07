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
        with patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="deleted"))
            self.assertEqual(thread_mock.call_count, 0)

    def test_handle_action_cooldown_suppresses_repeat(self):
        handler = CommandActionHandler(command="echo hi", cooldown="1h")
        with patch("time.time", return_value=100.0):
            handler.handle_action(make_context(event_type="created"))

        # Second firing is within the cooldown window (1h = 3600s).
        with patch("time.time", return_value=100.0 + 60), patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="created"))
            self.assertEqual(thread_mock.call_count, 0)

    def test_handle_action_cooldown_suppresses_different_event_type(self):
        handler = CommandActionHandler(command="echo hi", cooldown="10s")
        with patch("time.time", return_value=100.0), patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="created"))
            self.assertEqual(thread_mock.call_count, 1)

        # Different event type ('modified') within 10s cooldown window should also be suppressed.
        with patch("time.time", return_value=100.0 + 2), patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="modified"))
            self.assertEqual(thread_mock.call_count, 0)

    def test_handle_action_zero_cooldown_fires_all_events(self):
        handler = CommandActionHandler(command="echo hi", cooldown="0s")
        with patch("time.time", return_value=100.0), patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="created"))
            self.assertEqual(thread_mock.call_count, 1)

        with patch("time.time", return_value=100.0 + 0.1), patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="modified"))
            self.assertEqual(thread_mock.call_count, 1)

    def test_handle_action_fires_after_cooldown_expires(self):
        handler = CommandActionHandler(command="echo hi", cooldown="1h")
        with patch("time.time", return_value=100.0):
            handler.handle_action(make_context(event_type="created"))

        # After the cooldown window has elapsed it should fire again.
        with patch("time.time", return_value=100.0 + 3601), patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="created"))
            thread_mock.assert_called_once()

    def test_handle_action_dispatches_on_first_fire(self):
        handler = CommandActionHandler(command="echo hi", cooldown="1h")
        with patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="created"))
            thread_mock.assert_called_once()

    def test_default_cooldown_is_zero(self):
        handler = CommandActionHandler(command="echo hi")
        self.assertEqual(handler.cooldown_seconds, 0)

    def test_handle_action_timer_event_fires_when_listed(self):
        handler = CommandActionHandler(command="echo hi", events=["timer"])
        with patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="timer"))
            self.assertEqual(thread_mock.call_count, 1)

    def test_handle_action_timer_event_skipped_when_not_listed(self):
        handler = CommandActionHandler(command="echo hi", events=["created"])
        with patch("threading.Thread") as thread_mock:
            thread_mock.return_value.start.return_value = None
            handler.handle_action(make_context(event_type="timer"))
            self.assertEqual(thread_mock.call_count, 0)

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
