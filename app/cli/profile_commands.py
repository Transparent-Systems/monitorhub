"""Profile subcommands for MonitorHub."""

import logging
import shlex
from typing import Any

from app.cli.profile_editor import ProfileEditor
from app.cli.prompt_service import PromptService
from app.cli.selectors import ProfileSelector
from app.monitor.action_handler import (
    DEFAULT_COMMAND_MAX_WORKERS,
    MAX_COMMAND_MAX_WORKERS,
    MIN_COMMAND_MAX_WORKERS,
)
from app.monitor.rclone_handler import RcloneHandler
from app.monitor.s3_factory import S3Factory
from app.utils import reference_data
from app.utils.diagnostic_util import DiagnosticUtil
from app.utils.generic_util import find_by_id, is_interval_valid
from app.utils.sqlite_handler import SQLiteHandler


class ProfileCommands:
    """Profile CRUD, test, and import commands."""

    def __init__(
        self,
        sqlite_handler: SQLiteHandler,
        logger: logging.Logger,
        diagnostic_util: DiagnosticUtil,
        prompt: PromptService,
    ) -> None:
        self.sqlite_handler = sqlite_handler
        self.logger = logger
        self.diagnostic_util = diagnostic_util
        self.prompt = prompt
        # Interactive list selection is delegated to a focused collaborator.
        self.selector = ProfileSelector(sqlite_handler=sqlite_handler, prompt=prompt)
        # Interactive creation/editing flows are delegated to a collaborator.
        self.editor = ProfileEditor(sqlite_handler=sqlite_handler, prompt=prompt)

    def test(
        self,
        profile_id: int | None = None,
        profile_name: str | None = None,
        live: bool = False,
    ) -> bool:
        """
        Test selected profile.

        Dispatch is based on the profile's category (from the profile_types
        lookup table), not the profile_type directly. This keeps the
        application future-proof: adding a new "remote" profile type (e.g.
        ftp) only requires adding a new handler branch under that category.
        """

        if profile_id is not None and profile_name is not None:
            self.prompt.print("Cannot specify both --profile-id and --profile-name.")
            return False

        if profile_id is not None:
            # Get profile from database using sqlite handler
            profile = self.sqlite_handler.get_profile(profile_id=profile_id)
            if not profile:
                self.prompt.print(f"Profile with id={profile_id} not found.")
                return False
        elif profile_name is not None:
            profile = self.sqlite_handler.get_profile(profile_name=profile_name)
            if not profile:
                self.prompt.print(f"Profile with name='{profile_name}' not found.")
                return False
            profile_id = profile.get("id")
        else:
            profile = self.selector.select_interactive()
            if not profile:
                return False
            profile_id = profile.get("id")

        self.prompt.print(f"You selected profile id: {profile_id}")
        self.prompt.print(f"Profile name: {profile.get('name', 'N/A')}")

        config = profile.get("config", {})
        profile_type = profile.get("profile_type")

        if not profile_type:
            self.prompt.print(f"Profile type not found for profile id: {profile_id}")
            return False
        
        # Look up category from the code-defined reference data
        category = reference_data.get_profile_category(profile_type)

        if category == "command":
            return self._test_command_profile(
                profile_name=profile.get("name") or "N/A",
                config=config or {},
                live=live,
            )
        if category == "remote":
            # Currently only the s3_handler is implemented as a native Python
            # handler. All other remote profile types use rclone_handler.
            # More native handlers can be added here in the future.
            if profile_type == "s3":
                S3Factory.test_connection(profile_config=config, logger=self.logger, prompt=self.prompt)
            else:
                profile_name = profile.get("name")
                if profile_name is None:
                    self.prompt.print(f"Profile name not found for profile id: {profile_id}")
                    return False
                RcloneHandler.test_connection(
                    profile_name=profile_name,
                    logger=self.logger,
                    prompt=self.prompt,
                )
            return True

        self.prompt.print(f"Unknown or unsupported profile category '{category}' for profile type '{profile_type}'")
        return False

    def _test_command_profile(
        self, profile_name: str, config: dict, live: bool = False
    ) -> bool:
        """
        Validate an event_command profile's configuration.

        Checks that:
        - command is present, non-empty, and parseable by shlex
        - command_cooldown is a valid interval string
        - command_events (if present) contain only valid event names

        After validation, performs a dry-run substitution with sample
        placeholders to show the resolved command line. If --live is passed,
        the resolved command is actually executed.
        """

        self.prompt.print("=" * 50)
        self.prompt.print(f"Testing command profile: {profile_name}")
        self.prompt.print("=" * 50)

        errors: list[str] = []

        # Validate command
        command = config.get("command")
        if not command or not command.strip():
            errors.append("Missing or empty 'command' in profile config")
        else:
            self.prompt.print(f"Command: {command}")
            try:
                shlex.split(command)
            except ValueError as e:
                errors.append(f"Command is not parseable by shlex: {e}")

        # Validate cooldown
        cooldown = config.get("command_cooldown", "0s")
        self.prompt.print(f"Cooldown: {cooldown}")
        if not is_interval_valid(cooldown):
            errors.append(f"Invalid command_cooldown: {cooldown!r}")

        # Validate events
        events = config.get("command_events")
        valid_events = {"created", "deleted", "modified", "moved", "closed", "timer"}
        if events:
            self.prompt.print(f"Events: {', '.join(events) if events else 'all'}")
            invalid = [e for e in events if e not in valid_events]
            if invalid:
                errors.append(f"Invalid event(s): {', '.join(invalid)}")
        else:
            self.prompt.print("Events: all")

        # Shell flag
        shell = config.get("command_shell", False)
        self.prompt.print(f"Shell execution: {'yes' if shell else 'no'}")

        # Max concurrent command workers
        max_workers = config.get("command_max_workers", DEFAULT_COMMAND_MAX_WORKERS)
        self.prompt.print(f"Max concurrent command workers: {max_workers}")
        try:
            max_workers_int = int(max_workers)
        except (TypeError, ValueError):
            errors.append(f"Invalid command_max_workers: {max_workers!r}")
        else:
            if not (MIN_COMMAND_MAX_WORKERS <= max_workers_int <= MAX_COMMAND_MAX_WORKERS):
                errors.append(
                    f"command_max_workers {max_workers_int} is out of range "
                    f"[{MIN_COMMAND_MAX_WORKERS}, {MAX_COMMAND_MAX_WORKERS}]"
                )

        if errors:
            self.prompt.print("")
            self.prompt.print("VALIDATION ERRORS:")
            for err in errors:
                self.prompt.print(f"  - {err}")
            self.prompt.print("")
            self.prompt.print("Test failed")
            return False

        # command is guaranteed non-None here (validated above)
        assert command is not None

        # --- Dry-run: resolve placeholders with sample values ---
        resolved_cmd: str = ""
        resolved_parts: list[str] = []

        sample_values = {
            "monitor_name": "Example Monitor",
            "profile_name": profile_name,
            "event_name": "created",
            "src_path": "/path/to/example/file.txt",
        }

        self.prompt.print("")
        self.prompt.print("--- Dry-Run: Placeholder Resolution ---")
        for placeholder, value in sample_values.items():
            self.prompt.print(f"  {{{placeholder}}}  -> {value}")

        if shell:
            import shlex as _shlex
            quoted = {k: _shlex.quote(v) for k, v in sample_values.items()}
            resolved_cmd = command.format(**quoted)
            self.prompt.print("")
            self.prompt.print("Resolved command (shell):")
            self.prompt.print(f"  {resolved_cmd}")
        else:
            try:
                tokens = shlex.split(command)
            except ValueError:
                # Already caught above
                self.prompt.print("Test failed")
                return False
            resolved_parts: list[str] = []
            for token in tokens:
                resolved_parts.append(token.format(**sample_values))
            resolved_cmd = " ".join(resolved_parts)
            self.prompt.print("")
            self.prompt.print("Resolved command (argv):")
            self.prompt.print(f"  {resolved_cmd}")

        self.prompt.print("=" * 50)

        if live:
            import subprocess

            self.prompt.print("")
            self.prompt.print("Executing command with sample values (live)...")
            try:
                if shell:
                    result = subprocess.run(
                        resolved_cmd,
                        shell=True,
                        timeout=30,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                else:
                    result = subprocess.run(
                        resolved_parts,
                        shell=False,
                        timeout=30,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                self.prompt.print(f"Exit code: {result.returncode}")
                if result.stdout:
                    self.prompt.print(f"stdout: {result.stdout.rstrip()}")
                if result.stderr:
                    self.prompt.print(f"stderr: {result.stderr.rstrip()}")
            except subprocess.TimeoutExpired:
                self.prompt.print("Command timed out after 30s")
                self.prompt.print("Test failed")
                return False
            except Exception as e:  # noqa: BLE001
                self.prompt.print(f"Error executing command: {e}")
                self.prompt.print("Test failed")
                return False
        else:
            self.prompt.print(
                "To execute the command live, use: python mhub.py profile test --live"
            )

        self.prompt.print("")
        self.prompt.print("All checks passed. Command profile is valid.")
        self.prompt.print("Test succeeded")
        return True

    def delete(self, profile_id: int | None = None, profile_name: str | None = None):
        """
        Show all profiles and let user choose one to delete, or delete a
        single profile when an id or name is given.
        """
        if profile_id is not None and profile_name is not None:
            self.prompt.print("Cannot specify both --profile-id and --profile-name.")
            return

        if profile_id is not None:
            profile = self.sqlite_handler.get_profile(profile_id=profile_id)
            if not profile:
                self.prompt.print(f"Profile with id={profile_id} not found.")
                return
            self._delete_profile(profile, profile_id=profile_id)
            return

        if profile_name is not None:
            profile = self.sqlite_handler.get_profile(profile_name=profile_name)
            if not profile:
                self.prompt.print(f"Profile with name='{profile_name}' not found.")
                return
            self._delete_profile(profile)
            return

        # Show all profiles
        profiles = self.sqlite_handler.get_profiles()
        if profiles is None or len(profiles) == 0:
            self.logger.info(f"No profiles found in {self.sqlite_handler.db_path}")
            return

        # Show all profiles
        self.prompt.print("\nList of profiles to delete")
        self.prompt.print("=" * 50)
        for profile in profiles:
            self.prompt.print(
                f"Id: {profile.get('id', 'N/A')}, Profile name: {profile.get('name', 'N/A')}"
            )
        self.prompt.print("=" * 50)

        # Prompt user for profile id
        def valid_profile_id(value: str) -> str | None:
            if not value.isdigit():
                return f"Invalid profile id: {value}. Please try again."
            if find_by_id(profiles, int(value)) is None:
                return f"Invalid profile id: {int(value)}. Please try again."
            return None

        def valid_repeat_profile_id(value: str) -> str | None:
            if not value.isdigit():
                return f"Invalid profile id: {value}. Please try again."
            return None

        profile: dict[str, Any] | None = None
        while True:
            profile_id_entered = self.prompt.prompt_choice(
                "Enter profile id to delete: ",
                valid=valid_profile_id,
                allow_cancel=True,
                echo_label="profile id",
            )
            if profile_id_entered is None:
                self.prompt.print("No profile selected")
                return

            profile_id_selected = int(profile_id_entered)
            profile = find_by_id(profiles, profile_id_selected)
            if profile is None:  # Defensive: valid_profile_id already checked.
                continue

            profile_id_repeat_entered = self.prompt.prompt_choice(
                "Repeat profile id to delete: ",
                valid=valid_repeat_profile_id,
                echo_label="profile id",
            )
            if profile_id_repeat_entered is None:  # Defensive: there is no cancel path.
                continue
            profile_id_repeat = int(profile_id_repeat_entered)

            if profile_id_selected != profile_id_repeat:
                self.prompt.print(f"Profile ids do not match: {profile_id_selected} is not {profile_id_repeat}. Please try again.")
                continue
            break

        profile_name = profile.get("name", "N/A")
        self.prompt.print(f"You want to delete profile: {profile_name}")

        self._delete_profile(profile)

    def _delete_profile(self, profile: dict[str, Any], profile_id: int | None = None) -> None:
        """Delete a single profile resolved by id or name."""
        profile_name = profile.get("name", "N/A")
        if profile_id is not None:
            deleted = self.sqlite_handler.delete_profile(profile_id=profile_id)
        else:
            deleted = self.sqlite_handler.delete_profile(profile_name=profile_name)

        if deleted:
            self.prompt.print(f"Profile name: {profile_name} deleted")
        else:
            self.prompt.print(f"Profile name: {profile_name} not deleted")

    def edit(self, profile_id: int | None = None, profile_name: str | None = None):
        """Edit a profile interactively (delegated to :class:`ProfileEditor`)."""
        self.editor.edit(profile_id=profile_id, profile_name=profile_name)

    def new(self):
        """Create a new profile interactively (delegated to :class:`ProfileEditor`)."""
        self.editor.new()

    def show(self, profile_id: int | None = None, profile_name: str | None = None):
        """
        Show all profiles, or a single profile when an id or name is given.
        """
        if profile_id is not None and profile_name is not None:
            self.prompt.print("Cannot specify both --profile-id and --profile-name.")
            return

        if profile_id is not None:
            profile = self.sqlite_handler.get_profile(profile_id=profile_id)
            if not profile:
                self.prompt.print(f"Profile with id={profile_id} not found.")
                return
            profiles = [profile]
        elif profile_name is not None:
            profile = self.sqlite_handler.get_profile(profile_name=profile_name)
            if not profile:
                self.prompt.print(f"Profile with name='{profile_name}' not found.")
                return
            profiles = [profile]
        else:
            profiles = self.sqlite_handler.get_profiles()

        for profile in profiles:
            self.prompt.print("=" * 50)
            self.prompt.print(f"Profile id: {profile.get('id', 'N/A')}")
            self.prompt.print(f"Profile name: {profile.get('name', 'N/A')}")
            self.prompt.print(f"Profile type: {profile.get('profile_type', 'N/A')}")
            config = profile.get("config", {})
            for key in config:
                self.prompt.print(f"   {key}: {config[key]}")

    def import_profiles(self):
        """
        Import profiles from rclone
        """
        self.diagnostic_util.check_profile_import()
