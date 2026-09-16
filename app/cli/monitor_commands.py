"""Monitor subcommands for MonitorHub."""

import datetime
import logging
import time

from app.cli.monitor_process_manager import MonitorProcessManager
from app.cli.prompt_service import PromptService
from app.cli.selectors import MonitorSelector
from app.utils import reference_data
from app.utils.constants import (
    MONITOR_STATUS_RUNNING,
    MONITOR_STATUS_STOP,
    MONITOR_STATUS_STOPPED,
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)
from app.utils.generic_util import (
    find_by_id,
    is_interval_valid,
    parse_timestamp,
)
from app.utils.sqlite_handler import SQLiteHandler

STALE_HEARTBEAT_SECONDS = 60

# Time to wait for a monitor process to exit after a graceful stop is requested
# before escalating to SIGTERM/SIGKILL. The monitor's status poller interval is
# ~10s, so this allows one comfortable poll cycle plus teardown.
STOP_GRACE_SECONDS = 15


class MonitorCommands:
    """Monitor CRUD, start/stop, test, and lifecycle commands."""

    def __init__(
        self,
        sqlite_handler: SQLiteHandler,
        logger: logging.Logger,
        db_dir: str,
        log_config: str,
        log_level: str | None,
        prompt: PromptService,
    ) -> None:
        self.sqlite_handler = sqlite_handler
        self.logger = logger
        self.db_dir = db_dir
        self.log_config = log_config
        self.log_level = log_level
        self.prompt = prompt
        # Process mechanics (launch/track/kill/reap) live in a collaborator so
        # this class stays focused on commands, database state, and prompts.
        self.processes = MonitorProcessManager(
            logger=logger,
            db_dir=db_dir,
            log_config=log_config,
            log_level=log_level,
            prompt=prompt,
        )
        # Interactive list selection is delegated to a focused collaborator.
        self.selector = MonitorSelector(sqlite_handler=sqlite_handler, prompt=prompt)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _heartbeat_age_seconds(heartbeat: str | None) -> float | None:
        """Return the age of a heartbeat in seconds, or None if missing/unparseable.

        The heartbeat is written by the monitor process (run_monitor) using the
        shared ``TIMESTAMP_FORMAT``, so parsing must use the same format.
        """
        heartbeat_dt = parse_timestamp(heartbeat)
        if heartbeat_dt is None:
            return None
        now = datetime.datetime.now(datetime.UTC)
        return (now - heartbeat_dt).total_seconds()

    def _cleanup_stale_monitors(self, monitors: list[dict]) -> list[dict]:
        """Detect and stop stale/hung running monitors, returning them for restart."""
        stale_monitors: list[dict] = []

        for monitor in monitors:
            if monitor.get("status") != MONITOR_STATUS_RUNNING:
                continue

            monitor_id_val: int = monitor.get("id", 0)
            monitor_name = monitor.get("name", "N/A")
            pid = monitor.get("pid", 0)
            age = self._heartbeat_age_seconds(monitor.get("last_heartbeat"))

            if age is not None and age <= STALE_HEARTBEAT_SECONDS:
                continue

            if age is None:
                self.prompt.print(
                    f"Stale monitor '{monitor_name}' (id={monitor_id_val}) has no "
                    f"recent heartbeat. Forcing stop and restart..."
                )
            else:
                self.prompt.print(
                    f"Stale monitor '{monitor_name}' (id={monitor_id_val}) heartbeat "
                    f"is {age:.0f}s old. Forcing stop and restart..."
                )

            if pid:
                self.processes.force_kill(pid, monitor_name)

            self.sqlite_handler.update_monitor_status(monitor_id=monitor_id_val, status=MONITOR_STATUS_STOPPED)
            self.sqlite_handler.update_monitor_pid(monitor_id=monitor_id_val, pid=0)
            self.processes.reap(monitor_id_val)
            stale_monitors.append(monitor)

        return stale_monitors

    def _prompt_interval(self, current_interval: str | None = None, monitor_type: str | None = None) -> str:
        """Prompt the user for a monitor interval and return the normalized value."""
        label = f"{monitor_type} interval" if monitor_type else "interval"

        def render() -> None:
            if current_interval is not None:
                self.prompt.print(f"Current {label}: {current_interval}")
                self.prompt.print(f"Press Enter to keep current {label}")
            else:
                self.prompt.print(
                    "Interval is in minutes(m), hours(h) or days(d). "
                    "Default is minutes. For example 10m means 10 minutes."
                )

        def valid(value: str) -> str | None:
            if not is_interval_valid(value):
                return (
                    f"\nInvalid interval: '{value}'. "
                    "Interval must be a non-negative number with an optional unit (e.g. 10, 10s, 10m, 2h, 1d).\n"
                )
            return None

        prompt_text = (
            f"Enter {label}: " if current_interval is not None else f"Please enter {label}: "
        )
        input_interval = self.prompt.prompt_required(
            prompt_text,
            current=current_interval,
            empty_message="Interval cannot be just spaces",
            validator=valid,
            render=render,
        )
        if input_interval is None:  # Defensive: there is no cancel path here.
            return current_interval or ""
        return input_interval + "m" if input_interval.isdigit() else input_interval

    def _prompt_exclude_patterns(self, current: list[str] | None = None) -> list[str]:
        """Prompt for comma-separated exclude patterns and return them as a list.

        Applies to all monitor types. An empty response means either
        "keep current patterns" (when editing) or "no exclusions" (when new).
        """
        def render() -> None:
            if current:
                self.prompt.print(f"Current exclude patterns: {', '.join(current)}")
                self.prompt.print("Press Enter to keep current exclude patterns")
            else:
                self.prompt.print("Leave empty (press Enter) for no exclusions.")

        def parse(value: str) -> list[str]:
            return [p.strip() for p in value.split(",") if p.strip()]

        def valid(value: str) -> str | None:
            if not parse(value):
                return "No valid patterns entered. Please try again."
            return None

        raw = self.prompt.prompt_required(
            "Enter exclude patterns (comma-separated, e.g. *.log, .git): ",
            allow_cancel=True,
            validator=valid,
            render=render,
        )
        if raw is None:
            return current if current else []
        return parse(raw)

    # ------------------------------------------------------------------
    # edit helpers
    # ------------------------------------------------------------------

    def _edit_basic_fields(self, monitor: dict) -> None:
        """Edit name, monitor_path, remote_path, and monitor_type on a monitor dict."""
        # Monitor name
        def render_monitor_name() -> None:
            self.prompt.print(f"Current monitor name: {monitor.get('name', 'N/A')}")
            self.prompt.print("Press Enter to keep current monitor name")

        new_monitor_name = self.prompt.prompt_required(
            "Enter new monitor name: ",
            current=monitor.get("name"),
            allow_cancel=True,
            render=render_monitor_name,
        )
        if new_monitor_name:
            monitor["name"] = new_monitor_name

        # Monitor path
        def render_monitor_path() -> None:
            self.prompt.print(f"Current monitor path: {monitor.get('monitor_path', 'N/A')}")
            self.prompt.print("Press Enter to keep current monitor path")

        new_monitor_path = self.prompt.prompt_required(
            "Enter new monitor path: ",
            current=monitor.get("monitor_path"),
            allow_cancel=True,
            render=render_monitor_path,
        )
        if new_monitor_path:
            monitor["monitor_path"] = new_monitor_path

        # Remote path
        def render_remote_path() -> None:
            self.prompt.print(f"Current remote path: {monitor.get('remote_path', 'N/A')}")
            self.prompt.print("Press Enter to keep current remote path")

        new_remote_path = self.prompt.prompt_required(
            "Enter new remote path: ",
            current=monitor.get("remote_path"),
            allow_cancel=True,
            render=render_remote_path,
        )
        if new_remote_path:
            monitor["remote_path"] = new_remote_path

        # Monitor type
        monitor_types = reference_data.MONITOR_TYPES
        if not monitor_types:
            self.prompt.print("No monitor types available")
            return

        self.prompt.print("List of monitor types")
        self.prompt.print("=" * 50)
        for i, (name, description) in enumerate(monitor_types):
            self.prompt.print(f"{i+1}. {name} - {description}")
        self.prompt.print("=" * 50)
        self.prompt.print(f"Current monitor type: {monitor.get('monitor_type', 'N/A')}")
        self.prompt.print("Press Enter to keep current monitor type")
        input_monitor_type = self.prompt.input("Enter new monitor type: ")
        if input_monitor_type.strip() != "":
            monitor["monitor_type"] = monitor_types[int(input_monitor_type) - 1][0]

    def _edit_interval(self, monitor: dict) -> None:
        """Edit the interval config for backup/restore monitor types."""
        monitor_type = monitor.get("monitor_type", "N/A")
        if monitor_type in (MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE):
            config = monitor.get("config", {})
            if "interval" in config:
                current_interval = config.get("interval", "N/A")
                monitor["config"]["interval"] = self._prompt_interval(
                    current_interval=current_interval, monitor_type=monitor_type
                )
            else:
                monitor["config"]["interval"] = self._prompt_interval(monitor_type=monitor_type)

    def _edit_exclude_patterns(self, monitor: dict) -> None:
        """Edit the exclude_patterns config for all monitor types."""
        config = monitor.get("config") or {}
        current = config.get("exclude_patterns", [])
        config["exclude_patterns"] = self._prompt_exclude_patterns(
            current=current or None
        )
        monitor["config"] = config

    def _edit_profiles(self, monitor: dict, monitor_id: int) -> None:
        """Edit profile mappings: delete existing and add new profiles."""
        monitor_profiles = self.sqlite_handler.get_profiles_for_monitor(monitor_id=monitor_id)
        if monitor_profiles:
            self.prompt.print("\nCurrent profiles linked to this monitor:")
            for profile in monitor_profiles:
                self.prompt.print(f"  - {profile.get('name', 'N/A')} (ID: {profile.get('id', 'N/A')})")

            delete_profiles = {profile.get("id"): profile for profile in monitor_profiles}

            def render_delete_profiles() -> None:
                self.prompt.print("\nProfiles to delete (leave blank to skip):")
                for pid, v in delete_profiles.items():
                    self.prompt.print(f"Id: {pid}, Profile name: {v.get('name', 'N/A')}")

            def valid_delete_id(value: str) -> str | None:
                if not value.isdigit():
                    return f"Invalid profile id: {value}. Please try again."
                if int(value) not in delete_profiles:
                    return f"Invalid profile id: {int(value)}. Please try again."
                return None

            while delete_profiles:
                input_delete_id = self.prompt.prompt_choice(
                    "Enter profile id to delete (or press Enter to continue): ",
                    valid=valid_delete_id,
                    render=render_delete_profiles,
                    allow_cancel=True,
                )
                if input_delete_id is None:
                    break

                profile_id_to_delete = int(input_delete_id)
                profile_to_delete = delete_profiles[profile_id_to_delete]

                if self.sqlite_handler.delete_monitor_profile_map(
                    monitor_id=monitor_id, profile_id=profile_id_to_delete
                ):
                    self.prompt.print(f"Profile '{profile_to_delete.get('name', 'N/A')}' removed from monitor")
                    monitor_profiles.remove(profile_to_delete)
                    del delete_profiles[profile_id_to_delete]
                else:
                    self.prompt.print(
                        f"Profile '{profile_to_delete.get('name', 'N/A')}' was not mapped to this monitor"
                    )

                if not delete_profiles:
                    break

        # Add profiles
        all_profiles = self.sqlite_handler.get_profiles()
        current_profile_ids = {p.get("id") for p in monitor_profiles} if monitor_profiles else set()
        available_profiles = {
            profile.get("id"): profile
            for profile in all_profiles
            if profile.get("id") not in current_profile_ids
        }

        if available_profiles:
            def render_available_profiles() -> None:
                self.prompt.print("\nAvailable profiles to add:")
                for pid, v in available_profiles.items():
                    self.prompt.print(
                        f"Id: {pid}, Profile name: {v.get('name', 'N/A')}, Profile type: {v.get('profile_type', 'N/A')}"
                    )

            def valid_add_id(value: str) -> str | None:
                if not value.isdigit():
                    return f"Invalid profile id: {value}. Please try again."
                if int(value) not in available_profiles:
                    return f"Invalid profile id: {int(value)}. Please try again."
                return None

            while available_profiles:
                input_add_id = self.prompt.prompt_choice(
                    "Enter profile id to add. To stop just press Enter: ",
                    valid=valid_add_id,
                    render=render_available_profiles,
                    allow_cancel=True,
                )
                if input_add_id is None:
                    break

                profile_id_to_add = int(input_add_id)
                profile_to_add = available_profiles[profile_id_to_add]

                if self.sqlite_handler.add_monitor_profile_map(
                    monitor_id=monitor_id, profile_id=profile_id_to_add
                ):
                    self.prompt.print(f"Profile '{profile_to_add.get('name', 'N/A')}' added to monitor")
                    current_profile_ids.add(profile_id_to_add)
                    del available_profiles[profile_id_to_add]
                else:
                    self.prompt.print(
                        f"Profile '{profile_to_add.get('name', 'N/A')}' was already mapped to this monitor"
                    )

                if not available_profiles:
                    self.prompt.print("All profiles have been added.")
                    break

    # ------------------------------------------------------------------
    # Public monitor commands
    # ------------------------------------------------------------------

    def delete(self, monitor_id: int | None = None, monitor_name: str | None = None):
        """Delete monitor."""
        if monitor_id is not None and monitor_name is not None:
            self.prompt.print("Cannot specify both --monitor-id and --monitor-name.")
            return

        if monitor_id is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
            if not monitor:
                self.prompt.print(f"Monitor with id={monitor_id} not found.")
                return
            self._delete_monitor(monitor)
            return

        if monitor_name is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_name=monitor_name)
            if not monitor:
                self.prompt.print(f"Monitor with name='{monitor_name}' not found.")
                return
            self._delete_monitor(monitor)
            return

        monitors = self.sqlite_handler.get_monitors()
        if not monitors:
            self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
            return

        choice = self.selector.select_interactive(monitors=monitors)
        if choice is None:
            self.prompt.print("No monitor selected")
            return

        monitor = find_by_id(monitors, choice)
        if monitor is None:
            self.prompt.print(f"Monitor with id={choice} not found.")
            return
        self.prompt.print(f"You want to delete monitor: {monitor.get('name', 'N/A')}")

        while True:
            confirm = self.selector.select_interactive(
                monitors=monitors, prompt="Confirm monitor id: "
            )
            if confirm is None:
                self.prompt.print("No monitor selected")
                return

            if confirm == choice:
                break
            self.prompt.print(f"Monitor ids do not match: {choice} is not {confirm}. Please try again.")

        self._delete_monitor(monitor)

    def _delete_monitor(self, monitor: dict) -> None:
        """Delete a single monitor resolved by id or name."""
        if self.sqlite_handler.delete_monitor(monitor_id=monitor.get("id", 0)):
            self.prompt.print(f"Monitor name: {monitor.get('name', 'N/A')} deleted")
        else:
            self.prompt.print(f"Monitor name: {monitor.get('name', 'N/A')} not deleted")

    def edit(self, monitor_id: int | None = None, monitor_name: str | None = None):
        """Edit monitor."""
        if monitor_id is not None and monitor_name is not None:
            self.prompt.print("Cannot specify both --monitor-id and --monitor-name.")
            return

        if monitor_id is None and monitor_name is None:
            monitors = self.sqlite_handler.get_monitors()
            if not monitors:
                self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
                return

            self.prompt.print("\nList of monitors to edit")
            choice = self.selector.select_interactive(monitors=monitors)
            if choice is None:
                self.prompt.print("No monitor selected")
                return

            monitor = find_by_id(monitors, choice)
            if monitor is None:
                self.prompt.print(f"Monitor with id={choice} not found.")
                return
        elif monitor_id is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
            if not monitor:
                self.prompt.print(f"Monitor with id={monitor_id} not found.")
                return
        else:
            monitor = self.sqlite_handler.get_monitor(monitor_name=monitor_name)
            if not monitor:
                self.prompt.print(f"Monitor with name='{monitor_name}' not found.")
                return

        monitor_id = monitor.get("id", "N/A")
        monitor["config"] = monitor.get("config") or {}

        self._edit_basic_fields(monitor)
        self._edit_interval(monitor)
        self._edit_exclude_patterns(monitor)
        self._edit_profiles(monitor, monitor_id)

        # Update monitor
        rowid = self.sqlite_handler.update_monitor(
            monitor_id=monitor.get("id", 0),
            name=monitor.get("name", "N/A"),
            monitor_path=monitor.get("monitor_path", "N/A"),
            remote_path=monitor.get("remote_path", "N/A"),
            monitor_type=monitor.get("monitor_type", "N/A"),
            config=monitor.get("config", {}),
            status=monitor.get("status", MONITOR_STATUS_STOPPED),
        )
        if rowid is not None:
            self.prompt.print(f"Monitor name: {monitor.get('name', 'N/A')} has been updated")
        else:
            self.prompt.print(f"Monitor name: {monitor.get('name', 'N/A')} has not been updated")

    def new(self):
        """Create new monitor."""
        profiles = self.sqlite_handler.get_profiles()
        if profiles is None or len(profiles) == 0:
            self.logger.warning(f"No profiles found in {self.sqlite_handler.db_path}")
            self.logger.warning("Please add profiles first")
            return

        def valid_monitor_name(value: str) -> str | None:
            if self.sqlite_handler.get_monitor(monitor_name=value):
                return f"Monitor name: {value} already exists. Please try again"
            return None

        input_monitor_name = self.prompt.prompt_required(
            "Enter monitor name: ",
            allow_cancel=True,
            validator=valid_monitor_name,
            render=lambda: self.prompt.print("Please enter monitor name"),
            echo_label="monitor name",
        )
        if input_monitor_name is None:
            self.prompt.print("Monitor name cannot be just spaces.")
            return

        input_monitor_path = self.prompt.prompt_required(
            "Please enter monitor path: ",
            allow_cancel=True,
            echo_label="monitor path",
        )
        if input_monitor_path is None:
            self.prompt.print("monitor path cannot be just spaces.")
            return

        input_remote_path = self.prompt.prompt_required(
            "Please enter remote path: ",
            allow_cancel=True,
            echo_label="remote path",
        )
        if input_remote_path is None:
            self.prompt.print("Remote path cannot be just spaces.")
            return

        monitor_types = reference_data.MONITOR_TYPES
        if not monitor_types:
            self.prompt.print("No monitor types available")
            return

        def render_monitor_types() -> None:
            for i, (name, description) in enumerate(monitor_types):
                self.prompt.print(f"{i+1}. {name} - {description}")

        def valid_monitor_type(value: str) -> str | None:
            if not value.isdigit() or not (0 < int(value) <= len(monitor_types)):
                return f"Invalid monitor type number: {value}. Please try again."
            return None

        raw_monitor_type_number = self.prompt.prompt_choice(
            "Please select number of monitor type: ",
            valid=valid_monitor_type,
            render=render_monitor_types,
            empty_message="Monitor type cannot be just spaces",
        )
        if raw_monitor_type_number is None:  # Defensive: there is no cancel path here.
            return
        input_monitor_type_number = int(raw_monitor_type_number)

        self.prompt.print(f"You entered monitor type number: {input_monitor_type_number}")
        monitor_type = monitor_types[input_monitor_type_number - 1][0]
        self.prompt.print(f"You selected monitor type: {monitor_type}")
        if monitor_type in (MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE):
            monitor_config = {
                "interval": self._prompt_interval(monitor_type=monitor_type),
                "exclude_patterns": self._prompt_exclude_patterns(),
            }
        elif monitor_type == MONITOR_TYPE_INSTANT:
            monitor_config = {"exclude_patterns": self._prompt_exclude_patterns()}
        else:
            monitor_config = {}

        selected_profiles = []
        unselected_profiles: dict = {p.get("id"): p for p in profiles}

        def render_unselected_profiles() -> None:
            self.prompt.print("Profiles:")
            for pid, v in unselected_profiles.items():
                self.prompt.print(
                    f"Id: {pid}, Profile name: {v.get('name', 'N/A')}, Profile type: {v.get('profile_type', 'N/A')}"
                )

        def valid_profile_id(value: str) -> str | None:
            if not value.isdigit():
                return f"Invalid profile id: {value}. Please try again."
            if int(value) not in unselected_profiles:
                return f"You entered an invalid profile id: {int(value)}"
            return None

        while True:
            if not unselected_profiles:
                self.prompt.print("All profiles have been selected.")
                break

            raw_profile_id = self.prompt.prompt_choice(
                "Enter profile id to add. To stop just press Enter: ",
                valid=valid_profile_id,
                render=render_unselected_profiles,
                allow_cancel=True,
            )
            if raw_profile_id is None:
                break

            profile_id = int(raw_profile_id)
            self.prompt.print(f"You entered profile id: {profile_id}")
            chosen = unselected_profiles[profile_id]
            selected_profiles.append(chosen)
            del unselected_profiles[profile_id]

            if len(unselected_profiles) == 0:
                self.prompt.print("All profiles have been selected.")
                break

        monitor_id = self.sqlite_handler.add_monitor(
            name=input_monitor_name,
            monitor_path=input_monitor_path,
            remote_path=input_remote_path,
            monitor_type=monitor_types[input_monitor_type_number - 1][0],
            config=monitor_config,
            status=MONITOR_STATUS_STOPPED,
        )

        if monitor_id is None:
            self.prompt.print(f"Monitor name: {input_monitor_name} not created")
            return

        self.prompt.print(f"Monitor name: {input_monitor_name} created")
        for profile in selected_profiles:
            profile_id = profile["id"]
            self.sqlite_handler.add_monitor_profile_map(
                monitor_id=monitor_id, profile_id=profile_id
            )

    def show(self, monitor_id: int | None = None, monitor_name: str | None = None):
        """Show all monitors, or a single monitor when an id or name is given."""
        if monitor_id is not None and monitor_name is not None:
            self.prompt.print("Cannot specify both --monitor-id and --monitor-name.")
            return

        if monitor_id is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
            if not monitor:
                self.prompt.print(f"Monitor with id={monitor_id} not found.")
                return
            monitors = [monitor]
        elif monitor_name is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_name=monitor_name)
            if not monitor:
                self.prompt.print(f"Monitor with name='{monitor_name}' not found.")
                return
            monitors = [monitor]
        else:
            monitors = self.sqlite_handler.get_monitors()

        for monitor in monitors:
            self.prompt.print()
            self.prompt.print("=" * 60)
            self.prompt.print(f"Monitor id: {monitor.get('id', '0')}")
            self.prompt.print(f"Monitor pid: {monitor.get('pid', '0')}")
            self.prompt.print(f"Monitor name: {monitor.get('name', 'N/A')}")
            self.prompt.print(f"Monitor type: {monitor.get('monitor_type', 'N/A')}")
            self.prompt.print(f"Monitor path: {monitor.get('monitor_path', 'N/A')}")
            self.prompt.print(f"Remote path: {monitor.get('remote_path', 'N/A')}")
            self.prompt.print(f"Status: {monitor.get('status', 'N/A')}")
            config = monitor.get("config", {})
            for key in config:
                self.prompt.print(f"   {key}: {config.get(key, 'N/A')}")
            self.prompt.print("=" * 3)
            self.prompt.print("\tProfile list:")
            # List profiles: profile_id : profile_name
            monitor_id_str = monitor.get('id', '0')
            monitor_id = int(monitor_id_str)
            profiles = self.sqlite_handler.get_profiles_for_monitor(monitor_id=monitor_id)
            for profile in profiles:
                self.prompt.print(f"\tprofile id: {profile.get('id', '0')} ; profile name: {profile.get('name', 'UNKNOWN')}")

            self.prompt.print("=" * 60)

    def test(self, monitor_id: int | None = None, monitor_name: str | None = None):
        """Test monitor(s)."""
        from app.utils.diagnostic_util import DiagnosticUtil

        if monitor_id is not None and monitor_name is not None:
            self.prompt.print("Cannot specify both --monitor-id and --monitor-name.")
            return

        monitors = self.sqlite_handler.get_monitors()
        if not monitors:
            self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
            return

        if monitor_id is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
            if not monitor:
                self.prompt.print(f"Monitor with id={monitor_id} not found.")
                return
        elif monitor_name is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_name=monitor_name)
            if not monitor:
                self.prompt.print(f"Monitor with name='{monitor_name}' not found.")
                return
            monitor_id = monitor.get("id")
        else:
            self.prompt.print("\nList of monitors")
            choice = self.selector.select_interactive(monitors=monitors, allow_all=True)
            if choice is None:
                self.prompt.print("Nothing selected")
                return

            if choice == 0:
                self.prompt.print("Your selected all monitors")
                monitor_id = None
            else:
                monitor_id = choice

        try:
            diagnostic_util = DiagnosticUtil(
                sqlite_handler=self.sqlite_handler,
                logger=self.logger,
                prompt=self.prompt,
            )
            if not diagnostic_util.check_monitor_config(monitor_id=monitor_id):
                return
        finally:
            self.prompt.print("Monitor test completed")

    def start(self, monitor_id: int | None = None, monitor_name: str | None = None):
        """Start a single monitor, or all monitors when no id or name is given."""
        if monitor_id is not None and monitor_name is not None:
            self.prompt.print("Cannot specify both --monitor-id and --monitor-name.")
            return

        if monitor_id is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
            if not monitor:
                self.prompt.print(f"Monitor with id={monitor_id} not found.")
                return
            monitors = [monitor]
        elif monitor_name is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_name=monitor_name)
            if not monitor:
                self.prompt.print(f"Monitor with name='{monitor_name}' not found.")
                return
            monitors = [monitor]
        else:
            monitors = self.sqlite_handler.get_monitors()
            if not monitors:
                self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
                return
            # When starting all monitors, clean up stale/hung ones first so they
            # can be restarted.
            self._cleanup_stale_monitors(monitors)

        for monitor in monitors:
            self._start_monitor(monitor)

    def _start_monitor(self, monitor: dict | None) -> None:
        """Start a single monitor as a detached child process."""
        if monitor is None:  # Guard against Pylance warnings / bad callers.
            self.prompt.print("Monitor not found — skipping.")
            return

        monitor_id_val: int = monitor.get("id", 0)
        if not monitor_id_val:
            self.prompt.print("Monitor has no valid ID — skipping.")
            return

        monitor_name = monitor.get("name", "N/A")

        # A monitor is considered live when a process still holds its stored PID.
        # Checking liveness (not just the status flag) is essential because a
        # graceful stop first moves the monitor into the intermediate 'stop'
        # state while the previous process is still shutting down. Starting
        # again during that window would create a duplicate monitor process.
        current_status = monitor.get("status")
        current_pid = int(monitor.get("pid") or 0)
        pid_alive = current_pid != 0 and self.processes.is_alive(
            monitor_id_val, current_pid
        )

        if pid_alive:
            if current_status == MONITOR_STATUS_RUNNING:
                self.prompt.print(
                    f"Monitor '{monitor_name}' (id={monitor_id_val}) is already running "
                    f"(pid={current_pid})."
                )
            else:
                self.prompt.print(
                    f"Monitor '{monitor_name}' (id={monitor_id_val}) is still shutting down "
                    f"(status='{current_status}', pid={current_pid}). "
                    "Wait for it to stop, or use 'monitor stop --immediate' first."
                )
            return

        if current_status == MONITOR_STATUS_RUNNING:
            # Status says 'running' but no live process: stale entry, clean it up.
            self.prompt.print(
                f"Monitor '{monitor_name}' (id={monitor_id_val}) had a stale 'running' "
                "status with no live process; clearing it and starting."
            )
            self.sqlite_handler.update_monitor_status(
                monitor_id=monitor_id_val, status=MONITOR_STATUS_STOPPED
            )
            self.sqlite_handler.update_monitor_pid(monitor_id=monitor_id_val, pid=0)
        if self.processes.launch(monitor):
            self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) started.")

    def stop(self, monitor_id: int | None = None, immediate: bool = False, monitor_name: str | None = None):
        """Stop a single monitor, or all monitors when no id or name is given."""
        if monitor_id is not None and monitor_name is not None:
            self.prompt.print("Cannot specify both --monitor-id and --monitor-name.")
            return

        if monitor_id is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
            if not monitor:
                self.prompt.print(f"Monitor with id={monitor_id} not found.")
                return
            monitors = [monitor]
        elif monitor_name is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_name=monitor_name)
            if not monitor:
                self.prompt.print(f"Monitor with name='{monitor_name}' not found.")
                return
            monitors = [monitor]
        else:
            monitors = self.sqlite_handler.get_monitors()
            if not monitors:
                self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
                return

        graceful: list[tuple[int, str, int]] = []
        for monitor in monitors:
            entry = self._stop_monitor(monitor, immediate)
            if entry is not None:
                graceful.append(entry)

        if graceful:
            # Wait once for the whole batch against a shared deadline, then
            # escalate only the survivors, so stopping many monitors does not
            # take STOP_GRACE_SECONDS per monitor.
            deadline = time.monotonic() + STOP_GRACE_SECONDS
            for pid, name, monitor_id_val in graceful:
                remaining = max(0.0, deadline - time.monotonic())
                if self.processes.wait_for_exit(pid, remaining, monitor_id=monitor_id_val):
                    self.prompt.print(
                        f"Monitor '{name}' (id={monitor_id_val}) stopped gracefully."
                    )
                else:
                    self.prompt.print(
                        f"Monitor '{name}' (id={monitor_id_val}) did not exit within "
                        f"{STOP_GRACE_SECONDS:g}s; escalating."
                    )
                    self.processes.escalate_stop(pid, name, monitor_id_val)
                self.processes.reap(monitor_id_val)
                self.sqlite_handler.update_monitor_status(
                    monitor_id=monitor_id_val, status=MONITOR_STATUS_STOPPED
                )
                self.sqlite_handler.update_monitor_pid(monitor_id=monitor_id_val, pid=0)
                self.prompt.print(
                    f"Monitor '{name}' (id={monitor_id_val}) status set to 'stopped'."
                )

    def _stop_monitor(self, monitor: dict | None, immediate: bool) -> tuple[int, str, int] | None:
        """Stop one monitor; return graceful-stop details to wait on, or None."""
        if monitor is None:  # This should not happen. Check is here to avoid Pylance warnings.
            self.prompt.print("Monitor not found — skipping.")
            return None

        monitor_id_val: int = monitor.get("id", 0)

        if not monitor_id_val:
            self.prompt.print("Monitor has no valid ID — skipping.")
            return None

        monitor_name = monitor.get("name", "N/A")
        current_status = monitor.get("status", "N/A")
        current_pid = monitor.get("pid", 0)

        if current_status == MONITOR_STATUS_STOPPED:
            self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) is already stopped.")
            return None

        if immediate:
            if current_pid and current_pid != 0:
                if not self.processes.force_kill(current_pid, str(monitor_name)):
                    return None
            else:
                self.prompt.print(f"Monitor '{monitor_name}' has no stored PID — cannot force kill.")

            self.sqlite_handler.update_monitor_status(monitor_id=monitor_id_val, status=MONITOR_STATUS_STOPPED)
            self.sqlite_handler.update_monitor_pid(monitor_id=monitor_id_val, pid=0)
            self.processes.reap(monitor_id_val)
            self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) status set to 'stopped'.")
            return None

        self.sqlite_handler.update_monitor_status(monitor_id=monitor_id_val, status=MONITOR_STATUS_STOP)
        self.prompt.print(f"Stop signal sent to monitor '{monitor_name}' (id={monitor_id_val}).")
        if not current_pid or current_pid == 0:
            self.prompt.print(
                "No stored PID; the monitor will set status to 'stopped' when it exits."
            )
            return None
        return (int(current_pid), str(monitor_name), int(monitor_id_val))