"""Profile subcommands for MonitorHub."""

import logging
import shlex
from typing import Any

from scripts import reference_data
from scripts.prompt_service import PromptService
from scripts.rclone_handler import RcloneHandler
from scripts.s3_factory import S3Factory
from scripts.sqlite_handler import SQLiteHandler
from scripts.utils.diagnostic_util import DiagnosticUtil
from scripts.utils.generic_util import find_by_id


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

        while True:
            profile_id_entered = self.prompt.input("Enter profile id: ").strip()
            self.prompt.print(f"You entered profile id: {profile_id_entered}")
            if not profile_id_entered.isdigit():
                self.prompt.print(f"Invalid profile id: {profile_id_entered}. Please try again.")
                continue

            profile_id = int(profile_id_entered)
            for profile in profiles:
                if profile.get("id") == profile_id:
                    return profile

            self.prompt.print(f"Invalid profile id: {profile_id}. Please try again.")

    def test(self, profile_id: int | None = None, live: bool = False) -> bool:
        """
        Test selected profile.

        Dispatch is based on the profile's category (from the profile_types
        lookup table), not the profile_type directly. This keeps the
        application future-proof: adding a new "remote" profile type (e.g.
        ftp) only requires adding a new handler branch under that category.
        """

        if profile_id:
            # Get profile from database using sqlite handler
            profile = self.sqlite_handler.get_profile(profile_id=profile_id)
            if profile is None:
                self.prompt.print(f"Profile not found: {profile_id}")
                return False
        else:
            profile = self._select_profile()
            if not profile:
                return False
            profile_id = profile.get("id")

        self.prompt.print(f"You selected profile id: {profile_id}")
        self.prompt.print(f"Profile name: {profile.get('name', 'N/A')}")

        config = profile.get("config", {})
        profile_type = profile.get("profile_type")

        # Look up category from the code-defined reference data
        category = reference_data.get_profile_category(profile_type)

        if category == "command":
            return self._test_command_profile(
                profile_name=profile.get("name") or "N/A",
                config=config or {},
                live=live,
            )
        elif category == "remote":
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
        else:
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
        if not self._is_interval_valid(cooldown):
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
            except Exception as e:
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

    def delete(self):
        """
        Show all profiles and let user choose one to delete
        """

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
        while True:
            profile_id_entered = self.prompt.input("Enter profile id to delete: ").strip()
            self.prompt.print(f"You entered profile id: {profile_id_entered}")
            if not profile_id_entered.isdigit():
                self.prompt.print(f"Invalid profile id: {profile_id_entered}. Please try again.")
                continue

            profile_id = int(profile_id_entered)
            profile = find_by_id(profiles, profile_id)
            if profile is None:
                self.prompt.print(f"Invalid profile id: {profile_id}. Please try again.")
                continue

            profile_id_repeat_entered = self.prompt.input("Repeat profile id to delete: ").strip()
            self.prompt.print(f"You entered profile id: {profile_id_repeat_entered}")
            if not profile_id_repeat_entered.isdigit():
                self.prompt.print(f"Invalid profile id: {profile_id_repeat_entered}. Please try again.")
                continue
            profile_id_repeat = int(profile_id_repeat_entered)

            if profile_id != profile_id_repeat:
                self.prompt.print(f"Profile ids do not match: {profile_id} is not {profile_id_repeat}. Please try again.")
                continue
            break

        profile_name = profile.get("name", "N/A")
        self.prompt.print(f"You want to delete profile: {profile_name}")

        if self.sqlite_handler.delete_profile(profile_name=profile_name):
            self.prompt.print(f"Profile name: {profile_name} deleted")
        else:
            self.prompt.print(f"Profile name: {profile_name} not deleted")

    def edit(self):
        """
        Show all profiles and let user choose one to edit
        """

        implemented_profiles = reference_data.filter_implemented_profiles(self.sqlite_handler.get_profiles())
        # If there are no implemented_profiles then we are done
        if not implemented_profiles:
            self.prompt.print(f"No implemented profiles found in {self.sqlite_handler.db_path}")
            return

        while True:
            # Show all implemented profiles
            self.prompt.print("List of profiles")
            self.prompt.print("=" * 50)
            for profile in implemented_profiles:
                self.prompt.print(
                    f"Id: {profile.get('id', 'N/A')}, Profile name: {profile.get('name', 'N/A')}"
                )
            self.prompt.print("=" * 50)

            input_profile_id = self.prompt.input("Enter profile id: ").strip()

            if input_profile_id == "":
                self.prompt.print("No profile selected")
                return

            self.prompt.print(f"You entered profile id: {input_profile_id}")
            if not input_profile_id.isdigit():
                self.prompt.print(f"Invalid profile id: {input_profile_id}. Please try again.")
                continue

            profile_id = int(input_profile_id)
            profile = find_by_id(implemented_profiles, profile_id)
            if profile is not None:
                break

            self.prompt.print(f"Invalid profile id: {profile_id}. Please try again.")

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
            while True:
                # Show current region
                if profile_region:
                    self.prompt.print(f"Press Enter to continue with current region: {profile_region}")
                    # Prompt user for region
                    input_profile_region = self.prompt.input(f"Enter S3 region of your provider: {provider_name}: ")
                    if input_profile_region.strip() == "":
                        # No changes in profile_config
                        break
                    # Update region in profile_config
                    profile_config["region"] = input_profile_region
                    break
                else:
                    # Prompt user for region
                    input_profile_region = self.prompt.input(f"Enter S3 region of your provider: {provider_name}: ")
                    if input_profile_region.strip() == "":
                        self.prompt.print("Region cannot be just spaces. Please try again.")
                        continue

                    # Update region in profile_config
                    profile_config["region"] = input_profile_region
                    break
        else:
            # For other providers we need the endpoint
            current_endpoint = profile_config.get("endpoint", "N/A")
            self.prompt.print(f"Press Enter to keep current endpoint: {current_endpoint}")
            while True:
                if current_endpoint:
                    input_profile_endpoint = self.prompt.input(f"Enter S3 endpoint from your provider: {provider_name}: ")
                    if input_profile_endpoint.strip() != "":
                        # Update endpoint in profile_config
                        profile_config["endpoint"] = input_profile_endpoint
                    break
                else:
                    input_profile_endpoint = self.prompt.input(f"Enter S3 endpoint of your provider: {provider_name}: ")
                    if input_profile_endpoint.strip() == "":
                        self.prompt.print("Endpoint cannot be just spaces. Please try again.")
                        continue
                    # Update endpoint in profile_config
                    profile_config["endpoint"] = input_profile_endpoint
                    break

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

    def _is_interval_valid(self, interval: str) -> bool:
        """Check if interval string is valid (e.g. 10, 10m, 10h, 10d)."""
        if interval.isdigit():
            return True
        if len(interval) > 1:
            unit = interval[-1].lower()
            value = interval[:-1]
            if unit in ("s", "m", "h", "d") and value.isdigit():
                return True
        return False

    def _prompt_command_config(self, existing: dict | None = None) -> dict:
        """Prompt the user for a shell command configuration stored on a profile."""

        current_command = existing.get("command") if existing else None
        current_events = existing.get("command_events") if existing else None
        current_cooldown = existing.get("command_cooldown", "0s") if existing else "0s"
        current_shell = existing.get("command_shell", False) if existing else False
        current_timeout = existing.get("command_timeout", "10s") if existing else "10s"
        
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
        while True:
            prompt_text = "Please enter command to run"
            if current_command:
                prompt_text += f" (current: {current_command}; Enter to keep)"
            prompt_text += ": "
            input_command = self.prompt.input(prompt_text).strip()
            if input_command == "":
                if current_command:
                    command = current_command
                    break
                self.prompt.print("Command cannot be just spaces")
                continue
            command = input_command
            break

        # Event filter
        valid_events = ["created", "deleted", "modified", "moved", "closed", "timer"]
        self.prompt.print("Available events: created, deleted, modified, moved, closed, timer")
        self.prompt.print("Leave empty for all events.")
        while True:
            current_display = ",".join(current_events) if current_events else "all"
            input_events = self.prompt.input(
                f"Events to trigger on (current: {current_display}; Enter to keep): "
            ).strip()
            if input_events == "":
                if current_command and current_events is not None:
                    events = current_events
                    break
                events = []
                break

            requested = [e.strip() for e in input_events.split(",") if e.strip()]
            invalid = [e for e in requested if e not in valid_events]
            if invalid:
                self.prompt.print(f"Invalid event(s): {', '.join(invalid)}. Please try again.")
                continue
            events = requested
            break

        # Cooldown
        while True:
            input_cooldown = self.prompt.input(
                f"Cooldown between command firings (current: {current_cooldown}; Enter to keep): "
            ).strip()
            if input_cooldown == "":
                cooldown = current_cooldown if current_command else "0s"
                break
            if not self._is_interval_valid(input_cooldown):
                self.prompt.print(f"Invalid cooldown: {input_cooldown}. Please try again.")
                continue
            cooldown = input_cooldown
            break

        # Timeout
        while True:
            input_timeout = self.prompt.input(
                f"Timeout for command (current: {current_timeout}; Enter to keep): "
            ).strip()
            if input_timeout == "":
                timeout = current_timeout if current_timeout else "10s"
                break
            if not self._is_interval_valid(input_timeout):
                self.prompt.print(f"Invalid timeout: {input_timeout}. Please try again.")
                continue
            timeout = input_timeout
            break

        # Shell flag
        shell = bool(current_shell)
        while True:
            if current_command:
                shell_prompt = (
                    f"Use shell execution? (current: {'yes' if shell else 'no'}; Enter to keep; y/n): "
                )
            else:
                shell_prompt = "Use shell execution? (y/n, default no): "
            input_shell = self.prompt.input(shell_prompt).strip().lower()
            if input_shell == "":
                if current_command:
                    break
                shell = False
                break
            if input_shell in ("y", "yes"):
                shell = True
                break
            if input_shell in ("n", "no"):
                shell = False
                break
            self.prompt.print("Please answer y or n.")

        config = {
            "command": command,
            "command_events": events,
            "command_cooldown": cooldown,
            "command_timeout": timeout,
            "command_shell": shell,
        }
        return config

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

        while True:
            self.prompt.print("List of profile categories")
            self.prompt.print("=" * 50)
            for i, (name, description) in enumerate(categories):
                self.prompt.print(f"{i+1}. {name} - {description}")
            self.prompt.print("=" * 50)

            input_category_number = self.prompt.input("Please select number of profile category: ")
            if input_category_number.strip() == "":
                self.prompt.print("Profile category cannot be just spaces")
                continue

            if not input_category_number.isdigit():
                self.prompt.print(f"Invalid profile category number: {input_category_number}. Please try again.")
                continue

            input_category_number = int(input_category_number)
            if input_category_number > 0 and input_category_number <= len(categories):
                break

            self.prompt.print(f"Invalid profile category number: {input_category_number}. Please try again.")

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
        while True:
            self.prompt.print(
                "Please enter a profile name. The profile name can be anything you like, "
                "but it must be unique. It will be used to identify the profile in the "
                "database and in the command line interface."
            )
            input_profile_name = self.prompt.input("Enter profile name: ")

            if input_profile_name.strip() == "":
                self.prompt.print("Profile name cannot be just spaces.")
                return

            self.prompt.print(f"You entered profile name: {input_profile_name}")

            # Check if profile_name already exists
            profile = self.sqlite_handler.get_profile(profile_name=input_profile_name)

            if profile:
                self.prompt.print(f"Profile name: {input_profile_name} already exists. Please try again")
                continue
            break

        # Prompt user to select a provider
        while True:
            self.prompt.print("Enter provider number")
            for i, provider in enumerate(implemented_providers):
                self.prompt.print(f"{i+1}. {provider.name}")
            input_provider_number = self.prompt.input("Enter provider number: ")

            if input_provider_number == "":
                self.prompt.print("No provider selected")
                return

            self.prompt.print(f"You entered provider number: {input_provider_number}")
            if input_provider_number.isdigit():
                input_provider_number = int(input_provider_number)
                if input_provider_number > 0 and input_provider_number <= len(implemented_providers):
                    break
            else:
                self.prompt.print(f"Invalid provider number: {input_provider_number}. Please try again.")
                continue
            break

        selected_provider = implemented_providers[input_provider_number - 1]
        input_provider_name = selected_provider.name
        input_type_name = selected_provider.profile_type

        # Prompt user for access key
        while True:
            input_access_key_id = self.prompt.input(f"Enter S3 access key id of your provider: {input_provider_name}: ")
            self.prompt.print(f"You entered access key: {input_access_key_id}")
            if input_access_key_id.strip() == "":
                self.prompt.print("Access key id cannot be empty. Please try again.")
                continue
            break

        # Prompt user for secret key
        while True:
            input_access_key_id_secret = self.prompt.input(f"Enter S3 access secret key of your provider: {input_provider_name}: ")
            if input_access_key_id_secret.strip() == "":
                self.prompt.print("Access secret key cannot be empty. Please try again.")
                continue
            break

        input_region = None
        input_endpoint = None
        if "Amazon AWS" in input_provider_name:
            while True:
                input_region = self.prompt.input(f"Enter S3 region of your provider: {input_provider_name}: ")
                self.prompt.print(f"You entered region: {input_region}")
                if input_region.strip() == "":
                    self.prompt.print("Region cannot be empty. Please try again.")
                    continue
                break
        else:
            while True:
                input_endpoint = self.prompt.input(f"Enter S3 endpoint from your provider: {input_provider_name}: ")
                self.prompt.print(f"You entered endpoint: {input_endpoint}")
                if input_endpoint.strip() == "":
                    self.prompt.print("Endpoint cannot be empty. Please try again.")
                    continue
                break

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
        while True:
            self.prompt.print(
                "Please enter a profile name. The profile name can be anything you like, "
                "but it must be unique. It will be used to identify the profile in the "
                "database and in the command line interface."
            )
            input_profile_name = self.prompt.input("Enter profile name: ")

            if input_profile_name.strip() == "":
                self.prompt.print("Profile name cannot be just spaces.")
                return

            self.prompt.print(f"You entered profile name: {input_profile_name}")

            # Check if profile_name already exists
            profile = self.sqlite_handler.get_profile(profile_name=input_profile_name)

            if profile:
                self.prompt.print(f"Profile name: {input_profile_name} already exists. Please try again")
                continue
            break

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

    def show(self):
        """
        Show all profiles
        """

        # Show all profiles
        profiles = self.sqlite_handler.get_profiles()
        for profile in profiles:
            self.prompt.print("=" * 50)
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