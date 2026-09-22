"""Interactive list-selection collaborators for monitor and profile commands.

These isolate the "show a list and ask the user to pick an entry" behaviour
from the command handlers, so the handlers focus on what to do with the
selection rather than how it is prompted for.
"""

from __future__ import annotations

from typing import Any

from app.cli.prompt_service import PromptService
from app.utils.generic_util import find_by_id
from app.utils.sqlite_handler import SQLiteHandler


class MonitorSelector:
    """Prompt the user to pick a monitor from a displayed list."""

    def __init__(self, sqlite_handler: SQLiteHandler, prompt: PromptService) -> None:
        self.sqlite_handler = sqlite_handler
        self.prompt = prompt

    def select_interactive(
        self,
        monitors: list[dict] | None = None,
        allow_all: bool = False,
        prompt: str = "Enter monitor id: ",
    ) -> int | None:
        """Display a list of monitors (by id) and prompt the user to select one.

        Returns the id of the selected monitor, ``0`` when *allow_all* is True
        and the user chose "all", or ``None`` when the user entered an empty
        string (cancel).
        """
        if monitors is None:
            monitors = self.sqlite_handler.get_monitors()
            if not monitors:
                self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
                return None

        def render() -> None:
            self.prompt.print()
            if allow_all:
                self.prompt.print("0.  Select all monitors")
            for monitor in monitors:
                self.prompt.print(
                    f"Id: {monitor.get('id', 'N/A')}, Monitor name: {monitor.get('name', 'N/A')}"
                )

        def valid(value: str) -> str | None:
            if not value.isdigit():
                return f"Invalid monitor id: {value}. Please try again."
            if find_by_id(monitors, int(value)) is None:
                return f"Invalid monitor id: {int(value)}. Please try again."
            return None

        choice = self.prompt.prompt_choice(
            prompt,
            valid=valid,
            render=render,
            allow_all=allow_all,
            allow_cancel=True,
        )
        if choice is None:
            return None
        return int(choice)


class ProfileSelector:
    """Prompt the user to pick a profile from a displayed list."""

    def __init__(self, sqlite_handler: SQLiteHandler, prompt: PromptService) -> None:
        self.sqlite_handler = sqlite_handler
        self.prompt = prompt

    def select_interactive(self) -> dict[str, Any]:
        """Show all profiles and let user choose one.

        Returns the selected profile as a dictionary, or an empty dictionary
        when there are no profiles or the user cancels.
        """
        # Get all profiles
        profiles = self.sqlite_handler.get_profiles()
        if not profiles:
            self.prompt.print(f"No profiles found in {self.sqlite_handler.db_path}")
            return {}

        def render() -> None:
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
            render=render,
            allow_cancel=True,
            echo_label="profile id",
        )
        if profile_id_entered is None:
            self.prompt.print("No profile selected")
            return {}

        selected = find_by_id(profiles, int(profile_id_entered))
        return selected if selected is not None else {}


class ProfileImportSelector:
    """Prompt the user to pick rclone profiles to import from a displayed list.

    Unlike :class:`ProfileSelector`, the candidates are rclone config section
    names that are not in the database yet: they have no profile id, so they are
    addressed by their 1-based position in the list. The user can select none
    (press Enter), all (enter ``0``), or individual entries one after another.
    """

    def __init__(self, prompt: PromptService) -> None:
        self.prompt = prompt

    def select_interactive(
        self,
        profile_names: list[str],
        prompt: str = (
            "Enter profile number to import. Enter 0 to select all. "
            "To stop press Enter: "
        ),
    ) -> list[str]:
        """Show the importable profiles and return the names the user chose.

        Returns an empty list when there is nothing to import or the user
        cancels (presses Enter before choosing anything).
        """
        remaining = list(profile_names)
        if not remaining:
            return []

        selected: list[str] = []

        def render() -> None:
            self.prompt.print("\nProfiles to import from Rclone:")
            self.prompt.print("0.  Select all profiles")
            for index, name in enumerate(remaining, start=1):
                self.prompt.print(f"{index}. {name}")

        def valid(value: str) -> str | None:
            if not value.isdigit():
                return f"Invalid profile number: {value}. Please try again."
            if int(value) not in range(1, len(remaining) + 1):
                return f"Invalid profile number: {int(value)}. Please try again."
            return None

        while remaining:
            choice = self.prompt.prompt_choice(
                prompt,
                valid=valid,
                render=render,
                allow_all=True,
                allow_cancel=True,
            )
            if choice is None:
                break
            if choice == "0":
                selected.extend(remaining)
                remaining.clear()
                break

            selected.append(remaining.pop(int(choice) - 1))
            if not remaining:
                self.prompt.print("All profiles selected.")
                break

        return selected
