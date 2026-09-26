"""Import rclone remotes into MonitorHub as profiles.

The interactive rclone -> MonitorHub profile import lives here rather than in
:class:`~app.cli.diagnostic_util.DiagnosticUtil`: importing profiles is a CLI
action, while the diagnostic util only *reports* whether any profile is
available to import.  A single :class:`ProfileImporter` instance is shared by
both callers so the rclone.conf reading/folding rules cannot drift between the
check and the actual import.
"""

from __future__ import annotations

import configparser
import logging
import os
import re
from pathlib import Path

from app.cli.prompt_service import PromptService
from app.cli.selectors import ProfileImportSelector
from app.monitor import rclone_env
from app.utils import reference_data
from app.utils.sqlite_handler import SQLiteHandler


class ProfileImporter:
    """Read rclone remotes and import the selected ones as MonitorHub profiles."""

    def __init__(
        self,
        sqlite_handler: SQLiteHandler,
        logger: logging.Logger | None = None,
        prompt: PromptService | None = None,
    ) -> None:
        self.sqlite_handler = sqlite_handler
        self.logger = logger or logging.getLogger(__name__)
        self.prompt = prompt or PromptService()
        # Interactive import selection is delegated to a focused collaborator.
        self.selector = ProfileImportSelector(prompt=self.prompt)

    @staticmethod
    def default_rclone_config_path() -> Path:
        """Return the platform-specific default rclone config path."""
        if os.name == "nt":
            return Path(os.environ.get("APPDATA", "")) / "rclone" / "rclone.conf"
        return Path.home() / ".config" / "rclone" / "rclone.conf"

    def find_importable_profiles(
        self, rclone_config_path: Path | None = None
    ) -> list[str]:
        """Return rclone profile names that are not yet in the profiles table.

        Read-only and quiet: used by
        :meth:`DiagnosticUtil.check_profile_import <app.cli.diagnostic_util.DiagnosticUtil.check_profile_import>`
        to report whether an import is possible without prompting the user or
        writing anything to the database.
        """
        rclone_config_path = rclone_config_path or self.default_rclone_config_path()
        parser = self._read_rclone_config(rclone_config_path, notify=False)
        if parser is None:
            return []
        return self._find_importable_profiles(parser.sections())

    def import_profiles(self, rclone_config_path: Path | None = None) -> list[str]:
        """Interactively import rclone profiles that are not yet in MonitorHub.

        The user selects which profiles to import: press Enter to select none,
        enter 0 to select all, or enter a profile number to add single entries
        one at a time until pressing Enter stops the selection.  Returns the
        names that were imported.
        """
        rclone_config_path = rclone_config_path or self.default_rclone_config_path()
        parser = self._read_rclone_config(rclone_config_path, notify=True)
        if parser is None:
            return []

        profiles_to_import = self._find_importable_profiles(parser.sections())
        if not profiles_to_import:
            self.prompt.print("No profiles to import")
            return []

        selected = self.selector.select_interactive(profiles_to_import)
        if not selected:
            self.prompt.print("No profiles selected")
            return []

        return self._import_profiles(parser=parser, profile_names=selected)

    _SECTION_RE = re.compile(r"^\s*\[.*\]\s*$")
    _KEY_RE = re.compile(r"^\s*[a-z0-9_]+\s*=")
    _COMMENT_RE = re.compile(r"^\s*[#;]")

    def _read_rclone_config(
        self, rclone_config_path: Path, notify: bool
    ) -> configparser.ConfigParser | None:
        """Read the rclone config file, returning None when it cannot be used.

        MonitorHub does not repair a broken ``rclone.conf``.  rclone writes one
        ``key = value`` per line, so any line that is not a section header, a
        comment, a blank line or a ``key = value`` line is corruption (e.g. a
        value wrapped across lines).  Such a config is refused as a whole: the
        offending lines are reported and ``None`` is returned so no profile is
        imported.

        Warnings are always logged; they are additionally printed to the user
        only when ``notify`` is True (the interactive import), so the diagnostic
        check stays quiet.
        """
        if not rclone_config_path.is_file():
            if notify:
                self.prompt.print(f"No profiles found in {rclone_config_path}")
            else:
                self.logger.debug(f"No rclone config found at {rclone_config_path}")
            return None

        try:
            text = rclone_config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self.logger.warning(
                f"Cannot read rclone config {rclone_config_path}: {error}"
            )
            if notify:
                self.prompt.print(f"No profiles found in {rclone_config_path}")
            return None

        corrupt_lines = self._find_corrupt_lines(text)
        if corrupt_lines:
            for line_number, section, line in corrupt_lines:
                message = (
                    f"Corrupt rclone config {rclone_config_path}: line "
                    f"{line_number} in [{section or '?'}] does not start with a "
                    f"key: {line!r}. MonitorHub refuses to import a corrupt "
                    "config; fix rclone.conf and run the import again."
                )
                self.logger.warning(message)
                if notify:
                    self.prompt.print(f"Error: {message}")
            if notify:
                self.prompt.print(f"No profiles imported from {rclone_config_path}")
            return None

        # rclone.conf uses ``=`` only and has no configparser interpolation; the
        # defaults would treat ``:`` as a delimiter and expand ``%`` in a value.
        parser = configparser.ConfigParser(interpolation=None, delimiters=("=",))
        try:
            parser.read_string(text, source=str(rclone_config_path))
        except configparser.Error as error:
            message = (
                f"Corrupt rclone config {rclone_config_path}: {error}. MonitorHub "
                "refuses to import a corrupt config; fix rclone.conf and run the "
                "import again."
            )
            self.logger.warning(message)
            if notify:
                self.prompt.print(f"Error: {message}")
                self.prompt.print(f"No profiles imported from {rclone_config_path}")
            return None
        if not parser.sections():
            if notify:
                self.prompt.print(f"No profiles found in {rclone_config_path}")
            else:
                self.logger.debug(f"No profiles found in {rclone_config_path}")
            return None
        return parser

    @classmethod
    def _find_corrupt_lines(cls, text: str) -> list[tuple[int, str, str]]:
        """Return the config lines that are not valid rclone config syntax.

        rclone writes one ``key = value`` per line, so a line is valid only when
        it is a section header, a comment, a blank line or a ``key = value``
        line.  Anything else -- a value wrapped onto its own line, stray text --
        is corruption.  This is reported, never repaired.

        Returns ``(line_number, section, line)`` for every offending line, where
        ``line_number`` is one-based and ``section`` is the enclosing section
        name (or ``""`` when the line precedes any section).
        """
        corrupt: list[tuple[int, str, str]] = []
        section = ""

        for line_number, line in enumerate(text.splitlines(), start=1):
            if cls._SECTION_RE.match(line):
                section = line.strip()[1:-1].strip()
            elif (
                line.strip() == ""
                or cls._COMMENT_RE.match(line)
                or cls._KEY_RE.match(line)
            ):
                continue
            else:
                corrupt.append((line_number, section, line))

        return corrupt

    def _find_importable_profiles(self, rclone_profile_names: list[str]) -> list[str]:
        """Return rclone profile names that are not yet in the profiles table."""
        existing_names = {
            profile.get("name", "") for profile in self.sqlite_handler.get_profiles()
        }
        return [name for name in rclone_profile_names if name not in existing_names]

    def _import_profiles(
        self, parser: configparser.ConfigParser, profile_names: list[str]
    ) -> list[str]:
        """Convert the selected rclone sections into MonitorHub profiles."""
        # Some Rclone attribute names differ from those in MonitorHub.  Keys not
        # listed here are stored unchanged, so an identity entry is unnecessary.
        config_attribute_map = {
            "provider": "provider_name",
        }
        config_attribute_map_keys = config_attribute_map.keys()

        imported: list[str] = []
        for profile_name in profile_names:
            rclone_profile = dict(parser[profile_name]) if profile_name in parser else {}
            profile_type = ""
            profile_config = {}
            # Store each attribute with their corresponding name in profile_config
            for key in rclone_profile:
                if key == "type":
                    profile_type = rclone_profile[key]
                elif not rclone_env.is_valid_option_name(key):
                    # Not an rclone option name: a mangled config line would
                    # only add a bogus property, so skip it and say so.
                    self.prompt.print(
                        f"Warning: skipping unexpected key '{key}' in rclone "
                        f"profile '{profile_name}'"
                    )
                elif key in config_attribute_map_keys:
                    profile_config[config_attribute_map[key]] = rclone_profile[key]
                else:
                    profile_config[key] = rclone_profile[key]

            # MonitorHub owns the profile configuration: the display hints of
            # the rclone-import era (``comment``/``important``) are no longer
            # written, and existing ones are ignored when the rclone environment
            # is built.  Imported profiles are still rclone-managed, so they are
            # routed through rclone even when their type has a native handler.
            profile_config[reference_data.CONFIG_REMOTE_HANDLER] = (
                reference_data.RCLONE_REMOTE_HANDLER
            )
            # Add profile to database
            if self.sqlite_handler.add_profile(
                name=profile_name,
                profile_type=profile_type,
                config=profile_config,
            ):
                self.prompt.print(f"Profile name: {profile_name} imported to profiles")
                imported.append(profile_name)
            else:
                self.prompt.print(f"Profile name: {profile_name} not imported to profiles")

        return imported
