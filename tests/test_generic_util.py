"""
Unit tests for app.utils.generic_util.
"""

import unittest

from app.utils.generic_util import (
    BoundedLRUDict,
    convert_to_seconds,
    find_by_id,
    is_interval_valid,
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


if __name__ == "__main__":
    unittest.main()
