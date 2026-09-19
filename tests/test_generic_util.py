"""
Unit tests for app.utils.generic_util.
"""

import datetime
import os
import subprocess
import sys
import time
import unittest

from app.utils.constants import TIMESTAMP_FORMAT
from app.utils.generic_util import (
    BoundedLRUDict,
    convert_to_seconds,
    find_by_id,
    is_interval_valid,
    is_process_alive,
    parse_timestamp,
    utc_timestamp_now,
)


class TestBoundedLRUDict(unittest.TestCase):
    """Tests for BoundedLRUDict data structure."""

    def test_maxsize_validation(self):
        with self.assertRaises(ValueError):
            BoundedLRUDict(maxsize=0)

    def test_lru_eviction(self):
        d = BoundedLRUDict(maxsize=3)
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        self.assertEqual(list(d.keys()), ["a", "b", "c"])

        # Adding a 4th key evicts the oldest ("a")
        d["d"] = 4
        self.assertEqual(list(d.keys()), ["b", "c", "d"])

        # Accessing/updating "b" moves it to end (most recently used)
        d["b"] = 20
        self.assertEqual(list(d.keys()), ["c", "d", "b"])

        # Adding "e" should now evict "c", not "b"
        d["e"] = 5
        self.assertEqual(list(d.keys()), ["d", "b", "e"])


