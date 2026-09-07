"""
Unit tests for StoppableWorker and DebounceManager.
"""

import logging
import threading
import time
import unittest

from app.monitor.action_handler import DebounceManager
from app.monitor.instant_monitor_handler import MonitorEventHandler
from app.monitor.worker import PeriodicWorker, StoppableWorker
from app.utils.generic_util import BoundedLRUDict


class DummyWorker(StoppableWorker):
    """Test implementation of StoppableWorker."""

    def __init__(self, run_count_limit: int = 5, wait_interval: float = 0.02):
        super().__init__(name="DummyWorker")
        self.run_count_limit = run_count_limit
        self.wait_interval = wait_interval
        self.iterations = 0

    def run(self):
        while not self.is_stopped and self.iterations < self.run_count_limit:
            if self.wait_stop(self.wait_interval):
                break
            self.iterations += 1


class TestStoppableWorker(unittest.TestCase):
    """Tests for StoppableWorker base class lifecycle."""

    def test_worker_lifecycle(self):
        worker = DummyWorker(run_count_limit=10, wait_interval=0.01)
        self.assertFalse(worker.is_running)
        self.assertFalse(worker.is_stopped)

        worker.start()
        self.assertTrue(worker.is_running)

        # Calling start again should be idempotent
        worker.start()
        self.assertTrue(worker.is_running)

        worker.stop()
        self.assertTrue(worker.is_stopped)
        self.assertFalse(worker.is_running)

        # Calling stop again should be idempotent
        worker.stop()
        self.assertTrue(worker.is_stopped)

    def test_worker_finishes_before_stop(self):
        worker = DummyWorker(run_count_limit=2, wait_interval=0.005)
        worker.start()
        time.sleep(0.05)
        # Thread should finish its iterations naturally
        self.assertFalse(worker.is_running)
        self.assertEqual(worker.iterations, 2)
        worker.stop()

    def test_periodic_worker(self):
        count = 0

        def increment():
            nonlocal count
            count += 1

        worker = PeriodicWorker(
            interval=0.02,
            action=increment,
            name="TestPeriodic",
            initial_delay=False,
        )
        worker.start()
        # initial_delay=False means action runs once immediately
        time.sleep(0.05)
        worker.stop()
        self.assertGreaterEqual(count, 2)
        self.assertFalse(worker.is_running)


class TestMonitorEventHandlerBoundedHistory(unittest.TestCase):
    """Tests for MonitorEventHandler bounded event_time cache without background thread."""

    def test_bounded_history_eviction(self):
        class DummyDispatcher:
            def queue_action(self, context):
                pass

        class DummyEvent:
            def __init__(self, path):
                self.src_path = path
                self.is_directory = False
                self.event_type = "modified"

        handler = MonitorEventHandler(
            action_dispatcher=DummyDispatcher(),
            monitor_config={"config": {}},
        )
        # Set a small limit for testing eviction
        handler.event_time = BoundedLRUDict(maxsize=3)

        try:
            handler.on_modified(DummyEvent("/path/1.txt"))
            handler.on_modified(DummyEvent("/path/2.txt"))
            handler.on_modified(DummyEvent("/path/3.txt"))

            with handler.event_time_lock:
                self.assertEqual(len(handler.event_time), 3)
                self.assertIn("/path/1.txt", handler.event_time)

            # Adding a 4th should evict the oldest (/path/1.txt)
            handler.on_modified(DummyEvent("/path/4.txt"))
            with handler.event_time_lock:
                self.assertEqual(len(handler.event_time), 3)
                self.assertNotIn("/path/1.txt", handler.event_time)
                self.assertIn("/path/2.txt", handler.event_time)
                self.assertIn("/path/3.txt", handler.event_time)
                self.assertIn("/path/4.txt", handler.event_time)

            # Re-modifying /path/2.txt updates it and makes it most recent
            handler.on_modified(DummyEvent("/path/2.txt"))
            # Adding /path/5.txt should now evict /path/3.txt, not /path/2.txt
            handler.on_modified(DummyEvent("/path/5.txt"))
            with handler.event_time_lock:
                self.assertEqual(len(handler.event_time), 3)
                self.assertNotIn("/path/3.txt", handler.event_time)
                self.assertIn("/path/2.txt", handler.event_time)
                self.assertIn("/path/4.txt", handler.event_time)
                self.assertIn("/path/5.txt", handler.event_time)
        finally:
            handler.stop()



