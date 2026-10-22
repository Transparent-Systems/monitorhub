"""Unit tests for app.utils.monitor_naming."""

import unittest

from app.utils.monitor_naming import clone_base_name, next_clone_name


class TestCloneBaseName(unittest.TestCase):
    def test_plain_name_unchanged(self):
        self.assertEqual(clone_base_name("photos"), "photos")

    def test_copy_suffix_stripped(self):
        self.assertEqual(clone_base_name("photos (copy)"), "photos")

    def test_numbered_copy_suffix_stripped(self):
        self.assertEqual(clone_base_name("photos (copy 2)"), "photos")
        self.assertEqual(clone_base_name("photos (copy 10)"), "photos")

    def test_copy_not_at_end_is_left_alone(self):
        self.assertEqual(clone_base_name("photos (copy) extra"), "photos (copy) extra")

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(clone_base_name("photos  (copy)"), "photos")


class TestNextCloneName(unittest.TestCase):
    def test_first_clone_has_copy_suffix(self):
        self.assertEqual(next_clone_name("photos", lambda n: False), "photos (copy)")

    def test_increments_past_existing_copies(self):
        existing = {"photos (copy)", "photos (copy 2)"}
        self.assertEqual(
            next_clone_name("photos", lambda n: n in existing), "photos (copy 3)"
        )

    def test_cloning_a_copy_increments(self):
        existing = {"photos (copy)"}
        self.assertEqual(
            next_clone_name("photos (copy)", lambda n: n in existing), "photos (copy 2)"
        )

    def test_cloning_a_numbered_copy_increments(self):
        existing = {"photos (copy)", "photos (copy 2)"}
        self.assertEqual(
            next_clone_name("photos (copy 2)", lambda n: n in existing), "photos (copy 3)"
        )


if __name__ == "__main__":
    unittest.main()
