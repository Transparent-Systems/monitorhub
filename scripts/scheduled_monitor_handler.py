"""
Scheduled monitor handler.

Executes backup and restore operations for a monitor on a schedule.

Backup and restore differ only in the direction of the file flow:
- "backup":  local source -> remote destination
- "restore": remote destination -> local source

The `direction` parameter selects between them, so the same class handles both.
"""

import threading
import time

from scripts.remote_handler_factory import RemoteHandlerFactory
from scripts.constants import MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE
from scripts.monitor_handler import MonitorHandler, MonitorHandlerFactory
from scripts.utils.generic_util import convert_to_seconds


class ScheduledMonitorHandler(MonitorHandler):
    """
    Executes backup/restore operations for a given monitor configuration.

    This class handles both one-off and recurring operations based on the
    'interval' setting in the monitor's backup configuration.
    """

    MONITOR_TYPE = MONITOR_TYPE_BACKUP

    def __init__(self, monitor, profiles, log_config, direction=MONITOR_TYPE_BACKUP):
        super().__init__(monitor=monitor, profiles=profiles, log_config=log_config)
        if direction not in (MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE):
            raise ValueError(
                f"Unsupported backup direction: {direction!r}; "
                f"expected {MONITOR_TYPE_BACKUP!r} or {MONITOR_TYPE_RESTORE!r}"
            )
        self.direction = direction
        self.exclude_patterns = (monitor.get("config") or {}).get(
            "exclude_patterns", []
        )
        self.monitor_name = monitor.get("name")
        self.worker_thread = None
        self.stop_event = threading.Event()

    def start(self) -> bool:
        """
        Starts the backup/restore task.
        """
        self.stop_event.clear()
        self.worker_thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"Scheduled-{self.monitor_name}",
        )
        self.worker_thread.start()
        return True

    def stop(self) -> None:
        """
        Stops the backup/restore task.
        """
        self.stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2)

    def _perform_operation(self, reason="scheduled"):
        """
        Perform a backup (or restore) for this monitor configuration.
        """
        monitor_name = self.monitor["name"]
        monitor_path = self.monitor["monitor_path"]
        remote_path = self.monitor["remote_path"]

        self.logger.debug(
            f"Performing {reason} {self.direction} for monitor [{monitor_name}] "
            f"at {time.ctime()} for: {monitor_path} -> {remote_path}"
        )

        profiles = self.profiles or []

        # Iterate over profiles
        for profile in profiles:
            try:
                self.logger.debug(
                    f"[{monitor_name}] Using profile '{profile.get('name')}' for {self.direction}."
                )

                handler = RemoteHandlerFactory.get_handler(
                    logger=self.logger,
                    monitor_path=monitor_path,
                    remote_path=remote_path,
                    profile=profile,
                    exclude_patterns=self.exclude_patterns,
                )

                if handler is None:
                    self.logger.error(
                        f"[{monitor_name}] Could not instantiate handler for {self.direction}."
                    )
                    return

                if self.direction == MONITOR_TYPE_BACKUP:
                    handler.copy_folder(monitor_path=monitor_path)
                else:
                    handler.restore_folder(remote_path=remote_path)

                self.logger.debug(f"[{monitor_name}] Finished {self.direction} folder copy.")
            except Exception as e:
                self.logger.error(f"[{monitor_name}] {self.direction.capitalize()} failed: {e}")

    def _run_loop(self):
        """
        The main loop for the backup/restore task.
        """
        monitor_config = self.monitor.get("config", {})
        if not monitor_config:
            self.logger.debug(
                f"{self.direction.capitalize()} for monitor '{self.monitor_name}' "
                f"not configured. {self.direction.capitalize()} is disabled."
            )
            return

        raw_interval = monitor_config.get("interval", "0")
        interval_seconds = convert_to_seconds(raw_interval)
        self.logger.debug(
            f"[{self.monitor_name}] {self.direction.capitalize()} interval is "
            f"{interval_seconds} seconds"
        )

        if interval_seconds == 0:
            self.logger.debug(
                f"[{self.monitor_name}] Performing one-off {self.direction}."
            )
            self._perform_operation(reason="one-off (interval 0)")
            return

        # Initial operation before loop
        self.logger.debug(f"[{self.monitor_name}] Performing initial {self.direction}.")
        self._perform_operation(reason=f"initial {self.direction}")

        self.logger.debug(
            f"[{self.monitor_name}] {self.direction.capitalize()} scheduled "
            f"every {interval_seconds} seconds."
        )
        while not self.stop_event.is_set():
            # Wait for interval OR stop event
            if self.stop_event.wait(interval_seconds):
                break
            self._perform_operation(reason="scheduled")


# Register both directions to the same class, passing the direction explicitly.
MonitorHandlerFactory.register(
    MONITOR_TYPE_BACKUP,
    lambda monitor, profiles, log_config: ScheduledMonitorHandler(
        monitor, profiles, log_config, direction=MONITOR_TYPE_BACKUP
    ),
)
MonitorHandlerFactory.register(
    MONITOR_TYPE_RESTORE,
    lambda monitor, profiles, log_config: ScheduledMonitorHandler(
        monitor, profiles, log_config, direction=MONITOR_TYPE_RESTORE
    ),
)