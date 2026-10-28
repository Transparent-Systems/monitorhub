"""
Script: release_notes.py
Description:
    Extract one version's section from CHANGELOG.md and write it out as the
    body of a GitHub Release.

    The release workflows used to create a release with an empty body, so the
    notes had to be pasted by hand afterwards (docs/release-checklist.md). This
    script closes that gap: it reads the version from version.py, finds the
    matching ``## [<version>] - <date>`` section in CHANGELOG.md, and writes the
    text to a file that the release step consumes via ``body_path``.

    The section ends at the next level-2 heading, so every ``###`` subsection and
    the trailing ``---`` separator are handled. The version heading itself is not
    included in the output: the release title already carries the version.

    Heading forms accepted: ``## [1.2.0] - 2026-10-26``, ``## [v1.2.0] - ...``,
    ``## 1.2.0 - ...`` and ``## v1.2.0``. The version comparison ignores a leading
    ``v``, so a tag ``v1.2.0`` matches the heading ``[1.2.0]``.

Usage:
    .venv/bin/python utils/release_notes.py                      # print to stdout
    .venv/bin/python utils/release_notes.py --output dist/release_notes.md
    .venv/bin/python utils/release_notes.py --version 1.2.0      # override version.py
    .venv/bin/python utils/release_notes.py --tag v1.2.0         # verify the tag matches

Exit codes:
    0  the section was extracted
    1  no section for that version in CHANGELOG.md
    2  the requested version does not match version.py (or version.py is unreadable)
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION_FILE = REPO_ROOT / "version.py"
DEFAULT_CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"

EXIT_OK = 0
EXIT_NO_SECTION = 1
EXIT_VERSION_MISMATCH = 2

# A level-2 heading, which both starts a version section and terminates the one
# before it. Level-3 headings (### GUI and CLI binaries) are part of the body.
LEVEL_TWO_HEADING = re.compile(r"^##(?!#)\s*(?P<text>.*?)\s*$", re.MULTILINE)

# The leading version token of a heading: "1.2.0", "v1.2.0", "[1.2.0]",
# "[v1.2.0]" and a trailing " - 2026-10-26" date are all accepted.
HEADING_PATTERN = re.compile(
    r"^\[?(?P<version>v?\d+(?:\.\d+)*[0-9A-Za-z.\-+]*)\]?"
    r"(?:\s+-\s+(?P<date>.+?))?\s*$"
)

# A horizontal rule separating releases. Dropped when it trails the body.
TRAILING_RULE = re.compile(r"^-{3,}\s*$")


class ReleaseNotesError(RuntimeError):
    """Raised when the release notes cannot be produced."""


@dataclass(frozen=True)
class ReleaseSection:
    """One version's section of the changelog."""

    version: str
    """The version as written in the heading (``v1.2.0`` stays as written)."""

    date: str | None
    """The release date, when the heading carries one."""

    body: str
    """The section text without the heading and without trailing blank lines."""


def normalize_version(value: str) -> str:
    """Return value without surrounding whitespace or a leading ``v``."""
    return value.strip().lstrip("vV")


