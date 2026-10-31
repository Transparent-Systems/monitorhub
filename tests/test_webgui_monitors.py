"""Headless Streamlit tests for the Monitors page status/action mapping."""

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.monitor.monitor_process_manager import MonitorProcessManager
from app.utils.constants import (
    MONITOR_STATUS_RUNNING,
    MONITOR_STATUS_STOP,
    MONITOR_STATUS_STOPPED,
)
from app.utils.sqlite_handler import SQLiteHandler

PAGE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "webgui" / "pages" / "monitors.py"
)

logger = logging.getLogger("test.webgui.monitors")
logger.addHandler(logging.NullHandler())
logger.setLevel(logging.CRITICAL)

# A PID high enough that it cannot belong to a live process in practice.
DEAD_PID = 999_999_999


class TestMonitorsPageActions(unittest.TestCase):
    """Verify the Start/Stop label and stale-status rendering."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_dir = self._temp_dir.name
        self.sqlite_handler = SQLiteHandler(logger=logger, db_dir=self.db_dir)
        self.sqlite_handler.create_schema()

    def tearDown(self) -> None:
        self.sqlite_handler.close()
        self._temp_dir.cleanup()

    def _add_monitor(
        self,
        status: str,
        pid: int,
        monitor_path: str | None = None,
        remote_path: str = "/tmp/destination",
    ) -> int:
        monitor_id = self.sqlite_handler.add_monitor(
            name="monitor",
            monitor_path=monitor_path or self.db_dir,
            remote_path=remote_path,
            monitor_type="instant",
            config={},
            status=status,
            pid=pid,
        )
        self.assertIsNotNone(monitor_id)
        return int(monitor_id)

    def _add_profile(self, name: str, profile_type: str) -> int:
        profile_id = self.sqlite_handler.add_profile(
            name=name,
            profile_type=profile_type,
            config=(
                {"command": "echo hi"}
                if profile_type == "event_command"
                else {"remote_handler": "s3"}
            ),
        )
        self.assertIsNotNone(profile_id)
        return int(profile_id)

    def _select_profiles(self, at: AppTest, labels: list[str]) -> None:
        """Set the 'Attach profiles' picker (it lives outside the form)."""
        matches = [widget for widget in at.multiselect if widget.key.endswith("_profiles")]
        self.assertEqual(len(matches), 1, [widget.key for widget in at.multiselect])
        matches[0].set_value(labels)

    def _run_page(self) -> AppTest:
        with patch(
            "app.utils.app_config.AppConfig.get_default_db_dir",
            return_value=self.db_dir,
        ):
            at = AppTest.from_file(str(PAGE_PATH), default_timeout=30)
            at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    @staticmethod
    def _labels(at: AppTest) -> list[str]:
        return [button.label for button in at.button]

    @staticmethod
    def _warnings(at: AppTest) -> list[str]:
        return [warning.value for warning in at.warning]

    @staticmethod
    def _errors(at: AppTest) -> list[str]:
        return [error.value for error in at.error]

    def _click(self, at: AppTest, label: str) -> None:
        matches = [button for button in at.button if button.label == label]
        self.assertEqual(len(matches), 1, (label, self._labels(at)))
        matches[0].click().run()
        self.assertFalse(at.exception, at.exception)

    def _text_input(self, at: AppTest, key: str):
        matches = [widget for widget in at.text_input if widget.key == key]
        self.assertEqual(
            len(matches), 1, (key, [(w.label, w.key) for w in at.text_input])
        )
        return matches[0]

    def test_stopped_monitor_offers_start(self) -> None:
        self._add_monitor(MONITOR_STATUS_STOPPED, 0)
        at = self._run_page()
        self.assertIn("▶ Start", self._labels(at))
        self.assertNotIn("■ Stop", self._labels(at))
        self.assertFalse(any("stale" in warning for warning in self._warnings(at)))

    def test_toolbar_offers_a_refresh_button(self) -> None:
        # Monitor status also changes without a click (scheduled monitors, a
        # child still booting), so the page offers a deliberate refresh instead
        # of relying on the browser's own reload.
        self._add_monitor(MONITOR_STATUS_STOPPED, 0)
        at = self._run_page()
        self.assertIn("↻ Refresh", self._labels(at))

    def test_running_monitor_with_live_pid_offers_stop(self) -> None:
        self._add_monitor(MONITOR_STATUS_RUNNING, os.getpid())
        at = self._run_page()
        self.assertIn("■ Stop", self._labels(at))
        self.assertNotIn("▶ Start", self._labels(at))
        self.assertFalse(any("stale" in warning for warning in self._warnings(at)))

    def test_stopping_monitor_offers_stop_now(self) -> None:
        self._add_monitor(MONITOR_STATUS_STOP, os.getpid())
        at = self._run_page()
        labels = self._labels(at)
        self.assertIn("■ Stop now", labels)
        self.assertNotIn("■ Stopping…", labels)
        self.assertNotIn("✕ Force Stop", labels)
        stop_now = [button for button in at.button if button.label == "■ Stop now"][0]
        self.assertFalse(stop_now.disabled)

    def test_stop_now_force_stops_and_returns_to_start(self) -> None:
        monitor_id = self._add_monitor(MONITOR_STATUS_STOP, os.getpid())
        at = self._run_page()

        with patch.object(
            MonitorProcessManager, "force_kill", return_value=True
        ) as force_kill:
            self._click(at, "■ Stop now")

        force_kill.assert_called_once()
        self.assertIn("▶ Start", self._labels(at))
        monitor = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
        self.assertEqual(monitor["status"], MONITOR_STATUS_STOPPED)
        self.assertEqual(int(monitor["pid"] or 0), 0)

    def test_stale_running_monitor_offers_start_and_is_marked_stale(self) -> None:
        self._add_monitor(MONITOR_STATUS_RUNNING, DEAD_PID)
        at = self._run_page()
        self.assertIn("▶ Start", self._labels(at))
        self.assertNotIn("■ Stop", self._labels(at))
        warnings = self._warnings(at)
        self.assertTrue(any("stale" in warning for warning in warnings), warnings)
        table = at.dataframe[0].value
        self.assertEqual(list(table["Status"]), ["running (stale)"])

    def test_new_monitor_rejects_missing_path(self) -> None:
        """The create form refuses a path that does not exist."""
        at = self._run_page()
        self._click(at, "＋ New")
        self._text_input(at, "new_monitor_name").set_value("new-monitor")
        missing = str(Path(self.db_dir) / "missing")
        self._text_input(at, "new_monitor_path").set_value(missing)
        self._text_input(at, "new_monitor_remote").set_value("remote:destination")
        self._click(at, "Save")

        errors = self._errors(at)
        self.assertTrue(any("does not exist" in error for error in errors), errors)
        self.assertEqual(self.sqlite_handler.get_monitors(), [])

    def test_start_rejects_missing_path(self) -> None:
        """Start reports an invalid path without launching a child process."""
        missing = str(Path(self.db_dir) / "missing")
        self._add_monitor(MONITOR_STATUS_STOPPED, 0, monitor_path=missing)
        at = self._run_page()

        with patch.object(MonitorProcessManager, "launch") as launch:
            self._click(at, "▶ Start")

        launch.assert_not_called()
        errors = self._errors(at)
        self.assertTrue(
            any("cannot start" in error and "does not exist" in error for error in errors),
            errors,
        )

    def test_start_rejects_monitor_without_profiles(self) -> None:
        """Start refuses a monitor with no profiles instead of launching it.

        A launched child would find no profiles and exit immediately, which the
        page would otherwise report as a startup failure.
        """
        self._add_monitor(MONITOR_STATUS_STOPPED, 0)
        at = self._run_page()

        with patch.object(MonitorProcessManager, "launch") as launch:
            self._click(at, "▶ Start")

        launch.assert_not_called()
        errors = self._errors(at)
        self.assertTrue(
            any(
                "cannot start" in error and "Attach at least one profile" in error
                for error in errors
            ),
            errors,
        )

    def test_new_monitor_requires_a_profile(self) -> None:
        """The create form refuses a monitor with no profiles attached."""
        self.sqlite_handler.add_profile(
            name="s3-profile", profile_type="s3", config={"remote_handler": "s3"}
        )
        at = self._run_page()
        self._click(at, "＋ New")
        self._text_input(at, "new_monitor_name").set_value("new-monitor")
        self._text_input(at, "new_monitor_path").set_value(self.db_dir)
        self._text_input(at, "new_monitor_remote").set_value("remote:destination")
        self._click(at, "Save")

        errors = self._errors(at)
        self.assertTrue(
            any("Attach at least one profile" in error for error in errors), errors
        )
        self.assertEqual(self.sqlite_handler.get_monitors(), [])

    def test_edit_monitor_requires_a_profile(self) -> None:
        """Detaching the last profile is refused, so the monitor stays runnable."""
        profile_id = self.sqlite_handler.add_profile(
            name="s3-profile", profile_type="s3", config={"remote_handler": "s3"}
        )
        monitor_id = self._add_monitor(MONITOR_STATUS_STOPPED, 0)
        self.sqlite_handler.add_monitor_profile_map(
            monitor_id=monitor_id, profile_id=profile_id
        )

        at = self._run_page()
        self._click(at, "✎ Edit")
        self.assertEqual(len(at.multiselect), 1, [w.label for w in at.multiselect])
        at.multiselect[0].set_value([])
        self._click(at, "Save")

        errors = self._errors(at)
        self.assertTrue(
            any("Attach at least one profile" in error for error in errors), errors
        )
        linked = self.sqlite_handler.get_profiles_for_monitor(monitor_id=monitor_id)
        self.assertEqual({profile["id"] for profile in linked}, {profile_id})

    def test_new_monitor_requires_remote_path_for_remote_profile(self) -> None:
        """A remote profile needs a destination, so Save is refused without one."""
        profile_id = self._add_profile("s3-profile", "s3")
        at = self._run_page()
        self._click(at, "＋ New")
        self._text_input(at, "new_monitor_name").set_value("remote-monitor")
        self._text_input(at, "new_monitor_path").set_value(self.db_dir)
        self._select_profiles(at, [f"{profile_id}: s3-profile"])
        self._click(at, "Save")

        errors = self._errors(at)
        self.assertTrue(any("Remote path is required" in error for error in errors), errors)
        self.assertIsNone(
            self.sqlite_handler.get_monitor(monitor_name="remote-monitor")
        )

    def test_new_monitor_allows_empty_remote_path_for_command_profile(self) -> None:
        """A command-only monitor needs no remote path and saves without one."""
        profile_id = self._add_profile("cmd-profile", "event_command")
        at = self._run_page()
        self._click(at, "＋ New")
        self._text_input(at, "new_monitor_name").set_value("command-monitor")
        self._text_input(at, "new_monitor_path").set_value(self.db_dir)
        self._select_profiles(at, [f"{profile_id}: cmd-profile"])
        self._click(at, "Save")

        self.assertEqual(self._errors(at), [])
        monitor = self.sqlite_handler.get_monitor(monitor_name="command-monitor")
        self.assertIsNotNone(monitor)
        self.assertEqual(monitor["remote_path"], "")
        linked = self.sqlite_handler.get_profiles_for_monitor(monitor_id=monitor["id"])
        self.assertEqual({profile["id"] for profile in linked}, {profile_id})

    def test_edit_keeps_remote_path_for_command_only_monitor(self) -> None:
        """Editing a command-only monitor does not clear its stored remote path.

        The remote path is only *needed* by a remote profile, so it is left as
        it is rather than removed behind the user's back.
        """
        profile_id = self._add_profile("cmd-profile", "event_command")
        monitor_id = self._add_monitor(
            MONITOR_STATUS_STOPPED, 0, remote_path="left-over-destination"
        )
        self.sqlite_handler.add_monitor_profile_map(
            monitor_id=monitor_id, profile_id=profile_id
        )

        at = self._run_page()
        self._click(at, "✎ Edit")
        self._click(at, "Save")

        self.assertEqual(self._errors(at), [])
        updated = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
        self.assertEqual(updated["remote_path"], "left-over-destination")

    def test_start_rejects_remote_profile_without_remote_path(self) -> None:
        """Start refuses a remote profile with no destination."""
        profile_id = self._add_profile("s3-profile", "s3")
        monitor_id = self._add_monitor(MONITOR_STATUS_STOPPED, 0, remote_path="")
        self.sqlite_handler.add_monitor_profile_map(
            monitor_id=monitor_id, profile_id=profile_id
        )

        at = self._run_page()
        with patch.object(MonitorProcessManager, "launch") as launch:
            self._click(at, "▶ Start")

        launch.assert_not_called()
        errors = self._errors(at)
        self.assertTrue(
            any(
                "cannot start" in error and "Remote path is required" in error
                for error in errors
            ),
            errors,
        )

    def test_force_stop_is_not_offered(self) -> None:
        self._add_monitor(MONITOR_STATUS_STOPPED, 0)
        at = self._run_page()
        self.assertNotIn("✕ Force Stop", self._labels(at))


if __name__ == "__main__":
    unittest.main()
