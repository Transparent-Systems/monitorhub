"""
Unit tests for app.utils.generic_util.
"""

import unittest

from app.utils.generic_util import BoundedLRUDict, convert_to_seconds, find_by_id


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


if __name__ == "__main__":
    unittest.main()
