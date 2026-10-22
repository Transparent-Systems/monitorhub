"""Read rclone remotes and fold them into MonitorHub profile definitions.

This module is the single source of truth for reading ``rclone.conf`` and
mapping a section to a MonitorHub profile.  Both the CLI import action
(:class:`~app.cli.profile_importer.ProfileImporter`) and the web GUI profiles
page use it, so the reading rules cannot drift between the two.

It is deliberately free of prompting and database writes: it reads and parses
the config file and produces profile definitions.  Callers choose how to select
profiles and how to persist them.
"""

from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.monitor import rclone_env
from app.utils import reference_data

_SECTION_RE = re.compile(r"^\s*\[.*\]\s*$")
_KEY_RE = re.compile(r"^\s*[a-z0-9_]+\s*=")
_COMMENT_RE = re.compile(r"^\s*[#;]")


@dataclass(frozen=True)
class RcloneConfig:
    """A parsed ``rclone.conf``: its sections and any fatal error messages.

    ``sections`` maps each section name to its ``option = value`` pairs (option
    names lowercased, matching ``configparser``'s default behaviour).  When
    ``errors`` is non-empty the config must not be used; each message is
    user-facing and describes why.
    """

    sections: dict[str, dict[str, str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Extra warning detail for a config that could not be read (OS error or
    # invalid encoding).  Logged, not shown as a separate error.
    detail: str | None = None

    @property
    def is_usable(self) -> bool:
        """Return True when the config was read and has no errors."""
        return not self.errors


def default_rclone_config_path() -> Path:
    """Return the platform-specific default rclone config path."""
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", "")) / "rclone" / "rclone.conf"
    return Path.home() / ".config" / "rclone" / "rclone.conf"


def find_corrupt_lines(text: str) -> list[tuple[int, str, str]]:
    """Return the config lines that are not valid rclone config syntax.

    rclone writes one ``key = value`` per line, so a line is valid only when
    it is a section header, a comment, a blank line or a ``key = value`` line.
    Anything else -- a value wrapped onto its own line, stray text -- is
    corruption.  This is reported, never repaired.

    Returns ``(line_number, section, line)`` for every offending line, where
    ``line_number`` is one-based and ``section`` is the enclosing section name
    (or ``""`` when the line precedes any section).
    """
    corrupt: list[tuple[int, str, str]] = []
    section = ""

    for line_number, line in enumerate(text.splitlines(), start=1):
        if _SECTION_RE.match(line):
            section = line.strip()[1:-1].strip()
        elif (
            line.strip() == ""
            or _COMMENT_RE.match(line)
            or _KEY_RE.match(line)
        ):
            continue
        else:
            corrupt.append((line_number, section, line))

    return corrupt


def read_rclone_config(path: Path) -> RcloneConfig:
    """Read ``path`` and return its sections and any fatal error messages.

    MonitorHub does not repair a broken ``rclone.conf``.  rclone writes one
    ``key = value`` per line, so a line that is not a section header, a
    comment, a blank line or a ``key = value`` line is corruption (for example
    a value wrapped across lines).  A corrupt config is refused as a whole.
    """
    if not path.is_file():
        return RcloneConfig(errors=[f"No profiles found in {path}"])

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return RcloneConfig(
            errors=[f"No profiles found in {path}"],
            detail=f"Cannot read rclone config {path}: {error}",
        )

    corrupt = find_corrupt_lines(text)
    if corrupt:
        errors = [
            (
                f"Corrupt rclone config {path}: line {line_number} in "
                f"[{section or '?'}] does not start with a key: {line!r}. "
                "MonitorHub refuses to import a corrupt config; fix "
                "rclone.conf and run the import again."
            )
            for line_number, section, line in corrupt
        ]
        errors.append(f"No profiles imported from {path}")
        return RcloneConfig(errors=errors)

    # rclone.conf uses ``=`` only and has no configparser interpolation; the
    # defaults would treat ``:`` as a delimiter and expand ``%`` in a value.
    parser = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    try:
        parser.read_string(text, source=str(path))
    except configparser.Error as error:
        return RcloneConfig(
            errors=[
                (
                    f"Corrupt rclone config {path}: {error}. MonitorHub refuses "
                    "to import a corrupt config; fix rclone.conf and run the "
                    "import again."
                ),
                f"No profiles imported from {path}",
            ]
        )

    if not parser.sections():
        return RcloneConfig(errors=[f"No profiles found in {path}"])

    sections = {name: dict(parser[name]) for name in parser.sections()}
    return RcloneConfig(sections=sections)


def importable_profile_names(
    sections: dict[str, dict[str, str]],
    existing_names: set[str],
) -> list[str]:
    """Return section names that are not already MonitorHub profiles."""
    return [name for name in sections if name not in existing_names]


def build_profile(
    name: str,
    section: dict[str, str],
) -> tuple[str, dict[str, str], list[str]]:
    """Convert an rclone section into ``(profile_type, config, skipped_keys)``.

    The ``type`` key becomes the MonitorHub profile type; every other valid
    rclone option name is stored under its own name in ``config``; anything
    else is collected in ``skipped_keys`` so the caller can warn about it.  The
    returned config sets ``remote_handler`` to ``rclone``: imported profiles are
    rclone-managed by definition, even when their type has a native handler.
    """
    profile_type = ""
    profile_config: dict[str, str] = {}
    skipped_keys: list[str] = []

    for key, value in section.items():
        if key == "type":
            profile_type = value
        elif not rclone_env.is_valid_option_name(key):
            skipped_keys.append(key)
        else:
            profile_config[key] = value

    profile_config[reference_data.CONFIG_REMOTE_HANDLER] = (
        reference_data.RCLONE_REMOTE_HANDLER
    )
    return profile_type, profile_config, skipped_keys