class TestGenericUtilFunctions(unittest.TestCase):
    """Tests for convert_to_seconds and find_by_id."""

    def test_convert_to_seconds(self):
        self.assertEqual(convert_to_seconds(None), 0)
        self.assertEqual(convert_to_seconds(120), 120)
        self.assertEqual(convert_to_seconds(""), 0)
        self.assertEqual(convert_to_seconds("45"), 45)
        self.assertEqual(convert_to_seconds("30s"), 30)
        self.assertEqual(convert_to_seconds("2m"), 120)
        self.assertEqual(convert_to_seconds("1h"), 3600)
        self.assertEqual(convert_to_seconds("1d"), 86400)
        self.assertEqual(convert_to_seconds("unknown"), 0)

    def test_convert_to_seconds_float_and_fractional(self):
        """Float inputs and fractional strings stay seconds instead of collapsing to 0."""
        # Regression: convert_to_seconds(60.0) previously returned 0, which
        # made ActionHandlerFactory's default command timeout kill every
        # command instantly via subprocess.run(timeout=0).
        self.assertEqual(convert_to_seconds(60.0), 60)
        self.assertEqual(convert_to_seconds(0.5), 0.5)
        self.assertEqual(convert_to_seconds("0.5s"), 0.5)
        self.assertEqual(convert_to_seconds("1.5m"), 90)
        self.assertEqual(convert_to_seconds("1.5h"), 5400)
        self.assertEqual(convert_to_seconds("12.5"), 12.5)

    def test_convert_to_seconds_rejects_invalid_values(self):
        self.assertEqual(convert_to_seconds(-5), 0)
        self.assertEqual(convert_to_seconds(-5.0), 0)
        self.assertEqual(convert_to_seconds(True), 0)
        self.assertEqual(convert_to_seconds("  "), 0)
        self.assertEqual(convert_to_seconds("10x"), 0)
        self.assertEqual(convert_to_seconds("s"), 0)
        self.assertEqual(convert_to_seconds("0.5x"), 0)

    def test_find_by_id(self):
        items = [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]
        self.assertEqual(find_by_id(items, 1), items[0])
        self.assertEqual(find_by_id(items, 2), items[1])
        self.assertIsNone(find_by_id(items, 99))
        self.assertIsNone(find_by_id([], 1))

    def test_is_interval_valid(self):
        # Valid non-negative intervals (zero, plain digits, or digits with s/m/h/d)
        self.assertTrue(is_interval_valid("0"))
        self.assertTrue(is_interval_valid("0s"))
        self.assertTrue(is_interval_valid("0m"))
        self.assertTrue(is_interval_valid("0h"))
        self.assertTrue(is_interval_valid("0d"))
        self.assertTrue(is_interval_valid("10"))
        self.assertTrue(is_interval_valid("15s"))
        self.assertTrue(is_interval_valid("5m"))
        self.assertTrue(is_interval_valid("2h"))
        self.assertTrue(is_interval_valid("1d"))
        self.assertTrue(is_interval_valid(" 10m "))
        self.assertTrue(is_interval_valid("10M"))
        self.assertTrue(is_interval_valid("00"))

        # Invalid negative intervals
        self.assertFalse(is_interval_valid("-1"))
        self.assertFalse(is_interval_valid("-10s"))
        self.assertFalse(is_interval_valid("-5m"))
        self.assertFalse(is_interval_valid("-0"))

        # Invalid strings and types
        self.assertFalse(is_interval_valid(""))
        self.assertFalse(is_interval_valid("   "))
        self.assertFalse(is_interval_valid("abc"))
        self.assertFalse(is_interval_valid("10x"))
        self.assertFalse(is_interval_valid("1.5h"))
        self.assertFalse(is_interval_valid("s"))
        self.assertFalse(is_interval_valid(None))
        self.assertFalse(is_interval_valid(10))


    def test_utc_timestamp_now_roundtrips_through_parse_timestamp(self):
        """Writer and reader must agree on the shared timestamp format (A1)."""
        timestamp = utc_timestamp_now()
        parsed = parse_timestamp(timestamp)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, datetime.UTC)
        # A freshly produced timestamp is essentially "now".
        age = (datetime.datetime.now(datetime.UTC) - parsed).total_seconds()
        self.assertGreaterEqual(age, 0)
        self.assertLess(age, 5)

    def test_parse_timestamp_handles_invalid_input(self):
        self.assertIsNone(parse_timestamp(None))
        self.assertIsNone(parse_timestamp(""))
        self.assertIsNone(parse_timestamp("2026-01-01"))  # wrong format
        self.assertIsNone(parse_timestamp("not-a-timestamp"))

    def test_parse_timestamp_uses_shared_format(self):
        value = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
        self.assertEqual(parse_timestamp(value.strftime(TIMESTAMP_FORMAT)), value)

    def test_is_process_alive_current_process(self):
        self.assertTrue(is_process_alive(os.getpid()))

    def test_is_process_alive_invalid_pid(self):
        self.assertFalse(is_process_alive(None))
        self.assertFalse(is_process_alive(0))
        self.assertFalse(is_process_alive(-1))

    def test_is_process_alive_dead_process(self):
        # Spawn a short-lived child and reap it, so its PID no longer exists.
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(is_process_alive(child.pid))

    @unittest.skipUnless(
        sys.platform.startswith("linux"), "requires /proc to detect the process state"
    )
    def test_is_process_alive_zombie_child_is_not_alive(self):
        """A terminated child that has not been reaped must not count as alive.

        Such a child is a zombie: it still holds its PID, so os.kill(pid, 0)
        succeeds and a naive check would report it as running. The liveness check
        must detect the 'Z' state, otherwise a monitor that shut down gracefully
        looks like it needs a forceful stop.
        """
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        try:
            # Wait for the child to terminate WITHOUT reaping it (never call
            # wait/poll, which would release the PID).
            for _ in range(100):
                if self._proc_state(child.pid) == "Z":
                    break
                time.sleep(0.05)
            self.assertEqual(self._proc_state(child.pid), "Z")
            self.assertFalse(is_process_alive(child.pid))
        finally:
            child.wait()  # reap to avoid leaving a zombie behind

    @staticmethod
    def _proc_state(pid: int) -> str:
        """Return the Linux process state from /proc/<pid>/stat (e.g. 'Z')."""
        with open(f"/proc/{pid}/stat", "r") as stat_file:
            return stat_file.read().rsplit(")", 1)[1].split()[0]


if __name__ == "__main__":
    unittest.main()