def read_version(version_file: Path = DEFAULT_VERSION_FILE) -> str:
    """
    Return VERSION_STRING from version.py.

    version.py is loaded as a module from its path rather than imported: the
    script may be run from any working directory, and this keeps the repository
    off ``sys.path``.
    """
    spec = importlib.util.spec_from_file_location("_release_notes_version", version_file)
    if spec is None or spec.loader is None:
        raise ReleaseNotesError(f"cannot load {version_file}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except OSError as error:
        raise ReleaseNotesError(f"cannot read {version_file}: {error}") from error

    version = getattr(module, "VERSION_STRING", None)
    if not isinstance(version, str) or not version.strip():
        raise ReleaseNotesError(f"{version_file} does not define VERSION_STRING")
    return version.strip()


def parse_heading(text: str) -> tuple[str, str | None] | None:
    """
    Return (version, date) for a level-2 heading's text, or None.

    ``Unreleased`` and any other non-version heading return None: they cannot be
    matched against a released version, so they are skipped rather than treated
    as an error.
    """
    match = HEADING_PATTERN.match(text.strip())
    if match is None:
        return None
    return match.group("version"), match.group("date")


def _trim_body(lines: list[str]) -> str:
    """Drop leading/trailing blank lines and a trailing horizontal rule."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    while end > start and TRAILING_RULE.match(lines[end - 1].strip()):
        end -= 1
        while end > start and not lines[end - 1].strip():
            end -= 1
    return "\n".join(lines[start:end])


def extract_section(changelog_text: str, version: str) -> ReleaseSection:
    """
    Return the changelog section for version.

    The comparison ignores a leading ``v`` in either the requested version or
    the heading, so ``v1.2.0`` and ``[1.2.0]`` are the same release.
    """
    target = normalize_version(version)
    headings = list(LEVEL_TWO_HEADING.finditer(changelog_text))

    for position, match in enumerate(headings):
        parsed = parse_heading(match.group("text"))
        if parsed is None or normalize_version(parsed[0]) != target:
            continue

        start = match.end()
        end = (
            headings[position + 1].start()
            if position + 1 < len(headings)
            else len(changelog_text)
        )
        body = _trim_body(changelog_text[start:end].splitlines())
        if not body:
            raise ReleaseNotesError(
                f"the section for version {version} is empty in the changelog"
            )
        return ReleaseSection(version=parsed[0], date=parsed[1], body=body)

    available = [
        parsed[0]
        for match in headings
        if (parsed := parse_heading(match.group("text"))) is not None
    ]
    known = ", ".join(available) if available else "none"
    raise ReleaseNotesError(
        f"no section for version {version} in the changelog "
        f"(versions found: {known}). Add a '## [{version}] - <date>' section."
    )


def write_notes(section: ReleaseSection, output: Path | None) -> str:
    """Return the text to publish and write it to output when one is given."""
    text = section.body + "\n"
    if output is None:
        return text

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Wrote release notes for {section.version} to {output}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract one version's section from CHANGELOG.md and write it as a "
            "GitHub Release body."
        )
    )
    parser.add_argument(
        "--version",
        default=None,
        metavar="<VERSION>",
        help="Version to extract (default: VERSION_STRING from version.py)",
    )
    parser.add_argument(
        "--tag",
        default=None,
        metavar="<TAG>",
        help=(
            "Tag being released, e.g. v1.2.0. Fails when it does not match the "
            "version, so a mis-tagged build cannot publish the wrong notes."
        ),
    )
    parser.add_argument(
        "--changelog",
        default=str(DEFAULT_CHANGELOG_FILE),
        metavar="<PATH>",
        help=f"Changelog to read (default: {DEFAULT_CHANGELOG_FILE.name})",
    )
    parser.add_argument(
        "--version-file",
        default=str(DEFAULT_VERSION_FILE),
        metavar="<PATH>",
        help=f"Module holding VERSION_STRING (default: {DEFAULT_VERSION_FILE.name})",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="<PATH>",
        help="File to write (default: stdout)",
    )
    args = parser.parse_args(argv)

    try:
        file_version = read_version(Path(args.version_file))
    except ReleaseNotesError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_VERSION_MISMATCH

    version = args.version or file_version
    if normalize_version(version) != normalize_version(file_version):
        print(
            f"Error: requested version {version} does not match "
            f"VERSION_STRING {file_version} in {args.version_file}",
            file=sys.stderr,
        )
        return EXIT_VERSION_MISMATCH

    if args.tag is not None and normalize_version(args.tag) != normalize_version(
        version
    ):
        print(
            f"Error: tag {args.tag} does not match version {version}",
            file=sys.stderr,
        )
        return EXIT_VERSION_MISMATCH

    changelog_path = Path(args.changelog)
    try:
        changelog_text = changelog_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"Error: cannot read {changelog_path}: {error}", file=sys.stderr)
        return EXIT_NO_SECTION

    try:
        section = extract_section(changelog_text, version)
    except ReleaseNotesError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_NO_SECTION

    text = write_notes(section, Path(args.output) if args.output else None)
    if args.output is None:
        sys.stdout.write(text)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