class TestDebounceManager(unittest.TestCase):
    """Tests for DebounceManager thread safety and debounce functionality."""

    def setUp(self):
        self.logger = logging.getLogger("TestDebounceManager")
        self.calls = []
        self.lock = threading.Lock()

    def callback(self, path: str):
        with self.lock:
            self.calls.append((path, time.time()))

    def test_debounce_single_event(self):
        delay = 0.05
        dm = DebounceManager(self.callback, self.logger, delay=delay)
        dm.start()

        try:
            start_time = time.time()
            dm.add_event("/path/file1.txt")

            # Wait slightly longer than the debounce delay
            time.sleep(delay + 0.05)

            with self.lock:
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.calls[0][0], "/path/file1.txt")
                elapsed = self.calls[0][1] - start_time
                self.assertGreaterEqual(elapsed, delay)
        finally:
            dm.stop()

    def test_debounce_resets_deadline_on_rapid_events(self):
        delay = 0.08
        dm = DebounceManager(self.callback, self.logger, delay=delay)
        dm.start()

        try:
            # Emit multiple events for the same file in quick succession
            for _ in range(3):
                dm.add_event("/path/file_rapid.txt")
                time.sleep(0.02)

            last_added = time.time()
            # Wait for expiration
            time.sleep(delay + 0.05)

            with self.lock:
                # Should only trigger once
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.calls[0][0], "/path/file_rapid.txt")
                elapsed = self.calls[0][1] - last_added
                # The callback should have fired after the final event's deadline
                self.assertGreaterEqual(elapsed, delay - 0.03)
        finally:
            dm.stop()

    def test_debounce_multiple_files_staggered(self):
        delay = 0.06
        dm = DebounceManager(self.callback, self.logger, delay=delay)
        dm.start()

        try:
            dm.add_event("/path/file_a.txt")
            time.sleep(0.04)
            dm.add_event("/path/file_b.txt")

            time.sleep(delay + 0.06)

            with self.lock:
                self.assertEqual(len(self.calls), 2)
                called_paths = [c[0] for c in self.calls]
                self.assertIn("/path/file_a.txt", called_paths)
                self.assertIn("/path/file_b.txt", called_paths)
                # file_a should trigger before file_b
                self.assertEqual(called_paths[0], "/path/file_a.txt")
                self.assertEqual(called_paths[1], "/path/file_b.txt")
        finally:
            dm.stop()

    def test_debounce_cancel_event(self):
        delay = 0.08
        dm = DebounceManager(self.callback, self.logger, delay=delay)
        dm.start()

        try:
            dm.add_event("/path/file_cancelled.txt")
            dm.add_event("/path/file_kept.txt")

            # Cancel one of the events before delay expires
            time.sleep(0.02)
            dm.cancel_event("/path/file_cancelled.txt")

            time.sleep(delay + 0.04)

            with self.lock:
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.calls[0][0], "/path/file_kept.txt")
        finally:
            dm.stop()

    def test_stop_unblocks_immediately_with_pending_events(self):
        delay = 10.0  # long delay
        dm = DebounceManager(self.callback, self.logger, delay=delay)
        dm.start()

        dm.add_event("/path/long_delay.txt")
        stop_start = time.time()
        dm.stop()
        stop_duration = time.time() - stop_start

        # Stop should not wait for the 10s delay; it should complete quickly (well under 1s)
        self.assertLess(stop_duration, 1.0)
        self.assertFalse(dm.is_running)
        with self.lock:
            self.assertEqual(len(self.calls), 0)


if __name__ == "__main__":
    unittest.main()
