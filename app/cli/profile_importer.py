"""Import rclone remotes into MonitorHub as profiles.

The interactive rclone -> MonitorHub profile import lives here rather than in
:class:`~app.cli.diagnostic_util.DiagnosticUtil`: importing profiles is a CLI
action, while the diagnostic util only *reports* whether any profile is
available to import.  A single :class:`ProfileImporter` instance is shared by
both callers, and the rclone.conf reading/folding rules live in
:mod:`app.monitor.rclone_importer` so the check, the import and the web GUI
cannot disagree.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.cli.prompt_service import PromptService
from app.cli.selectors import ProfileImportSelector
from app.monitor import rclone_importer
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
        return rclone_importer.default_rclone_config_path()

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
        config = rclone_importer.read_rclone_config(rclone_config_path)
        if not config.is_usable:
            self._log_config_errors(config)
            return []
        return rclone_importer.importable_profile_names(
            config.sections, self._existing_profile_names()
        )

    def import_profiles(self, rclone_config_path: Path | None = None) -> list[str]:
        """Interactively import rclone profiles that are not yet in MonitorHub.

        The user selects which profiles to import: press Enter to select none,
        enter 0 to select all, or enter a profile number to add single entries
        one at a time until pressing Enter stops the selection.  Returns the
        names that were imported.
        """
        rclone_config_path = rclone_config_path or self.default_rclone_config_path()
        config = rclone_importer.read_rclone_config(rclone_config_path)
        if not config.is_usable:
            self._report_config_errors(config)
            return []

        profiles_to_import = rclone_importer.importable_profile_names(
            config.sections, self._existing_profile_names()
        )
        if not profiles_to_import:
            self.prompt.print("No profiles to import")
            return []

        selected = self.selector.select_interactive(profiles_to_import)
        if not selected:
            self.prompt.print("No profiles selected")
            return []

        return self._import_profiles(sections=config.sections, profile_names=selected)

    def _existing_profile_names(self) -> set[str]:
        """Return the names of the profiles already in the database."""
        return {
            profile.get("name", "") for profile in self.sqlite_handler.get_profiles()
        }

    def _log_config_errors(self, config: rclone_importer.RcloneConfig) -> None:
        """Log a config that cannot be used without printing to the user."""
        if config.detail:
            self.logger.warning(config.detail)
        for message in config.errors:
            if message.startswith("Corrupt rclone config"):
                self.logger.warning(message)
            else:
                self.logger.debug(message)

    def _report_config_errors(self, config: rclone_importer.RcloneConfig) -> None:
        """Log and print a config that cannot be used."""
        if config.detail:
            self.logger.warning(config.detail)
        for message in config.errors:
            if message.startswith("Corrupt rclone config"):
                self.logger.warning(message)
                self.prompt.print(f"Error: {message}")
            else:
                self.logger.debug(message)
                self.prompt.print(message)

    @classmethod
    def _find_corrupt_lines(cls, text: str) -> list[tuple[int, str, str]]:
        """Return the config lines that are not valid rclone config syntax."""
        return rclone_importer.find_corrupt_lines(text)

    def _import_profiles(
        self,
        sections: dict[str, dict[str, str]],
        profile_names: list[str],
    ) -> list[str]:
        """Convert the selected rclone sections into MonitorHub profiles."""
        imported: list[str] = []
        for profile_name in profile_names:
            profile_type, profile_config, skipped_keys = rclone_importer.build_profile(
                profile_name, sections.get(profile_name, {})
            )
            for key in skipped_keys:
                self.prompt.print(
                    f"Warning: skipping unexpected key '{key}' in rclone "
                    f"profile '{profile_name}'"
                )

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
