"""
Scheduled monitor handler.

Executes backup and restore operations for a monitor on a schedule.

Backup and restore differ only in the direction of the file flow:
- "backup":  local source -> remote destination
- "restore": remote destination -> local source

The `direction` parameter selects between them, so the same class handles both.
"""

import time

from app.monitor.action_handler import (
    ActionContext,
    ActionHandlerFactory,
)
from app.monitor.monitor_handler import MonitorHandler
from app.monitor.remote_handler_factory import RemoteHandlerFactory
from app.monitor.worker import PeriodicWorker, StoppableWorker
from app.utils import reference_data
from app.utils.constants import MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE
from app.utils.generic_util import convert_to_seconds


class _OneOffWorker(StoppableWorker):
    """Worker for executing a one-off task on a stoppable background thread."""

    def __init__(self, action, on_complete=None, name: str | None = None, logger=None):
        super().__init__(name=name, logger=logger)
        self.action = action
        self.on_complete = on_complete

    def run(self) -> None:
        try:
            if not self.is_stopped:
                self.action()
        finally:
            if not self.is_stopped and self.on_complete:
                self.on_complete("one-off task finished")


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
        self.worker: StoppableWorker | None = None
        self.command_handlers = self._build_command_handlers()

    def start(self, on_complete=None) -> bool:
        """
        Starts the backup/restore task.

        :param on_complete: Optional callback invoked when a one-off task finishes.
        """
        if on_complete is not None:
            self._on_complete = on_complete

        # (Re)build command handlers so that a restart after stop() works:
        # stop() shuts down and clears the cached handlers.
        self.command_handlers = self._build_command_handlers()

        monitor_config = self.monitor.get("config", {})
        if not monitor_config:
            self.logger.debug(
                f"{self.direction.capitalize()} for monitor '{self.monitor_name}' "
                f"not configured. {self.direction.capitalize()} is disabled."
            )
            return True

        raw_interval = monitor_config.get("interval", "0")
        interval_seconds = convert_to_seconds(raw_interval)
        self.logger.debug(
            f"[{self.monitor_name}] {self.direction.capitalize()} interval is "
            f"{interval_seconds} seconds"
        )

        worker_name = f"Scheduled-{self.monitor_name}"

        if interval_seconds == 0:
            self.logger.debug(
                f"[{self.monitor_name}] Performing one-off {self.direction}."
            )
            self.worker = _OneOffWorker(
                action=lambda: self._perform_operation(reason="one-off (interval 0)"),
                on_complete=self.notify_complete,
                name=worker_name,
                logger=self.logger,
            )
        else:
            self.logger.debug(
                f"[{self.monitor_name}] {self.direction.capitalize()} scheduled "
                f"every {interval_seconds} seconds."
            )
            self.worker = PeriodicWorker(
                interval=interval_seconds,
                action=lambda: self._perform_operation(reason="scheduled"),
                name=worker_name,
                logger=self.logger,
                initial_delay=False,
            )

        self.worker.start()
        return True

    def stop(self) -> None:
        """
        Stops the backup/restore task.
        """
        if self.worker is not None:
            self.worker.stop(timeout=2.0)
            self.worker = None

        # Shut down command handlers (each owns a bounded command executor).
        for handler in self.command_handlers.values():
            handler_stop = getattr(handler, "stop", None)
            if callable(handler_stop):
                handler_stop()
        self.command_handlers = {}

        # Join the completion-notification thread, if one was spawned.
        self._join_completion_thread()

    def _build_command_handlers(self) -> dict:
        """
        Build (and cache) a CommandActionHandler for each command profile.

        Handlers are built once so that per-handler state (e.g. cooldown)
        persists across scheduled ticks, and are reused for every timer event.
        """
        handlers = {}
        for profile in self.profiles or []:
            category = reference_data.get_profile_category(
                profile_type=profile.get("profile_type", "")
            )
            if category != reference_data.PROFILE_CATEGORY_COMMAND:
                continue
            handler = ActionHandlerFactory.get_handler(
                monitor=self.monitor,
                profile=profile,
                logger=self.logger,
            )
            handlers[profile.get("name")] = handler
        return handlers

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
            # Handler depends on profile category: command or remote
            profile_type = profile.get("profile_type", "")
            category = reference_data.get_profile_category(profile_type=profile_type)
            self.logger.debug(
                f"[{monitor_name}] Using profile '{profile.get('name')}' for {self.direction}."
            )

            if category == "remote":
                remote_handler = RemoteHandlerFactory.get_handler(
                    logger=self.logger,
                    monitor_path=monitor_path,
                    remote_path=remote_path,
                    profile=profile,
                    exclude_patterns=self.exclude_patterns,
                )

                if remote_handler is None:
                    self.logger.error(
                        f"[{monitor_name}] Could not instantiate handler for {self.direction}."
                    )
                    return

                if self.direction == MONITOR_TYPE_BACKUP:
                    result = remote_handler.copy_folder(monitor_path=monitor_path)
                else:
                    result = remote_handler.restore_folder(remote_path=remote_path)

                if result.ok:
                    self.logger.debug(f"[{monitor_name}] Finished {self.direction} folder copy.")
                else:
                    self.logger.error(
                        f"[{monitor_name}] {self.direction} failed "
                        f"(kind={result.kind}, code={result.code}): {result.message}"
                    )
            elif category == "command":
                command_handler = self.command_handlers.get(profile.get("name"))
                if command_handler is None:
                    self.logger.error(
                        f"Profile {profile.get('name')} could not be instantiated by ActionHandlerFactory"
                    )
                    continue
                # Fire the handler directly; CommandActionHandler runs the
                # command asynchronously on its own thread without blocking.
                action_context = ActionContext(
                    event_type="timer",
                    src_path=monitor_path,
                    dest_path=remote_path,
                    is_directory=True
                )
                command_handler.handle_action(action_context)
            else:
                self.logger.warning(f"Unknown profile category: {category}")