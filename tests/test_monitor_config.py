"""Unit tests for app.utils.monitor_config."""

import unittest

from app.utils.monitor_config import (
    build_monitor_config,
    normalize_interval,
    parse_exclude_patterns,
)


class TestNormalizeInterval(unittest.TestCase):
    def test_bare_number_gets_minute_suffix(self):
        self.assertEqual(normalize_interval("10"), "10m")

    def test_unit_suffix_is_kept(self):
        self.assertEqual(normalize_interval("10m"), "10m")
        self.assertEqual(normalize_interval("2h"), "2h")
        self.assertEqual(normalize_interval("1d"), "1d")

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(normalize_interval(" 10 "), "10m")


class TestParseExcludePatterns(unittest.TestCase):
    def test_comma_separated_patterns_are_split_and_trimmed(self):
        self.assertEqual(
            parse_exclude_patterns("*.tmp, *.log, cache"),
            ["*.tmp", "*.log", "cache"],
        )

    def test_empty_input_yields_empty_list(self):
        self.assertEqual(parse_exclude_patterns(""), [])

    def test_empty_segments_are_dropped(self):
        self.assertEqual(parse_exclude_patterns("a, , b"), ["a", "b"])


class TestBuildMonitorConfig(unittest.TestCase):
    def test_backup_includes_normalized_interval_and_patterns(self):
        self.assertEqual(
            build_monitor_config("backup", "10", "*.tmp"),
            {"interval": "10m", "exclude_patterns": ["*.tmp"]},
        )

    def test_restore_includes_normalized_interval_and_patterns(self):
        self.assertEqual(
            build_monitor_config("restore", "2h", ""),
            {"interval": "2h", "exclude_patterns": []},
        )

    def test_instant_excludes_interval(self):
        self.assertEqual(
            build_monitor_config("instant", "10", "*.tmp"),
            {"exclude_patterns": ["*.tmp"]},
        )

    def test_unknown_type_yields_empty_config(self):
        self.assertEqual(build_monitor_config("unknown", "10", "*.tmp"), {})


if __name__ == "__main__":
    unittest.main()
