"""
Unit tests for ScheduledMonitorHandler using PeriodicWorker and _OneOffWorker.
"""

import time
import unittest
from unittest.mock import patch

from app.monitor.scheduled_monitor_handler import ScheduledMonitorHandler, _OneOffWorker
from app.monitor.worker import PeriodicWorker
from app.utils.constants import MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE


class TestScheduledMonitorHandler(unittest.TestCase):
    """Test suite for ScheduledMonitorHandler lifecycle and worker integration."""

    def setUp(self):
        self.mock_monitor = {
            "name": "test_backup",
            "monitor_path": "/tmp/source",
            "remote_path": "remote:dest",
            "config": {
                "interval": "10s",
                "exclude_patterns": [],
            },
        }
        self.mock_profiles = []
        self.mock_log_config = {}

    def test_init_invalid_direction(self):
        with self.assertRaises(ValueError):
            ScheduledMonitorHandler(
                monitor=self.mock_monitor,
                profiles=self.mock_profiles,
                log_config=self.mock_log_config,
                direction="invalid_direction",
            )

    def test_start_creates_periodic_worker_when_interval_positive(self):
        handler = ScheduledMonitorHandler(
            monitor=self.mock_monitor,
            profiles=self.mock_profiles,
            log_config=self.mock_log_config,
            direction=MONITOR_TYPE_BACKUP,
        )

        with patch.object(handler, "_perform_operation") as mock_op:
            started = handler.start()
            self.assertTrue(started)
            self.assertIsInstance(handler.worker, PeriodicWorker)
            self.assertEqual(handler.worker.interval, 10.0)
            self.assertTrue(handler.worker.is_running)

            # initial_delay=False means action was executed upon starting
            time.sleep(0.05)
            self.assertGreaterEqual(mock_op.call_count, 1)

            handler.stop()
            self.assertFalse(handler.worker.is_running if handler.worker else False)
            self.assertIsNone(handler.worker)

    def test_start_creates_oneoff_worker_when_interval_zero(self):
        monitor = dict(self.mock_monitor)
        monitor["config"] = {"interval": "0"}

        handler = ScheduledMonitorHandler(
            monitor=monitor,
            profiles=self.mock_profiles,
            log_config=self.mock_log_config,
            direction=MONITOR_TYPE_BACKUP,
        )

        with patch.object(handler, "_perform_operation") as mock_op:
            started = handler.start()
            self.assertTrue(started)
            self.assertIsInstance(handler.worker, _OneOffWorker)

            # Wait for one-off worker to finish
            time.sleep(0.05)
            mock_op.assert_called_once_with(reason="one-off (interval 0)")

            handler.stop()
            self.assertIsNone(handler.worker)

    def test_start_when_config_empty(self):
        monitor = dict(self.mock_monitor)
        monitor["config"] = {}

        handler = ScheduledMonitorHandler(
            monitor=monitor,
            profiles=self.mock_profiles,
            log_config=self.mock_log_config,
            direction=MONITOR_TYPE_BACKUP,
        )

        with patch.object(handler, "_perform_operation") as mock_op:
            started = handler.start()
            self.assertTrue(started)
            self.assertIsNone(handler.worker)
            mock_op.assert_not_called()

            handler.stop()
            self.assertIsNone(handler.worker)

    def test_start_invokes_on_complete_callback_when_interval_zero(self):
        monitor = dict(self.mock_monitor)
        monitor["config"] = {"interval": "0"}

        handler = ScheduledMonitorHandler(
            monitor=monitor,
            profiles=self.mock_profiles,
            log_config=self.mock_log_config,
            direction=MONITOR_TYPE_BACKUP,
        )

        completed_reason = []

        def on_complete(reason):
            completed_reason.append(reason)

        with patch.object(handler, "_perform_operation") as mock_op:
            started = handler.start(on_complete=on_complete)
            self.assertTrue(started)

            time.sleep(0.05)
            mock_op.assert_called_once_with(reason="one-off (interval 0)")
            self.assertEqual(completed_reason, ["one-off task finished"])

            handler.stop()

    def test_start_does_not_invoke_on_complete_when_interval_positive(self):
        handler = ScheduledMonitorHandler(
            monitor=self.mock_monitor,
            profiles=self.mock_profiles,
            log_config=self.mock_log_config,
            direction=MONITOR_TYPE_BACKUP,
        )

        completed_reason = []

        def on_complete(reason):
            completed_reason.append(reason)

        with patch.object(handler, "_perform_operation"):
            started = handler.start(on_complete=on_complete)
            self.assertTrue(started)

            time.sleep(0.05)
            self.assertEqual(completed_reason, [])

            handler.stop()
            self.assertEqual(completed_reason, [])

    def test_stop_idempotent_when_not_started(self):
        handler = ScheduledMonitorHandler(
            monitor=self.mock_monitor,
            profiles=self.mock_profiles,
            log_config=self.mock_log_config,
            direction=MONITOR_TYPE_RESTORE,
        )
        # Should not raise exception
        handler.stop()
        self.assertIsNone(handler.worker)


if __name__ == "__main__":
    unittest.main()
