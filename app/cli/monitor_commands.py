"""Monitor subcommands for MonitorHub."""

import datetime
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from app.cli.prompt_service import PromptService
from app.utils import reference_data
from app.utils.constants import (
    MONITOR_STATUS_RUNNING,
    MONITOR_STATUS_STOP,
    MONITOR_STATUS_STOPPED,
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)
from app.utils.generic_util import find_by_id, is_interval_valid
from app.utils.sqlite_handler import SQLiteHandler

STALE_HEARTBEAT_SECONDS = 60


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

    @staticmethod
    def _resolve_python_interpreter(script_dir: Path) -> str:
        """Return the Python interpreter used to launch monitor child processes.

        Prefer the project's virtual environment (.venv) so child processes run
        with the same interpreter and installed dependencies. Falls back to the
        currently running interpreter when the venv is not found.
        """
        if sys.platform == "win32":
            venv_python = script_dir / ".venv" / "Scripts" / "python.exe"
        else:
            venv_python = script_dir / ".venv" / "bin" / "python3"

        return str(venv_python) if venv_python.exists() else sys.executable

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _heartbeat_age_seconds(heartbeat: str | None) -> float | None:
        """Return the age of a heartbeat in seconds, or None if missing/unparseable."""
        if not heartbeat:
            return None
        try:
            heartbeat_dt = datetime.datetime.strptime(heartbeat, "%Y-%m-%d %H:%M:%S%z")
                
        except (ValueError, TypeError):
            return None
        heartbeat_dt = heartbeat_dt.replace(tzinfo=datetime.UTC)
        now = datetime.datetime.now(datetime.UTC)
        return (now - heartbeat_dt).total_seconds()

    def _force_kill_process(self, pid: int, name: str) -> bool:
        """Send SIGKILL to a process and return whether it is now dead.

        Returns True if the process was killed or was already gone.
        Returns False on PermissionError (process still alive).
        """
        try:
            os.kill(pid, signal.SIGKILL)
            self.prompt.print(f"Sent SIGKILL to monitor '{name}' (pid={pid}).")
            return True
        except ProcessLookupError:
            self.prompt.print(f"Monitor '{name}' process (pid={pid}) not found — may have already exited.")
            return True
        except PermissionError:
            self.prompt.print(f"Permission denied when sending SIGKILL to monitor '{name}' (pid={pid}).")
            return False

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
                self._force_kill_process(pid, monitor_name)

            self.sqlite_handler.update_monitor_status(monitor_id=monitor_id_val, status=MONITOR_STATUS_STOPPED)
            self.sqlite_handler.update_monitor_pid(monitor_id=monitor_id_val, pid=0)
            stale_monitors.append(monitor)

        return stale_monitors

    def _select_monitor_interactive(
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

        while True:
            self.prompt.print()
            if allow_all:
                self.prompt.print("0.  Select all monitors")
            for monitor in monitors:
                self.prompt.print(
                    f"Id: {monitor.get('id', 'N/A')}, Monitor name: {monitor.get('name', 'N/A')}"
                )

            choice = self.prompt.input(prompt).strip()
            if choice == "":
                return None

            if allow_all and choice == "0":
                return 0

            if not choice.isdigit():
                self.prompt.print(f"Invalid monitor id: {choice}. Please try again.")
                continue

            choice_int = int(choice)
            if find_by_id(monitors, choice_int) is not None:
                return choice_int

            self.prompt.print(f"Invalid monitor id: {choice_int}. Please try again.")

    def _prompt_interval(self, current_interval: str | None = None, monitor_type: str | None = None) -> str:
        """Prompt the user for a monitor interval and return the normalized value."""
        label = f"{monitor_type} interval" if monitor_type else "interval"
        while True:
            if current_interval is not None:
                self.prompt.print(f"Current {label}: {current_interval}")
                self.prompt.print(f"Press Enter to keep current {label}")
                input_interval = self.prompt.input(f"Enter {label}: ").strip()
                if input_interval == "":
                    return current_interval
            else:
                self.prompt.print(
                    "Interval is in minutes(m), hours(h) or days(d). "
                    "Default is minutes. For example 10m means 10 minutes."
                )
                input_interval = self.prompt.input(f"Please enter {label}: ").strip()
                if input_interval == "":
                    self.prompt.print("Interval cannot be just spaces")
                    continue

            if not is_interval_valid(input_interval):
                self.prompt.print(
                    f"\nInvalid interval: '{input_interval}'. "
                    "Interval must be a non-negative number with an optional unit (e.g. 10, 10s, 10m, 2h, 1d).\n"
                )
                continue

            return input_interval + "m" if input_interval.isdigit() else input_interval

    def _prompt_exclude_patterns(self, current: list[str] | None = None) -> list[str]:
        """Prompt for comma-separated exclude patterns and return them as a list.

        Applies to all monitor types. An empty response means either
        "keep current patterns" (when editing) or "no exclusions" (when new).
        """
        while True:
            if current:
                self.prompt.print(f"Current exclude patterns: {', '.join(current)}")
                self.prompt.print("Press Enter to keep current exclude patterns")
            else:
                self.prompt.print("Leave empty (press Enter) for no exclusions.")

            raw = self.prompt.input(
                "Enter exclude patterns (comma-separated, e.g. *.log, .git): "
            ).strip()

            if raw == "":
                return current if current else []

            patterns = [p.strip() for p in raw.split(",") if p.strip()]
            if not patterns:
                self.prompt.print("No valid patterns entered. Please try again.")
                continue

            return patterns

    def _launch_monitor_process(self, monitor: dict) -> bool:
        """Launch run_monitor.py for a single monitor as a detached child process.

        Returns True on success, False on failure.
        """
        import os as _os

        monitor_id_val: int = monitor.get("id", 0)
        monitor_name = monitor.get("name", "N/A")

        project_root = Path(_os.path.join(_os.path.dirname(__file__), "../")).resolve()
        run_monitor_script = project_root / "monitor" / "run_monitor.py"
        python = self._resolve_python_interpreter(project_root)

        child_env = None
        if getattr(sys, "frozen", False):
            cmd = [
                sys.executable,
                "run-monitor",
                "--monitor-id", str(monitor_id_val),
                "--db-dir", str(self.db_dir),
                "--log", self.log_config,
            ]
            if self.log_level:
                cmd += ["--log-level", self.log_level]
            child_env = _os.environ.copy()
            for key in list(child_env.keys()):
                if key.startswith("_PYI_") or key in (
                    "LD_LIBRARY_PATH",
                    "DYLD_LIBRARY_PATH",
                ):
                    child_env.pop(key, None)
        else:
            cmd = [
                python,
                str(run_monitor_script),
                "--monitor-id", str(monitor_id_val),
                "--db-dir", str(self.db_dir),
                "--log", self.log_config,
            ]
            if self.log_level:
                cmd += ["--log-level", self.log_level]

        try:
            logs_dir = Path.cwd() / "logs"
            logs_dir.mkdir(exist_ok=True)
            error_log = logs_dir / f"monitor_{monitor_id_val}.log"
            with open(error_log, "a") as error_log_fh:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=error_log_fh,
                    start_new_session=True,
                    env=child_env,
                )
        except Exception as e:  # noqa: BLE001
            self.prompt.print(f"Failed to start monitor '{monitor_name}' (id={monitor_id_val}): {e}")
            return False

        return True

    # ------------------------------------------------------------------
    # edit helpers
    # ------------------------------------------------------------------

    def _edit_basic_fields(self, monitor: dict) -> None:
        """Edit name, monitor_path, remote_path, and monitor_type on a monitor dict."""
        # Monitor name
        while True:
            self.prompt.print(f"Current monitor name: {monitor.get('name', 'N/A')}")
            self.prompt.print("Press Enter to keep current monitor name")
            input_monitor_name = self.prompt.input("Enter new monitor name: ")
            if input_monitor_name.strip() == "":
                break
            monitor["name"] = input_monitor_name
            break

        # Monitor path
        while True:
            self.prompt.print(f"Current monitor path: {monitor.get('monitor_path', 'N/A')}")
            self.prompt.print("Press Enter to keep current monitor path")
            input_monitor_path = self.prompt.input("Enter new monitor path: ")
            if input_monitor_path.strip() == "":
                break
            monitor["monitor_path"] = input_monitor_path
            break

        # Remote path
        while True:
            self.prompt.print(f"Current remote path: {monitor.get('remote_path', 'N/A')}")
            self.prompt.print("Press Enter to keep current remote path")
            input_remote_path = self.prompt.input("Enter new remote path: ")
            if input_remote_path.strip() == "":
                break
            monitor["remote_path"] = input_remote_path
            break

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

            while delete_profiles:
                self.prompt.print("\nProfiles to delete (leave blank to skip):")
                for pid, v in delete_profiles.items():
                    self.prompt.print(f"Id: {pid}, Profile name: {v.get('name', 'N/A')}")

                input_delete_id = self.prompt.input("Enter profile id to delete (or press Enter to continue): ")
                if input_delete_id.strip() == "":
                    break

                if not input_delete_id.isdigit():
                    self.prompt.print(f"Invalid profile id: {input_delete_id}. Please try again.")
                    continue

                profile_id_to_delete = int(input_delete_id)
                if profile_id_to_delete not in delete_profiles:
                    self.prompt.print(f"Invalid profile id: {profile_id_to_delete}. Please try again.")
                    continue

                profile_to_delete = delete_profiles[profile_id_to_delete]

                if self.sqlite_handler.delete_monitor_profile_map(
                    monitor_id=monitor_id, profile_id=profile_id_to_delete
                ):
                    self.prompt.print(f"Profile '{profile_to_delete.get('name', 'N/A')}' removed from monitor")
                    monitor_profiles.remove(profile_to_delete)
                    del delete_profiles[profile_id_to_delete]
                else:
                    self.prompt.print(f"Failed to remove profile '{profile_to_delete.get('name', 'N/A')}'")

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
            self.prompt.print("\nAvailable profiles to add:")
            while available_profiles:
                for pid, v in available_profiles.items():
                    self.prompt.print(
                        f"Id: {pid}, Profile name: {v.get('name', 'N/A')}, Profile type: {v.get('profile_type', 'N/A')}"
                    )

                input_add_id = self.prompt.input("Enter profile id to add (or press Enter to skip): ")
                if input_add_id.strip() == "":
                    break

                if not input_add_id.isdigit():
                    self.prompt.print(f"Invalid profile id: {input_add_id}. Please try again.")
                    continue

                profile_id_to_add = int(input_add_id)
                if profile_id_to_add not in available_profiles:
                    self.prompt.print(f"Invalid profile id: {profile_id_to_add}. Please try again.")
                    continue

                profile_to_add = available_profiles[profile_id_to_add]

                if self.sqlite_handler.add_monitor_profile_map(
                    monitor_id=monitor_id, profile_id=profile_id_to_add
                ):
                    self.prompt.print(f"Profile '{profile_to_add.get('name', 'N/A')}' added to monitor")
                    current_profile_ids.add(profile_id_to_add)
                    del available_profiles[profile_id_to_add]
                else:
                    self.prompt.print(f"Failed to add profile '{profile_to_add.get('name', 'N/A')}'")

                if not available_profiles:
                    self.prompt.print("All profiles have been added.")
                    break

                input_continue = self.prompt.input("Do you want to add another profile? (y/N): ")
                if input_continue.strip().lower() in ("y", "yes"):
                    continue
                else:
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

        choice = self._select_monitor_interactive(monitors=monitors)
        if choice is None:
            self.prompt.print("No monitor selected")
            return

        monitor = find_by_id(monitors, choice)
        if monitor is None:
            self.prompt.print(f"Monitor with id={choice} not found.")
            return
        self.prompt.print(f"You want to delete monitor: {monitor.get('name', 'N/A')}")

        while True:
            confirm = self._select_monitor_interactive(
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
            choice = self._select_monitor_interactive(monitors=monitors)
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

        while True:
            self.prompt.print("Please enter monitor name")
            input_monitor_name = self.prompt.input("Enter monitor name: ")
            if input_monitor_name.strip() == "":
                self.prompt.print("Monitor name cannot be just spaces.")
                return
            self.prompt.print(f"You entered monitor name: {input_monitor_name}")
            monitor = self.sqlite_handler.get_monitor(monitor_name=input_monitor_name)
            if monitor:
                self.prompt.print(f"Monitor name: {input_monitor_name} already exists. Please try again")
                continue
            break

        while True:
            input_monitor_path = self.prompt.input("Please enter monitor path: ")
            if input_monitor_path.strip() == "":
                self.prompt.print("monitor path cannot be just spaces.")
                return
            self.prompt.print(f"You entered monitor path: {input_monitor_path}")
            break

        while True:
            input_remote_path = self.prompt.input("Please enter remote path: ")
            if input_remote_path.strip() == "":
                self.prompt.print("Remote path cannot be just spaces.")
                return
            self.prompt.print(f"You entered remote path: {input_remote_path}")
            break

        monitor_types = reference_data.MONITOR_TYPES
        if not monitor_types:
            self.prompt.print("No monitor types available")
            return

        while True:
            for i, (name, description) in enumerate(monitor_types):
                self.prompt.print(f"{i+1}. {name} - {description}")

            input_monitor_type_number = self.prompt.input("Please select number of monitor type: ")
            if input_monitor_type_number.strip() == "":
                self.prompt.print("Monitor type cannot be just spaces")

            if not input_monitor_type_number.isdigit():
                self.prompt.print(f"Invalid monitor type number: {input_monitor_type_number}. Please try again.")
                continue

            input_monitor_type_number = int(input_monitor_type_number)
            if input_monitor_type_number > 0 and input_monitor_type_number <= len(monitor_types):
                break

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

        while True:
            if not unselected_profiles:
                self.prompt.print("All profiles have been selected.")
                break

            self.prompt.print("Profiles:")
            for pid, v in unselected_profiles.items():
                self.prompt.print(
                    f"Id: {pid}, Profile name: {v.get('name', 'N/A')}, Profile type: {v.get('profile_type', 'N/A')}"
                )

            input_profile_id = self.prompt.input("Please select profile id (or press Enter to finish): ")
            if input_profile_id.strip() == "":
                break

            if not input_profile_id.isdigit():
                self.prompt.print(f"Invalid profile id: {input_profile_id}. Please try again.")
                continue

            profile_id = int(input_profile_id)
            if profile_id not in unselected_profiles:
                self.prompt.print(f"You entered an invalid profile id: {profile_id}")
                continue

            self.prompt.print(f"You entered profile id: {profile_id}")
            chosen = unselected_profiles[profile_id]
            selected_profiles.append(chosen)
            del unselected_profiles[profile_id]

            if len(unselected_profiles) == 0:
                self.prompt.print("All profiles have been selected.")
                break

            input_continue = self.prompt.input("Do you want to add another profile? (y/N): ")
            if input_continue.strip().lower() in ("y", "yes"):
                continue
            else:
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
        else:
            self.prompt.print(f"Monitor name: {input_monitor_name} created")
            for i in range(len(selected_profiles)):
                profile = selected_profiles[i]
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
            self.prompt.print("=" * 50)
            self.prompt.print(f"Monitor id: {monitor.get('id', '0')}")
            self.prompt.print(f"Monitor name: {monitor.get('name', 'N/A')}")
            self.prompt.print(f"Monitor type: {monitor.get('monitor_type', 'N/A')}")
            self.prompt.print(f"Monitor path: {monitor.get('monitor_path', 'N/A')}")
            self.prompt.print(f"Remote path: {monitor.get('remote_path', 'N/A')}")
            self.prompt.print(f"Status: {monitor.get('status', 'N/A')}")
            config = monitor.get("config", {})
            for key in config:
                self.prompt.print(f"   {key}: {config.get(key, 'N/A')}")
            self.prompt.print("=" * 50)

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
            choice = self._select_monitor_interactive(monitors=monitors, allow_all=True)
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
        """Start a single monitor as a detached child process."""
        if monitor_id is not None and monitor_name is not None:
            self.prompt.print("Cannot specify both --monitor-id and --monitor-name.")
            return

        if monitor_id is None and monitor_name is None:
            monitors = self.sqlite_handler.get_monitors()
            if not monitors:
                self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
                return

            self.prompt.print("\nList of monitors")
            choice = self._select_monitor_interactive(monitors=monitors)
            if choice is None:
                self.prompt.print("Nothing selected")
                return
            monitor = find_by_id(monitors, choice)
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

        if not monitor:
            if monitor_id is not None:
                self.prompt.print(f"Monitor {monitor_id} not found.")
            elif monitor_name is not None:
                self.prompt.print(f"Monitor '{monitor_name}' not found.")
            else:
                self.prompt.print("Monitor not found.")
            return

        monitor_id_val: int = monitor.get("id", 0)
        monitor_name = monitor.get("name", "N/A")

        if monitor.get("status") == MONITOR_STATUS_RUNNING:
            self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) is already running.")
            return
        
        if self._launch_monitor_process(monitor):
            self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) started.")

    def start_all(self):
        """Clean up stale/hung monitors and start all monitors that are not running."""
        monitors = self.sqlite_handler.get_monitors()
        if not monitors:
            self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
            return

        to_start = self._cleanup_stale_monitors(monitors)
        to_start.extend(m for m in monitors if m.get("status") != MONITOR_STATUS_RUNNING)

        if not to_start:
            self.prompt.print("All monitors are already running.")
            return

        self.prompt.print(f"Starting {len(to_start)} monitor(s)...")

        for monitor in to_start:
            monitor_id_val: int = monitor.get("id", 0)
            monitor_name = monitor.get("name", "N/A")

            if self._launch_monitor_process(monitor):
                self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) started.")
            else:
                self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) failed to start.")

        self.prompt.print(f"Processed {len(to_start)} monitor(s)...")

    def stop(self, monitor_id: int | None = None, immediate: bool = False, monitor_name: str | None = None):
        """Stop a running monitor (gracefully or force-kill)."""
        if monitor_id is not None and monitor_name is not None:
            self.prompt.print("Cannot specify both --monitor-id and --monitor-name.")
            return

        monitors = self.sqlite_handler.get_monitors()
        if not monitors:
            self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
            return

        if monitor_id is None and monitor_name is None:
            self.prompt.print("\nList of monitors")
            choice = self._select_monitor_interactive(monitors=monitors, allow_all=True)
            if choice is None:
                self.prompt.print("Nothing selected")
                return

            if choice == 0:
                selected_monitors = monitors
            else:
                monitor = find_by_id(monitors, choice)
                if monitor is None:
                    self.prompt.print(f"Monitor with id={choice} not found.")
                    return
                selected_monitors = [monitor]
        elif monitor_id is not None:
            monitor = self.sqlite_handler.get_monitor(monitor_id=monitor_id)
            if not monitor:
                self.prompt.print(f"Monitor with id={monitor_id} not found.")
                return
            selected_monitors = [monitor]
        else:
            monitor = self.sqlite_handler.get_monitor(monitor_name=monitor_name)
            if not monitor:
                self.prompt.print(f"Monitor with name='{monitor_name}' not found.")
                return
            selected_monitors = [monitor]

        for monitor in selected_monitors:
            if monitor is None: # This should not happen. Check is here to avoid Pylance warnings.
                self.prompt.print("Monitor not found — skipping.")
                continue

            monitor_id_val: int = monitor.get("id", 0)

            if not monitor_id_val:
                self.prompt.print("Monitor has no valid ID — skipping.")
                continue

            monitor_name = monitor.get("name", "N/A")
            current_status = monitor.get("status", "N/A")
            current_pid = monitor.get("pid", 0)

            if current_status == MONITOR_STATUS_STOPPED:
                self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) is already stopped.")
                continue

            if immediate:
                if current_pid and current_pid != 0:
                    if not self._force_kill_process(current_pid, str(monitor_name)):
                        continue
                else:
                    self.prompt.print(f"Monitor '{monitor_name}' has no stored PID — cannot force kill.")

                self.sqlite_handler.update_monitor_status(monitor_id=monitor_id_val, status=MONITOR_STATUS_STOPPED)
                self.sqlite_handler.update_monitor_pid(monitor_id=monitor_id_val, pid=0)
                self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) status set to 'stopped'.")
            else:
                self.sqlite_handler.update_monitor_status(monitor_id=monitor_id_val, status=MONITOR_STATUS_STOP)
                self.prompt.print(f"Stop signal sent to monitor '{monitor_name}' (id={monitor_id_val}).")
                self.prompt.print("The monitor will gracefully shut down within ~10 seconds and set status to 'stopped'.")

    def stop_all(self, immediate: bool = False):
        """Stop all running monitors."""
        monitors = self.sqlite_handler.get_monitors()
        if not monitors:
            self.prompt.print(f"No monitors found in {self.sqlite_handler.db_path}")
            return

        running_monitors = [m for m in monitors if m.get("status") == MONITOR_STATUS_RUNNING]
        if not running_monitors:
            self.prompt.print("No running monitors found.")
            return

        self.prompt.print(f"Stopping {len(running_monitors)} running monitor(s)...")

        for monitor in running_monitors:
            monitor_id_val: int = monitor.get("id", 0)
            if not monitor_id_val:
                self.prompt.print("Monitor has no valid ID — skipping.")
                continue
            monitor_name = monitor.get("name", "N/A")
            current_pid = monitor.get("pid", 0)

            if immediate:
                if current_pid and current_pid != 0:
                    if not self._force_kill_process(current_pid, str(monitor_name)):
                        continue
                else:
                    self.prompt.print(f"Monitor '{monitor_name}' has no stored PID — cannot force kill.")

                self.sqlite_handler.update_monitor_status(monitor_id=monitor_id_val, status=MONITOR_STATUS_STOPPED)
                self.sqlite_handler.update_monitor_pid(monitor_id=monitor_id_val, pid=0)
                self.prompt.print(f"Monitor '{monitor_name}' (id={monitor_id_val}) status set to 'stopped'.")
            else:
                self.sqlite_handler.update_monitor_status(monitor_id=monitor_id_val, status=MONITOR_STATUS_STOP)
                self.prompt.print(f"Stop signal sent to monitor '{monitor_name}' (id={monitor_id_val}).")
                self.prompt.print("  The monitor will gracefully shut down within ~10 seconds and set status to 'stopped'.")

        self.prompt.print(f"All {len(running_monitors)} running monitor(s) have been processed.")