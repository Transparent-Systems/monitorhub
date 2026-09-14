"""Profile subcommands for MonitorHub."""

import logging
import shlex
from typing import Any

from app.cli.prompt_service import PromptService
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

    def _select_profile(self) -> dict[str, Any]:
        """
        Show all profiles and let user choose one
        Return profile as dictionary
        """

        # Get all profiles
        profiles: list[dict[str, Any]] = self.sqlite_handler.get_profiles()
        if profiles is None or len(profiles) == 0:
            self.prompt.print(f"No profiles found in {self.sqlite_handler.db_path}")
            return {}

        self.prompt.print("List of profiles")
        self.prompt.print("=" * 50)
        for profile in profiles:
            profile_id = profile.get("id", "N/A")
            profile_name = profile.get("name", "N/A")
            self.prompt.print(f"Id: {profile_id}, Profile name: {profile_name}")
        self.prompt.print("=" * 50)

        def valid_profile_id(value: str) -> str | None:
            if not value.isdigit():
                return f"Invalid profile id: {value}. Please try again."
            if find_by_id(profiles, int(value)) is None:
                return f"Invalid profile id: {int(value)}. Please try again."
            return None

        profile_id_entered = self.prompt.prompt_choice(
            "Enter profile id: ",
            valid=valid_profile_id,
            allow_cancel=True,
            echo_label="profile id",
        )
        if profile_id_entered is None:
            self.prompt.print("No profile selected")
            return {}

        selected = find_by_id(profiles, int(profile_id_entered))
        return selected if selected is not None else {}

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
            profile = self._select_profile()
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
        """
        Show all profiles and let user choose one to edit, or edit a single
        profile when an id or name is given.
        """
        if profile_id is not None and profile_name is not None:
            self.prompt.print("Cannot specify both --profile-id and --profile-name.")
            return

        profile: dict[str, Any] | None = None
        if profile_id is not None:
            profile = self.sqlite_handler.get_profile(profile_id=profile_id)
            if not profile:
                self.prompt.print(f"Profile with id={profile_id} not found.")
                return
        elif profile_name is not None:
            profile = self.sqlite_handler.get_profile(profile_name=profile_name)
            if not profile:
                self.prompt.print(f"Profile with name='{profile_name}' not found.")
                return

        if profile is not None:
            profile_type: str = str(profile.get("profile_type"))
            if not reference_data.is_profile_type_implemented(profile_type):
                self.prompt.print(f"Profile type '{profile_type}' is not implemented and cannot be edited.")
                return
        else:
            implemented_profiles = reference_data.filter_implemented_profiles(self.sqlite_handler.get_profiles())
            # If there are no implemented_profiles then we are done
            if not implemented_profiles:
                self.prompt.print(f"No implemented profiles found in {self.sqlite_handler.db_path}")
                return

            def render_implemented_profiles() -> None:
                self.prompt.print("List of profiles")
                self.prompt.print("=" * 50)
                for implemented_profile in implemented_profiles:
                    self.prompt.print(
                        f"Id: {implemented_profile.get('id', 'N/A')}, Profile name: {implemented_profile.get('name', 'N/A')}"
                    )
                self.prompt.print("=" * 50)

            def valid_implemented_profile_id(value: str) -> str | None:
                if not value.isdigit():
                    return f"Invalid profile id: {value}. Please try again."
                if find_by_id(implemented_profiles, int(value)) is None:
                    return f"Invalid profile id: {int(value)}. Please try again."
                return None

            input_profile_id = self.prompt.prompt_choice(
                "Enter profile id: ",
                valid=valid_implemented_profile_id,
                render=render_implemented_profiles,
                allow_cancel=True,
                echo_label="profile id",
            )
            if input_profile_id is None:
                self.prompt.print("No profile selected")
                return

            selected_profile_id = int(input_profile_id)
            profile = find_by_id(implemented_profiles, selected_profile_id)

        # Get profile name
        input_profile_name = profile.get("name", "N/A")
        self.prompt.print(f"You selected profile: {input_profile_name}")

        # Get profile category from code-defined reference data
        profile_type = profile.get("profile_type", "")
        profile_category = reference_data.get_profile_category(profile_type)

        if profile_category == "remote":
            self._edit_remote(profile=profile, profile_name=input_profile_name)
        else:
            self._edit_command(profile=profile, profile_name=input_profile_name)

    def _edit_command(self, profile: dict[str, Any], profile_name: str):
        """
        Handles profile edit for profiles with category "command". See lookup table profile_types.
        """
        profile_config = profile.get("config", {})

        # Prompt for updated command configuration, pre-populated with current values
        command_config = self._prompt_command_config(existing=profile_config)
        profile_config.update(command_config)

        # Update profile in database
        if self.sqlite_handler.update_profile(
            profile_id=profile["id"],
            name=profile["name"],
            profile_type=profile["profile_type"],
            config=profile_config,
        ):
            self.prompt.print(f"Profile name: {profile_name} updated")
        else:
            self.prompt.print(f"Profile name: {profile_name} not updated")

        self.prompt.print("Please test profile with one of the following commands:")
        self.prompt.print("   Command: mhub profile test")

    def _edit_remote(self, profile: dict[str, Any], profile_name: str):
        """
        Handles profile edit for profiles with category "remote". See lookup table profile_types.
        """
        # Lookup current provider from code-defined reference data
        profile_config = profile.get("config", {})
        current_provider_name = profile_config.get("provider_name", "")
        current_provider = reference_data.get_provider(current_provider_name)
        if current_provider is None:
            self.prompt.print(f"Provider not found for profile: {profile_name}")
            return

        # At this point we have a valid profile_type and provider_name
        # Currently we have only a remote profile for S3 implemented
        # When other profile types are implemented we need to change the logic here
        # Show current access key
        current_profile_access_key = profile_config.get("access_key_id", "N/A")
        self.prompt.print(f"Press Enter to keep current S3 access key: : {current_profile_access_key}")
        # Prompt user for access key
        input_access_key_id = self.prompt.input(f"Enter S3 access key id of your provider: {current_provider.name}: ")
        if input_access_key_id.strip() != "":
            # Store access key in profile_config
            profile_config["access_key_id"] = input_access_key_id

        # Show current secret key
        current_secret_key = profile_config.get("access_key_secret", "N/A")
        self.prompt.print(f"Press Enter to continue with S3 access key secret: {current_secret_key}")
        # Prompt user for secret key
        input_access_key_id_secret = self.prompt.input("Please enter secret key: ")
        if input_access_key_id_secret.strip() != "":
            # Store secret key in profile_config
            profile_config["access_key_secret"] = input_access_key_id_secret

        # Prompt user for region
        # For Amazon we need the region
        provider_name = profile_config.get("provider_name", "N/A")
        if "Amazon AWS" in provider_name:
            profile_config["env_auth"] = "false"
            profile_region = profile_config.get("region", None)

            def render_region() -> None:
                if profile_region:
                    self.prompt.print(f"Press Enter to continue with current region: {profile_region}")

            input_profile_region = self.prompt.prompt_required(
                f"Enter S3 region of your provider: {provider_name}: ",
                current=profile_region,
                empty_message="Region cannot be just spaces. Please try again.",
                render=render_region,
            )
            if input_profile_region:
                # Update region in profile_config
                profile_config["region"] = input_profile_region
        else:
            # For other providers we need the endpoint
            current_endpoint = profile_config.get("endpoint", "N/A")
            self.prompt.print(f"Press Enter to keep current endpoint: {current_endpoint}")
            endpoint_prompt = (
                f"Enter S3 endpoint from your provider: {provider_name}: "
                if current_endpoint
                else f"Enter S3 endpoint of your provider: {provider_name}: "
            )
            input_profile_endpoint = self.prompt.prompt_required(
                endpoint_prompt,
                allow_cancel=True,
                empty_message="Endpoint cannot be just spaces. Please try again.",
            )
            if input_profile_endpoint:
                # Update endpoint in profile_config
                profile_config["endpoint"] = input_profile_endpoint

        # Profile_config has already been populated with provider_name, access_key_id etc
        # Now update profile
        if self.sqlite_handler.update_profile(
            profile_id=profile["id"],
            name=profile["name"],
            profile_type=profile["profile_type"],
            config=profile_config
        ):
            self.prompt.print(f"Profile name: {profile_name} updated")
        else:
            self.prompt.print(f"Profile name: {profile_name} not updated")

        self.prompt.print("Please test profile with one of the following commands:")
        self.prompt.print("   Command: mhub profile test")

    def _prompt_command_config(self, existing: dict | None = None) -> dict:
        """Prompt the user for a shell command configuration stored on a profile."""

        current_command = existing.get("command") if existing else None
        current_events = existing.get("command_events") if existing else None
        current_cooldown = existing.get("command_cooldown", "0s") if existing else "0s"
        current_shell = existing.get("command_shell", False) if existing else False
        current_timeout = existing.get("command_timeout", "10s") if existing else "10s"
        current_max_workers = (
            existing.get("command_max_workers", DEFAULT_COMMAND_MAX_WORKERS)
            if existing
            else DEFAULT_COMMAND_MAX_WORKERS
        )
        
        # Command template
        self.prompt.print()
        self.prompt.print("Runtime variables are injected before the command runs:")
        self.prompt.print("  {monitor_name}  - name of the monitor")
        self.prompt.print("  {profile_name}  - name of the attached profile")
        self.prompt.print("  {event_name}    - event type: created, deleted, modified, moved, closed, timer")
        self.prompt.print("  {src_path}      - absolute source file path")
        self.prompt.print()
        self.prompt.print("Other information (monitor paths, destinations, etc.) is available")
        self.prompt.print("in the database and can be looked up by scripts using monitor_name")
        self.prompt.print("or profile_name.")
        self.prompt.print()
        self.prompt.print("Example:")
        self.prompt.print('  notify-send "Monitor={monitor_name}, profile={profile_name}, event={event_name}, file={src_path}"')
        self.prompt.print()
        prompt_text = "Please enter command to run"
        if current_command:
            prompt_text += f" (current: {current_command}; Enter to keep)"
        prompt_text += ": "
        command = self.prompt.prompt_required(
            prompt_text,
            current=current_command,
            empty_message="Command cannot be just spaces",
        ) or ""

        # Event filter
        valid_events = ["created", "deleted", "modified", "moved", "closed", "timer"]
        self.prompt.print("Available events: created, deleted, modified, moved, closed, timer")
        self.prompt.print("Leave empty for all events.")

        def parse_events(value: str) -> list[str]:
            return [e.strip() for e in value.split(",") if e.strip()]

        def valid_events_input(value: str) -> str | None:
            invalid = [e for e in parse_events(value) if e not in valid_events]
            if invalid:
                return f"Invalid event(s): {', '.join(invalid)}. Please try again."
            return None

        current_display = ",".join(current_events) if current_events else "all"
        input_events = self.prompt.prompt_required(
            f"Events to trigger on (current: {current_display}; Enter to keep): ",
            allow_cancel=True,
            validator=valid_events_input,
        )
        if input_events is None:
            events = current_events if (current_command and current_events is not None) else []
        else:
            events = parse_events(input_events)

        # Cooldown
        cooldown = self.prompt.prompt_required(
            f"Cooldown between command firings (current: {current_cooldown}; Enter to keep): ",
            default=current_cooldown if current_command else "0s",
            validator=lambda value: (
                None
                if is_interval_valid(value)
                else f"Invalid cooldown: {value}. Please try again."
            ),
        ) or "0s"

        # Timeout
        timeout = self.prompt.prompt_required(
            f"Timeout for command (current: {current_timeout}; Enter to keep): ",
            default=current_timeout or "10s",
            validator=lambda value: (
                None
                if is_interval_valid(value)
                else f"Invalid timeout: {value}. Please try again."
            ),
        ) or "10s"

        # Max concurrent command workers
        self.prompt.print(
            f"Max concurrent command workers (default: {DEFAULT_COMMAND_MAX_WORKERS}, "
            f"min: {MIN_COMMAND_MAX_WORKERS}, max: {MAX_COMMAND_MAX_WORKERS})."
        )
        self.prompt.print(
            "Commands are queued FIFO and never dropped when the limit is reached."
        )
        def valid_max_workers(value: str) -> str | None:
            try:
                workers = int(value)
            except ValueError:
                return f"Invalid number of workers: {value}. Please try again."
            if not (MIN_COMMAND_MAX_WORKERS <= workers <= MAX_COMMAND_MAX_WORKERS):
                return (
                    f"Number of workers must be between {MIN_COMMAND_MAX_WORKERS} and "
                    f"{MAX_COMMAND_MAX_WORKERS}. Please try again."
                )
            return None

        input_max_workers = self.prompt.prompt_required(
            f"Max concurrent command workers (default: {DEFAULT_COMMAND_MAX_WORKERS}, "
            f"min: {MIN_COMMAND_MAX_WORKERS}, max: {MAX_COMMAND_MAX_WORKERS}; "
            f"current: {current_max_workers}; Enter to keep): ",
            default=str(current_max_workers),
            validator=valid_max_workers,
        )
        max_workers = (
            int(input_max_workers) if input_max_workers is not None else current_max_workers
        )

        # Shell flag
        shell = bool(current_shell)
        if current_command:
            shell_prompt = (
                f"Use shell execution? (current: {'yes' if shell else 'no'}; Enter to keep; y/n): "
            )
        else:
            shell_prompt = "Use shell execution? (y/n, default no): "
        shell = self.prompt.prompt_yes_no(
            shell_prompt, default=shell if current_command else False
        )

        return {
            "command": command,
            "command_events": events,
            "command_cooldown": cooldown,
            "command_timeout": timeout,
            "command_shell": shell,
            "command_max_workers": max_workers,
        }

    def new(self):
        """
        Create a new profile.

        Mirrors monitor_new(): the profile category is selected interactively
        from reference_data.PROFILE_CATEGORIES instead of being a hard-coded
        CLI subcommand. The selected category then dispatches to the specific
        remote or command creation flow.
        """

        categories = reference_data.PROFILE_CATEGORIES
        if not categories:
            self.prompt.print("No profile categories available")
            return

        def render_categories() -> None:
            self.prompt.print("List of profile categories")
            self.prompt.print("=" * 50)
            for i, (name, description) in enumerate(categories):
                self.prompt.print(f"{i+1}. {name} - {description}")
            self.prompt.print("=" * 50)

        def valid_category_number(value: str) -> str | None:
            if not value.isdigit() or not (0 < int(value) <= len(categories)):
                return f"Invalid profile category number: {value}. Please try again."
            return None

        raw_category_number = self.prompt.prompt_choice(
            "Please select number of profile category: ",
            valid=valid_category_number,
            render=render_categories,
            empty_message="Profile category cannot be just spaces",
        )
        if raw_category_number is None:  # Defensive: there is no cancel path here.
            return
        input_category_number = int(raw_category_number)

        category = categories[input_category_number - 1][0]
        self.prompt.print(f"You selected profile category: {category}")

        if category == reference_data.PROFILE_CATEGORY_REMOTE:
            self._new_remote()
        elif category == reference_data.PROFILE_CATEGORY_COMMAND:
            self._new_command()
        else:
            self.prompt.print(f"Unknown or unsupported profile category '{category}'")

    def _new_remote(self):
        """
        Create a new remote profile.
        """

        implemented_providers = reference_data.get_providers()
        if not implemented_providers:
            self.prompt.print("No providers found")
            return

        # Prompt user for a profile_name
        def valid_profile_name(value: str) -> str | None:
            if self.sqlite_handler.get_profile(profile_name=value):
                return f"Profile name: {value} already exists. Please try again"
            return None

        input_profile_name = self.prompt.prompt_required(
            "Enter profile name: ",
            allow_cancel=True,
            validator=valid_profile_name,
            render=lambda: self.prompt.print(
                "Please enter a profile name. The profile name can be anything you like, "
                "but it must be unique. It will be used to identify the profile in the "
                "database and in the command line interface."
            ),
            echo_label="profile name",
        )
        if input_profile_name is None:
            self.prompt.print("Profile name cannot be just spaces.")
            return

        # Prompt user to select a provider
        def render_providers() -> None:
            self.prompt.print("Enter provider number")
            for i, provider in enumerate(implemented_providers):
                self.prompt.print(f"{i+1}. {provider.name}")

        def valid_provider_number(value: str) -> str | None:
            if not value.isdigit() or not (0 < int(value) <= len(implemented_providers)):
                return f"Invalid provider number: {value}. Please try again."
            return None

        raw_provider_number = self.prompt.prompt_choice(
            "Enter provider number: ",
            valid=valid_provider_number,
            render=render_providers,
            allow_cancel=True,
            echo_label="provider number",
        )
        if raw_provider_number is None:
            self.prompt.print("No provider selected")
            return
        provider_number = int(raw_provider_number)

        selected_provider = implemented_providers[provider_number - 1]
        input_provider_name = selected_provider.name
        input_type_name = selected_provider.profile_type

        # Prompt user for access key
        input_access_key_id = self.prompt.prompt_required(
            f"Enter S3 access key id of your provider: {input_provider_name}: ",
            empty_message="Access key id cannot be empty. Please try again.",
            echo_label="access key",
            echo_on_empty=True,
        ) or ""

        # Prompt user for secret key
        input_access_key_id_secret = self.prompt.prompt_required(
            f"Enter S3 access secret key of your provider: {input_provider_name}: ",
            empty_message="Access secret key cannot be empty. Please try again.",
        ) or ""

        input_region: str = ""
        input_endpoint: str = ""
        if "Amazon AWS" in input_provider_name:
            input_region = self.prompt.prompt_required(
                f"Enter S3 region of your provider: {input_provider_name}: ",
                empty_message="Region cannot be empty. Please try again.",
                echo_label="region",
                echo_on_empty=True,
            ) or ""
        else:
            input_endpoint = self.prompt.prompt_required(
                f"Enter S3 endpoint from your provider: {input_provider_name}: ",
                empty_message="Endpoint cannot be empty. Please try again.",
                echo_label="endpoint",
                echo_on_empty=True,
            ) or ""

        # Create profile
        profile_config = {
            "provider_name": input_provider_name,
            "access_key_id": input_access_key_id,
            "access_key_secret": input_access_key_id_secret,
        }

        if "Amazon AWS" in input_provider_name:
            profile_config["env_auth"] = "false"
            profile_config["region"] = input_region
        else:
            profile_config["endpoint"] = input_endpoint

        # Now add profile to database
        profile_id = self.sqlite_handler.add_profile(
            name=input_profile_name,
            profile_type=input_type_name,
            config=profile_config
        )

        if profile_id is None:
            self.prompt.print(f"Profile name: {input_profile_name} not created")
        else:
            self.prompt.print(f"Profile name: {input_profile_name} created")

        self.prompt.print("Please test profile with one of the following commands:")
        self.prompt.print("   Command: mhub profile test")

    def _new_command(self):
        """
        Create a new event_command profile.

        An event_command profile triggers a shell command on matching events
        (file system events such as created/modified, or timer events).
        Unlike a remote profile, it has no provider, credentials, or
        remote endpoint — only the command configuration is required.
        """

        # Prompt user for a unique profile name
        def valid_profile_name(value: str) -> str | None:
            if self.sqlite_handler.get_profile(profile_name=value):
                return f"Profile name: {value} already exists. Please try again"
            return None

        input_profile_name = self.prompt.prompt_required(
            "Enter profile name: ",
            allow_cancel=True,
            validator=valid_profile_name,
            render=lambda: self.prompt.print(
                "Please enter a profile name. The profile name can be anything you like, "
                "but it must be unique. It will be used to identify the profile in the "
                "database and in the command line interface."
            ),
            echo_label="profile name",
        )
        if input_profile_name is None:
            self.prompt.print("Profile name cannot be just spaces.")
            return

        # Prompt for mandatory command configuration
        command_config = self._prompt_command_config()

        # Create profile
        profile_id = self.sqlite_handler.add_profile(
            name=input_profile_name,
            profile_type="event_command",
            config=command_config,
        )

        if profile_id is None:
            self.prompt.print(f"Profile name: {input_profile_name} not created")
        else:
            self.prompt.print(f"Profile name: {input_profile_name} created")

        self.prompt.print("Please test profile with one of the following commands:")
        self.prompt.print("   Command: mhub profile test")

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