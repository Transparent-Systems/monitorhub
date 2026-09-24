"""Profile subcommands for MonitorHub."""

import logging
import shlex
from typing import Any

from app.cli import profile_display
from app.cli.diagnostic_util import DiagnosticUtil
from app.cli.profile_editor import ProfileEditor
from app.cli.prompt_service import PromptService
from app.cli.selectors import ProfileSelector
from app.monitor.rclone_handler import RcloneHandler
from app.utils import reference_data
from app.utils.constants import (
    DEFAULT_COMMAND_MAX_WORKERS,
    MAX_COMMAND_MAX_WORKERS,
    MIN_COMMAND_MAX_WORKERS,
)
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

        Dispatch is based on the profile's category. Local/command profiles are
        tested in-process, while a remote profile is tested through the handler
        its ``remote_handler`` config key resolves to -- the same rule the
        monitor runtime uses, so the two cannot disagree.
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
            # The profile's remote_handler key selects the route (it is written
            # when the profile is created), matching the monitor runtime. Only
            # s3 has a native test today; a future native handler adds its
            # branch here.
            handler_key = reference_data.remote_handler_key(profile, logger=self.logger)
            if handler_key == "s3":
                # Lazy import: S3Factory pulls in boto3, so it is only loaded
                # when a native s3 profile is actually being tested.
                from app.monitor.s3_factory import S3Factory

                S3Factory.test_connection(profile_config=config, logger=self.logger, prompt=self.prompt)
            elif handler_key == reference_data.RCLONE_REMOTE_HANDLER:
                rclone_profile_name = profile.get("name")
                if rclone_profile_name is None:
                    self.prompt.print(f"Profile name not found for profile id: {profile_id}")
                    return False
                RcloneHandler.test_connection(
                    profile_name=rclone_profile_name,
                    logger=self.logger,
                    prompt=self.prompt,
                    profile=profile,
                )
            else:
                self.prompt.print(
                    f"Unknown or unsupported remote handler '{handler_key}' "
                    f"for profile id: {profile_id}"
                )
                return False
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
        # Tolerate a legacy comma-separated string as well as the list written
        # by the editor; iterating a string would otherwise check single
        # characters and report bogus "Invalid event(s)" errors.
        if isinstance(events, str):
            events = [e.strip() for e in events.split(",") if e.strip()]
        valid_events = {"created", "deleted", "modified", "moved", "closed", "timer"}
        if events:
            self.prompt.print(f"Events: {', '.join(events)}")
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
            except (OSError, ValueError) as e:
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
        if not profiles:
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
                self.prompt.print(
                    f"   {key}: {profile_display.format_value(key, config[key])}"
                )

    def import_profiles(self):
        """
        Import profiles from rclone.

        The user selects which profiles to import: press Enter to select none,
        enter 0 to select all, or enter a profile number to add single entries
        one at a time until pressing Enter stops the selection.
        """
        self.diagnostic_util.check_profile_import(select=True)
