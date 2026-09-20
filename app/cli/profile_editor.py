"""Interactive profile creation and editing flows.

Extracted from :class:`~app.cli.profile_commands.ProfileCommands` so the
command handler can focus on the test/show/delete/import commands while this
collaborator owns the multi-step interactive prompts used by ``profile new``
and ``profile edit``.
"""

from __future__ import annotations

from typing import Any

from app.cli.prompt_service import PromptService
from app.utils import reference_data
from app.utils.constants import (
    DEFAULT_COMMAND_MAX_WORKERS,
    MAX_COMMAND_MAX_WORKERS,
    MIN_COMMAND_MAX_WORKERS,
)
from app.utils.generic_util import find_by_id, is_interval_valid
from app.utils.sqlite_handler import SQLiteHandler


class ProfileEditor:
    """Interactive creation and editing flows for profiles."""

    def __init__(
        self,
        sqlite_handler: SQLiteHandler,
        prompt: PromptService,
    ) -> None:
        self.sqlite_handler = sqlite_handler
        self.prompt = prompt

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
            prompt_text += f" (current: {current_command}))"
            prompt_text += "\nEnter to keep"
        prompt_text += ": "
        command = self.prompt.prompt_required(
            prompt_text,
            current=current_command,
            empty_message="Command cannot be just spaces",
        ) or ""

        # Event filter
        valid_events = ["created", "deleted", "modified", "moved", "closed", "timer"]

        def parse_events(value: str) -> list[str]:
            return [e.strip() for e in value.split(",") if e.strip()]

        """
        Return None to indicate the valie is valid
        The string returned is the error message
        """
        def valid_events_input(value: str) -> str | None:
            if value.strip().lower() == "all":
                return None
            invalid = [e for e in parse_events(value) if e not in valid_events]
            if invalid:
                return f"Invalid event(s): {', '.join(invalid)}. Please try again."
            return None

        current_display = ",".join(current_events) if current_events else "all"
        prompt = f"\nAvailable events: {valid_events}"
        prompt += f"\nCurrent events to trigger on: {current_display}"
        if current_display != "all":
            prompt += "\nTo select all events enter: all"
        prompt += "\nTo select some events enter a list like: deleted,modified"
        prompt += "\nTo keep the current event list press Enter only"
        prompt += "\nEnter event list: "
        input_events = self.prompt.prompt_required(
            prompt=prompt,
            allow_cancel=True,
            validator=valid_events_input,
        )
        if input_events is None:
            events = current_events if (current_command and current_events is not None) else []
        elif input_events.strip().lower() ==  "all":
            events = []
        else:
            events = parse_events(input_events)

        # Cooldown
        cooldown = self.prompt.prompt_required(
            f"Cooldown between command firings (current: {current_cooldown})\nEnter to keep: ",
            default=current_cooldown if current_command else "0s",
            validator=lambda value: (
                None
                if is_interval_valid(value)
                else f"Invalid cooldown: {value}. Please try again."
            ),
        ) or "0s"

        # Timeout
        timeout = self.prompt.prompt_required(
            f"Timeout for command (current: {current_timeout})\nEnter to keep: ",
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
            f"current: {current_max_workers})\nEnter to keep: ",
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
