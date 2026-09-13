import os
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

from app.monitor.run_monitor import main, run_monitor_main

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
