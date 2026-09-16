import contextlib
import io
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

from app.monitor.run_monitor import (
    MonitorRunContext,
    main,
    parse_args,
    run_monitor_main,
)

from tests.base_test_class import BaseTestClass


class TestRunMonitor(BaseTestClass):
    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_run_monitor_missing_monitor_exits(self, mock_setup_logging, mock_sqlite_cls):
        mock_logger = MagicMock()
        mock_setup_logging.return_value = (mock_logger, {})
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = None
        mock_sqlite_cls.return_value = mock_sqlite

        with self.assertRaises(SystemExit) as cm:
            run_monitor_main(["--monitor-id", "999", "--db-dir", self.db_dir])

        self.assertEqual(cm.exception.code, 1)
        mock_sqlite.close.assert_called_once()

    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_run_monitor_missing_profiles_exits(self, mock_setup_logging, mock_sqlite_cls):
        mock_logger = MagicMock()
        mock_setup_logging.return_value = (mock_logger, {})
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = {"id": 1, "name": "test_monitor"}
        mock_sqlite.get_profiles_for_monitor.return_value = []
        mock_sqlite_cls.return_value = mock_sqlite

        with self.assertRaises(SystemExit) as cm:
            run_monitor_main(["--monitor-id", "1", "--db-dir", self.db_dir])

        self.assertEqual(cm.exception.code, 1)
        mock_sqlite.close.assert_called_once()

    @patch("app.monitor.run_monitor.MonitorHandlerFactory")
    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_run_monitor_handler_start_failure(
        self, mock_setup_logging, mock_sqlite_cls, mock_factory
    ):
        mock_logger = MagicMock()
        mock_setup_logging.return_value = (mock_logger, {})
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = {
            "id": 1,
            "name": "test_monitor",
            "monitor_type": "scheduled",
        }
        mock_sqlite.get_profiles_for_monitor.return_value = [{"id": 1, "name": "p1"}]
        mock_sqlite_cls.return_value = mock_sqlite

        mock_handler = MagicMock()
        mock_handler.start.return_value = False
        mock_factory.create.return_value = mock_handler

        with self.assertRaises(SystemExit) as cm:
            run_monitor_main(["--monitor-id", "1", "--db-dir", self.db_dir])

        self.assertEqual(cm.exception.code, 1)
        mock_sqlite.update_monitor_status.assert_called_with(monitor_id=1, status="stopped")
        mock_sqlite.update_monitor_pid.assert_called_with(monitor_id=1, pid=0)
        mock_sqlite.close.assert_called()

    @patch("app.monitor.run_monitor.MonitorHandlerFactory")
    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_run_monitor_refuses_when_pid_alive(
        self, mock_setup_logging, mock_sqlite_cls, mock_factory
    ):
        """Single-instance guard: refuse when another live process owns the monitor."""
        mock_logger = MagicMock()
        mock_setup_logging.return_value = (mock_logger, {})
        mock_sqlite = MagicMock()

        # A live child process stands in for an already-running monitor.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            mock_sqlite.get_monitor.return_value = {
                "id": 1,
                "name": "test_monitor",
                "monitor_type": "instant",
                # Intermediate 'stop' state with a PID that is still alive.
                "status": "stop",
                "pid": child.pid,
            }
            mock_sqlite.get_profiles_for_monitor.return_value = [{"id": 1, "name": "p1"}]
            mock_sqlite_cls.return_value = mock_sqlite

            with self.assertRaises(SystemExit) as cm:
                run_monitor_main(["--monitor-id", "1", "--db-dir", self.db_dir])

            self.assertEqual(cm.exception.code, 1)
            mock_factory.create.assert_not_called()
            mock_sqlite.close.assert_called_once()
        finally:
            child.terminate()
            child.wait()

    @patch("app.monitor.run_monitor.run_monitor_main")
    def test_main_cli_entry_point(self, mock_run_main):
        mock_run_main.return_value = 0
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 0)
        mock_run_main.assert_called_once()

    @patch("app.monitor.run_monitor.MonitorHandlerFactory")
    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_run_monitor_on_complete_clean_shutdown(
        self, mock_setup_logging, mock_sqlite_cls, mock_factory
    ):
        """Verify on_complete callback triggers graceful shutdown and returns 0 without os._exit."""
        mock_logger = MagicMock()
        mock_setup_logging.return_value = (mock_logger, {})
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = {
            "id": 1,
            "name": "test_monitor",
            "monitor_type": "scheduled",
        }
        mock_sqlite.get_profiles_for_monitor.return_value = [{"id": 1, "name": "p1"}]
        mock_sqlite_cls.return_value = mock_sqlite

        mock_handler = MagicMock()

        def fake_start(on_complete=None):
            def complete_worker():
                time.sleep(0.05)
                if on_complete:
                    on_complete("one-off task finished")

            t = threading.Thread(target=complete_worker)
            t.start()
            return True

        mock_handler.start.side_effect = fake_start
        mock_factory.create.return_value = mock_handler

        ret = run_monitor_main(["--monitor-id", "1", "--db-dir", self.db_dir])
        self.assertEqual(ret, 0)

        mock_handler.stop.assert_called_once()
        mock_sqlite.update_monitor_status.assert_called_with(monitor_id=1, status="stopped")
        mock_sqlite.update_monitor_pid.assert_called_with(monitor_id=1, pid=0)
        mock_sqlite.close.assert_called_once()

    @patch("app.monitor.run_monitor.MonitorHandlerFactory")
    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_run_monitor_signal_shutdown(
        self, mock_setup_logging, mock_sqlite_cls, mock_factory
    ):
        """Verify SIGTERM/SIGINT signal triggers graceful shutdown and returns 0."""
        mock_logger = MagicMock()
        mock_setup_logging.return_value = (mock_logger, {})
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = {
            "id": 1,
            "name": "test_monitor",
            "monitor_type": "instant",
        }
        mock_sqlite.get_profiles_for_monitor.return_value = [{"id": 1, "name": "p1"}]
        mock_sqlite_cls.return_value = mock_sqlite

        mock_handler = MagicMock()
        mock_handler.start.return_value = True
        mock_factory.create.return_value = mock_handler

        def send_signal():
            time.sleep(0.1)
            os.kill(os.getpid(), signal.SIGINT)

        sig_thread = threading.Thread(target=send_signal)
        sig_thread.start()

        ret = run_monitor_main(["--monitor-id", "1", "--db-dir", self.db_dir])
        sig_thread.join()

        self.assertEqual(ret, 0)
        mock_handler.stop.assert_called_once()
        mock_sqlite.update_monitor_status.assert_called_with(monitor_id=1, status="stopped")
        mock_sqlite.update_monitor_pid.assert_called_with(monitor_id=1, pid=0)
        mock_sqlite.close.assert_called_once()


