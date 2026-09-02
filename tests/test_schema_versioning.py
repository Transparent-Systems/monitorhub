import unittest

from scripts.schema_versioning import (
    APP_VERSION_TO_DB_VERSION,
    LATEST_DB_SCHEMA_VERSION,
    SCHEMA_MIGRATIONS,
    classify,
    compare_versions,
    db_version_for_app,
    parse_version,
)


class TestSchemaVersioning(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("1.0.0"), (1, 0, 0))
        self.assertEqual(parse_version("10.2.3"), (10, 2, 3))
        self.assertEqual(parse_version("1"), (1,))

    def test_compare_versions_is_numeric_not_lexicographic(self):
        # Lexicographically "9" > "10", but numerically 9 < 10.
        self.assertLess(compare_versions("9.0.0", "10.0.0"), 0)
        self.assertGreater(compare_versions("10.0.0", "9.0.0"), 0)
        self.assertEqual(compare_versions("1.0.0", "1.0.0"), 0)

    def test_compare_versions_pads_missing_segments(self):
        self.assertEqual(compare_versions("1.0", "1.0.0"), 0)
        self.assertEqual(compare_versions("2", "2.0.0"), 0)

    def test_classify(self):
        self.assertEqual(classify("1.0.0", "1.0.0"), "ok")
        self.assertEqual(classify("0.9.0", "1.0.0"), "older")
        self.assertEqual(classify("2.0.0", "1.0.0"), "newer")
        self.assertEqual(classify("9.0.0", "10.0.0"), "older")
        self.assertEqual(classify("10.0.0", "9.0.0"), "newer")

    def test_db_version_for_app_inherits_latest_schema(self):
        self.assertEqual(db_version_for_app("1.0.0"), "1.0.0")
        # A release newer than the last schema bump still maps to the same schema.
        self.assertEqual(db_version_for_app("1.5.0"), "1.0.0")

    def test_registry_has_only_one_entry_per_schema_change(self):
        # The current codebase has a single schema change: the initial schema.
        self.assertEqual(len(APP_VERSION_TO_DB_VERSION), 1)
        self.assertEqual(SCHEMA_MIGRATIONS[0], ("1.0.0", "Initial schema", None))
        self.assertEqual(LATEST_DB_SCHEMA_VERSION, SCHEMA_MIGRATIONS[-1][0])


if __name__ == "__main__":
    unittest.main()