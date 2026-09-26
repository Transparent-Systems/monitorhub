import subprocess
import sys
import unittest
from pathlib import Path

from app.utils.schema_versioning import (
    DATABASE_SCHEMA_VERSION,
    SCHEMA_MIGRATIONS,
    classify,
    compare_versions,
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

    def test_registry_baseline_is_first_and_supported_is_last(self):
        # The initial schema stays the first entry; the supported schema version
        # is always the newest (last) entry in the registry.
        self.assertEqual(SCHEMA_MIGRATIONS[0], ("1.0.0", "Initial schema", None))
        self.assertEqual(DATABASE_SCHEMA_VERSION, SCHEMA_MIGRATIONS[-1][0])

    def test_migrations_are_ordered_ascending(self):
        # ``apply_pending_migrations`` sorts defensively, but the registry is
        # still expected to be authored in ascending version order. Fail fast
        # here if a future entry is added out of sequence.
        self.assertEqual(
            SCHEMA_MIGRATIONS,
            sorted(SCHEMA_MIGRATIONS, key=lambda entry: parse_version(entry[0])),
        )


class TestSchemaVersioningLocation(unittest.TestCase):
    """The schema-version data must not live in the CLI package.

    ``app.utils.sqlite_handler`` depends on it, so keeping it under ``app.cli``
    would make the utility layer import the presentation layer.
    """

    def test_module_lives_in_app_utils(self):
        from app.utils import schema_versioning

        self.assertEqual(schema_versioning.__name__, "app.utils.schema_versioning")
        self.assertTrue(callable(getattr(schema_versioning, "classify", None)))

    def test_importing_sqlite_handler_does_not_import_app_cli(self):
        # Run in a fresh interpreter: unittest discovery may already have
        # imported app.cli for other tests, which would mask a regression.
        repo_root = Path(__file__).resolve().parents[1]
        code = (
            "import sys\n"
            "import app.utils.sqlite_handler\n"
            "cli = sorted(\n"
            "    m for m in sys.modules if m == 'app.cli' or m.startswith('app.cli.')\n"
            ")\n"
            "print(','.join(cli))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "", result.stdout)


if __name__ == "__main__":
    unittest.main()