class TestRunMonitorPhases(BaseTestClass):
    """Unit tests for the individual monitor lifecycle phases.

    These exercise parse_args, MonitorRunContext.get_monitor_context and the
    run_until_shutdown/teardown/run methods in isolation. The end-to-end
    behaviour is covered by TestRunMonitor above.
    """

    def _make_context(self, **overrides) -> MonitorRunContext:
        """Build a MonitorRunContext with mocked collaborators."""
        defaults = {
            "monitor_id": 1,
            "db_dir": self.db_dir,
            "logger": MagicMock(),
            "log_config": {},
            "sqlite_handler": MagicMock(),
            "monitor": {"id": 1, "name": "test_monitor", "monitor_type": "scheduled"},
            "profiles": [{"id": 1, "name": "p1"}],
            "monitor_handler": MagicMock(),
        }
        defaults.update(overrides)
        return MonitorRunContext(**defaults)

    def test_parse_args_defaults(self):
        args = parse_args(["--monitor-id", "7"])

        self.assertEqual(args.monitor_id, 7)
        self.assertEqual(args.db_dir, "data")
        self.assertEqual(args.log, "conf/log.yaml")
        self.assertIsNone(args.log_level)

    def test_parse_args_requires_monitor_id(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            parse_args([])

        self.assertEqual(cm.exception.code, 2)

    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_get_monitor_context_missing_monitor_returns_none(
        self, mock_setup_logging, mock_sqlite_cls
    ):
        mock_setup_logging.return_value = (MagicMock(), {})
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = None
        mock_sqlite_cls.return_value = mock_sqlite

        context = MonitorRunContext.get_monitor_context(
            parse_args(["--monitor-id", "999", "--db-dir", self.db_dir])
        )

        self.assertIsNone(context)
        mock_sqlite.close.assert_called_once()

    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_get_monitor_context_missing_profiles_returns_none(
        self, mock_setup_logging, mock_sqlite_cls
    ):
        mock_setup_logging.return_value = (MagicMock(), {})
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = {"id": 1, "name": "test_monitor"}
        mock_sqlite.get_profiles_for_monitor.return_value = []
        mock_sqlite_cls.return_value = mock_sqlite

        context = MonitorRunContext.get_monitor_context(
            parse_args(["--monitor-id", "1", "--db-dir", self.db_dir])
        )

        self.assertIsNone(context)
        mock_sqlite.close.assert_called_once()

    @patch("app.monitor.run_monitor.MonitorHandlerFactory")
    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    def test_get_monitor_context_returns_context(
        self, mock_setup_logging, mock_sqlite_cls, mock_factory
    ):
        mock_setup_logging.return_value = (MagicMock(), {"version": 1})
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = {
            "id": 1,
            "name": "test_monitor",
            "monitor_type": "scheduled",
            "pid": 0,
        }
        mock_sqlite.get_profiles_for_monitor.return_value = [{"id": 1, "name": "p1"}]
        mock_sqlite_cls.return_value = mock_sqlite
        mock_handler = MagicMock()
        mock_factory.create.return_value = mock_handler

        context = MonitorRunContext.get_monitor_context(
            parse_args(["--monitor-id", "1", "--db-dir", self.db_dir])
        )

        self.assertIsInstance(context, MonitorRunContext)
        self.assertEqual(context.monitor_id, 1)
        self.assertEqual(context.db_dir, self.db_dir)
        self.assertIs(context.sqlite_handler, mock_sqlite)
        self.assertIs(context.monitor_handler, mock_handler)
        self.assertIsNotNone(context.stop_event)
        mock_sqlite.update_monitor_status.assert_called_with(monitor_id=1, status="running")
        mock_sqlite.update_monitor_pid.assert_called_with(monitor_id=1, pid=os.getpid())
        mock_sqlite.update_monitor_last_run.assert_called_once()
        mock_sqlite.update_monitor_last_heartbeat.assert_called_once()
        mock_factory.create.assert_called_once()

    @patch("app.monitor.run_monitor.MonitorHandlerFactory")
    @patch("app.monitor.run_monitor.SQLiteHandler")
    @patch("app.monitor.run_monitor.setup_logging")
    @patch("app.monitor.run_monitor.is_process_alive")
    def test_get_monitor_context_refuses_when_pid_alive(
        self, mock_is_alive, mock_setup_logging, mock_sqlite_cls, mock_factory
    ):
        """Phase-level single-instance guard: no handler is created."""
        mock_setup_logging.return_value = (MagicMock(), {})
        mock_is_alive.return_value = True
        mock_sqlite = MagicMock()
        mock_sqlite.get_monitor.return_value = {
            "id": 1,
            "name": "test_monitor",
            "monitor_type": "instant",
            "status": "stop",
            "pid": os.getpid() + 12345,
        }
        mock_sqlite.get_profiles_for_monitor.return_value = [{"id": 1, "name": "p1"}]
        mock_sqlite_cls.return_value = mock_sqlite

        context = MonitorRunContext.get_monitor_context(
            parse_args(["--monitor-id", "1", "--db-dir", self.db_dir])
        )

        self.assertIsNone(context)
        mock_factory.create.assert_not_called()
        mock_sqlite.update_monitor_status.assert_not_called()
        mock_sqlite.close.assert_called_once()

    def test_run_until_shutdown_start_failure_returns_none(self):
        mock_sqlite = MagicMock()
        mock_handler = MagicMock()
        mock_handler.start.return_value = False
        context = self._make_context(
            sqlite_handler=mock_sqlite, monitor_handler=mock_handler
        )

        reason = context.run_until_shutdown()

        self.assertIsNone(reason)
        mock_handler.stop.assert_not_called()
        mock_sqlite.update_monitor_status.assert_called_with(monitor_id=1, status="stopped")
        mock_sqlite.update_monitor_pid.assert_called_with(monitor_id=1, pid=0)
        mock_sqlite.close.assert_called_once()

    def test_run_until_shutdown_returns_reason(self):
        mock_handler = MagicMock()

        def fake_start(on_complete=None):
            def complete_worker():
                time.sleep(0.05)
                if on_complete:
                    on_complete("one-off task finished")

            threading.Thread(target=complete_worker).start()
            return True

        mock_handler.start.side_effect = fake_start
        context = self._make_context(monitor_handler=mock_handler)

        reason = context.run_until_shutdown()

        self.assertEqual(reason, "one-off task finished")
        # Clean up the poller thread started by run_until_shutdown.
        context.teardown(reason)

    def test_teardown_marks_stopped_and_closes(self):
        mock_sqlite = MagicMock()
        mock_handler = MagicMock()
        mock_poller = MagicMock()
        mock_poller.is_alive.return_value = True
        context = self._make_context(
            sqlite_handler=mock_sqlite,
            monitor_handler=mock_handler,
            poller_thread=mock_poller,
        )

        context.teardown("unit-test reason")

        self.assertTrue(context.stop_event.is_set())
        mock_handler.stop.assert_called_once()
        mock_poller.join.assert_called_once()
        mock_sqlite.update_monitor_status.assert_called_with(monitor_id=1, status="stopped")
        mock_sqlite.update_monitor_pid.assert_called_with(monitor_id=1, pid=0)
        mock_sqlite.close.assert_called_once()

    def test_teardown_without_poller_thread(self):
        mock_sqlite = MagicMock()
        context = self._make_context(sqlite_handler=mock_sqlite, poller_thread=None)

        context.teardown("no poller")

        mock_sqlite.update_monitor_status.assert_called_with(monitor_id=1, status="stopped")
        mock_sqlite.close.assert_called_once()

    def test_run_returns_zero_on_clean_shutdown(self):
        mock_sqlite = MagicMock()
        mock_handler = MagicMock()

        def fake_start(on_complete=None):
            on_complete("one-off task finished")
            return True

        mock_handler.start.side_effect = fake_start
        context = self._make_context(
            sqlite_handler=mock_sqlite, monitor_handler=mock_handler
        )

        exit_code = context.run()

        self.assertEqual(exit_code, 0)
        mock_handler.stop.assert_called_once()
        mock_sqlite.update_monitor_status.assert_called_with(monitor_id=1, status="stopped")
        mock_sqlite.update_monitor_pid.assert_called_with(monitor_id=1, pid=0)
        mock_sqlite.close.assert_called_once()

    def test_run_returns_one_when_start_fails(self):
        mock_sqlite = MagicMock()
        mock_handler = MagicMock()
        mock_handler.start.return_value = False
        context = self._make_context(
            sqlite_handler=mock_sqlite, monitor_handler=mock_handler
        )

        exit_code = context.run()

        self.assertEqual(exit_code, 1)
        mock_handler.stop.assert_not_called()
        mock_sqlite.close.assert_called_once()


    def test_run_monitor_main_reports_database_error_from_context(self):
        """A database error is reported cleanly instead of tracebacking."""
        with patch.object(
            MonitorRunContext,
            "get_monitor_context",
            side_effect=sqlite3.Error("no such table: monitors"),
        ), contextlib.redirect_stderr(io.StringIO()):
            exit_code = run_monitor_main(["--monitor-id", "1", "--db-dir", self.db_dir])

        self.assertEqual(exit_code, 1)

    def test_run_monitor_main_reports_database_error_from_run(self):
        """A database error raised while running is reported, not propagated."""
        mock_context = MagicMock()
        mock_context.monitor_id = 1
        mock_context.run.side_effect = sqlite3.Error("database is locked")

        with patch.object(
            MonitorRunContext, "get_monitor_context", return_value=mock_context
        ), contextlib.redirect_stderr(io.StringIO()):
            exit_code = run_monitor_main(["--monitor-id", "1", "--db-dir", self.db_dir])

        self.assertEqual(exit_code, 1)

    def test_teardown_closes_the_connection_when_a_write_fails(self):
        """teardown releases the database even when recording 'stopped' fails."""
        mock_sqlite = MagicMock()
        mock_sqlite.update_monitor_status.side_effect = sqlite3.Error("database is locked")
        context = self._make_context(sqlite_handler=mock_sqlite)

        with self.assertRaises(sqlite3.Error):
            context.teardown("unit-test reason")

        mock_sqlite.close.assert_called_once()

