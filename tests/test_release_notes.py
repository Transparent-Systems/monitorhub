"""Unit tests for the release-notes extractor (utils/release_notes.py).

The script feeds the ``body_path`` of the GitHub Release step, so a regression
here publishes the wrong text (or nothing) on every tagged build. All tests are
offline and file-based.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from utils.release_notes import (
    EXIT_NO_SECTION,
    EXIT_OK,
    EXIT_VERSION_MISMATCH,
    ReleaseNotesError,
    ReleaseSection,
    extract_section,
    main,
    normalize_version,
    parse_heading,
    read_version,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

CHANGELOG = """\
# Changelog

## [Unreleased]

Nothing yet.

## [1.2.0] - 2026-10-26

This release is about packaging and documentation.

### GUI and CLI binaries

- The GUI binary is now called `mhub-gui`.

---

## [1.1.0] - 2026-10-22

This release introduced the web GUI.

---

## [1.0.0] - 2026-10-10

Initial release.
"""


class TestNormalizeVersion(unittest.TestCase):
    def test_strips_a_leading_v(self):
        self.assertEqual(normalize_version("v1.2.0"), "1.2.0")

    def test_strips_a_leading_capital_v(self):
        self.assertEqual(normalize_version("V1.2.0"), "1.2.0")

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(normalize_version("  1.2.0\n"), "1.2.0")

    def test_leaves_a_plain_version_alone(self):
        self.assertEqual(normalize_version("1.2.0"), "1.2.0")


class TestParseHeading(unittest.TestCase):
    def test_bracketed_heading_with_a_date(self):
        self.assertEqual(parse_heading("[1.2.0] - 2026-10-26"), ("1.2.0", "2026-10-26"))

    def test_bracketed_heading_with_a_v_prefix(self):
        self.assertEqual(parse_heading("[v1.2.0] - 2026-10-26"), ("v1.2.0", "2026-10-26"))

    def test_bare_heading_without_brackets(self):
        self.assertEqual(parse_heading("1.2.0"), ("1.2.0", None))

    def test_bare_heading_with_a_v_prefix(self):
        self.assertEqual(parse_heading("v1.2.0"), ("v1.2.0", None))

    def test_unreleased_is_not_a_version(self):
        self.assertIsNone(parse_heading("Unreleased"))

    def test_bracketed_unreleased_is_not_a_version(self):
        self.assertIsNone(parse_heading("[Unreleased]"))

    def test_a_free_text_heading_is_not_a_version(self):
        self.assertIsNone(parse_heading("Acknowledgements"))


class TestExtractSection(unittest.TestCase):
    def test_returns_the_matching_section(self):
        section = extract_section(CHANGELOG, "1.2.0")

        self.assertIsInstance(section, ReleaseSection)
        self.assertEqual(section.version, "1.2.0")
        self.assertEqual(section.date, "2026-10-26")
        self.assertIn("This release is about packaging and documentation.", section.body)

    def test_the_body_excludes_the_heading(self):
        section = extract_section(CHANGELOG, "1.2.0")

        self.assertNotIn("## [1.2.0]", section.body)
        self.assertFalse(section.body.startswith("#"))

    def test_stops_at_the_next_release(self):
        section = extract_section(CHANGELOG, "1.2.0")

        self.assertNotIn("web GUI", section.body)
        self.assertNotIn("1.1.0", section.body)

    def test_keeps_level_three_subsections_in_the_body(self):
        section = extract_section(CHANGELOG, "1.2.0")

        self.assertIn("### GUI and CLI binaries", section.body)

    def test_drops_the_trailing_horizontal_rule(self):
        section = extract_section(CHANGELOG, "1.2.0")

        self.assertNotIn("---", section.body)
        self.assertFalse(section.body.endswith("\n"))

    def test_matches_a_bracketed_heading_when_asked_for_a_bare_version(self):
        section = extract_section(CHANGELOG, "1.1.0")

        self.assertIn("web GUI", section.body)

    def test_matches_across_a_v_prefix(self):
        section = extract_section(CHANGELOG, "v1.1.0")

        self.assertEqual(section.version, "1.1.0")

    def test_extracts_the_last_section_in_the_file(self):
        section = extract_section(CHANGELOG, "1.0.0")

        self.assertIn("Initial release.", section.body)

    def test_unreleased_is_not_matched_as_a_version(self):
        # "Unreleased" is not a version, so asking for it must fail rather than
        # silently returning the wrong section.
        with self.assertRaises(ReleaseNotesError):
            extract_section(CHANGELOG, "Unreleased")

    def test_unknown_version_raises_and_lists_what_exists(self):
        with self.assertRaises(ReleaseNotesError) as raised:
            extract_section(CHANGELOG, "9.9.9")

        message = str(raised.exception)
        self.assertIn("9.9.9", message)
        self.assertIn("1.2.0", message)

    def test_an_empty_section_raises(self):
        text = "## [2.0.0] - 2026-01-01\n\n## [1.0.0] - 2025-01-01\n\nBody.\n"

        with self.assertRaises(ReleaseNotesError) as raised:
            extract_section(text, "2.0.0")

        self.assertIn("empty", str(raised.exception))


class TestReadVersion(unittest.TestCase):
    def test_reads_the_real_version_file(self):
        version = read_version(REPO_ROOT / "version.py")

        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_reads_version_string_from_a_temporary_module(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            version_file = Path(tmp_dir) / "version.py"
            version_file.write_text(
                'VERSION_STRING = "9.8.7"\n', encoding="utf-8"
            )

            self.assertEqual(read_version(version_file), "9.8.7")

    def test_a_missing_version_string_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            version_file = Path(tmp_dir) / "version.py"
            version_file.write_text("VERSION_MAJOR = 1\n", encoding="utf-8")

            with self.assertRaises(ReleaseNotesError) as raised:
                read_version(version_file)

            self.assertIn("VERSION_STRING", str(raised.exception))

    def test_a_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ReleaseNotesError):
                read_version(Path(tmp_dir) / "nope.py")


class TestMain(unittest.TestCase):
    """The workflow calls main() indirectly through the script."""

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def _version_file(self, tmp_dir: str, version: str = "1.2.0") -> str:
        path = Path(tmp_dir) / "version.py"
        path.write_text(f'VERSION_STRING = "{version}"\n', encoding="utf-8")
        return str(path)

    def _changelog_file(self, tmp_dir: str, text: str = CHANGELOG) -> str:
        path = Path(tmp_dir) / "CHANGELOG.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_writes_the_body_to_the_output_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # A nested path: the script must create the parent directory.
            output = Path(tmp_dir) / "dist" / "release_notes.md"
            code, _, _ = self._run(
                [
                    "--version-file",
                    self._version_file(tmp_dir),
                    "--changelog",
                    self._changelog_file(tmp_dir),
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(code, EXIT_OK)
            self.assertTrue(output.is_file())
            text = output.read_text(encoding="utf-8")
            self.assertIn("packaging and documentation", text)
            self.assertTrue(text.endswith("\n"))

    def test_prints_to_stdout_without_an_output_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            code, out, _ = self._run(
                [
                    "--version-file",
                    self._version_file(tmp_dir),
                    "--changelog",
                    self._changelog_file(tmp_dir),
                ]
            )

            self.assertEqual(code, EXIT_OK)
            self.assertIn("packaging and documentation", out)

    def test_a_matching_tag_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            code, _, _ = self._run(
                [
                    "--version-file",
                    self._version_file(tmp_dir),
                    "--changelog",
                    self._changelog_file(tmp_dir),
                    "--tag",
                    "v1.2.0",
                ]
            )

            self.assertEqual(code, EXIT_OK)

    def test_a_mismatched_tag_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            code, _, err = self._run(
                [
                    "--version-file",
                    self._version_file(tmp_dir),
                    "--changelog",
                    self._changelog_file(tmp_dir),
                    "--tag",
                    "v9.9.9",
                ]
            )

            self.assertEqual(code, EXIT_VERSION_MISMATCH)
            self.assertIn("v9.9.9", err)

    def test_a_version_missing_from_the_changelog_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            code, _, err = self._run(
                [
                    "--version-file",
                    self._version_file(tmp_dir, "3.0.0"),
                    "--changelog",
                    self._changelog_file(tmp_dir),
                ]
            )

            self.assertEqual(code, EXIT_NO_SECTION)
            self.assertIn("3.0.0", err)

    def test_an_unreadable_changelog_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            code, _, err = self._run(
                [
                    "--version-file",
                    self._version_file(tmp_dir),
                    "--changelog",
                    str(Path(tmp_dir) / "nope.md"),
                ]
            )

            self.assertEqual(code, EXIT_NO_SECTION)
            self.assertIn("cannot read", err)


class TestRealChangelog(unittest.TestCase):
    """Guards the two invariants the release workflows rely on."""

    def setUp(self):
        self.version = read_version(REPO_ROOT / "version.py")
        self.changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_the_changelog_documents_the_current_version(self):
        section = extract_section(self.changelog, self.version)

        self.assertEqual(normalize_version(section.version), self.version)
        self.assertTrue(section.body.strip())

    def test_the_current_section_has_no_stray_headings(self):
        section = extract_section(self.changelog, self.version)

        self.assertNotIn("## [", section.body)


if __name__ == "__main__":
    unittest.main()

