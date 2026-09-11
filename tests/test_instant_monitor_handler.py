"""
Unit tests for MonitorEventHandler and InstantMonitorHandler.
"""

import unittest

from app.monitor.instant_monitor_handler import MonitorEventHandler
from app.utils.generic_util import BoundedLRUDict


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


if __name__ == "__main__":
    unittest.main()
