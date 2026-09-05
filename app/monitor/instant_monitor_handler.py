"""
Instant monitor handler.

Monitors a folder for changes and immediately triggers an upload for each
change event to the destination storage (cloud storage, FTP server, etc).
"""

import logging
import threading
import time
from pathlib import Path

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
    FileClosedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from app.monitor.action_handler import (
    ActionContext,
    ActionDispatcher,
    ActionHandlerFactory,
)
from app.utils.constants import MONITOR_TYPE_INSTANT
from app.monitor.monitor_handler import MonitorHandler

from app.utils.path_filter import is_excluded

class MonitorEventHandler(FileSystemEventHandler):
    """
    A class to handle file system events.
    It is used by the watchdog library to monitor a folder for changes.
    """

    # These are instance attributes, defined here with type hints for clarity
    # and static analysis. They will be initialized in __init__.
    action_dispatcher: ActionDispatcher
    logger: logging.Logger
    exclude_patterns: list[str]

    def __init__(
        self, action_dispatcher: ActionDispatcher, monitor_config: dict, logger: logging.Logger | None = None
    ):
        super().__init__()
        self.action_dispatcher = action_dispatcher
        self.exclude_patterns = (monitor_config.get("config") or {}).get("exclude_patterns", [])
        self.logger = logger or logging.getLogger(__name__)
        self.event_time: dict[str, float] = {}  # Dictionary to store event times
        self.event_time_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
        self.cleanup_thread.start()
        self.logger.debug("MonitorEventHandler initialized")

    def stop(self):
        """Stops the cleanup worker thread."""
        self.stop_event.set()
        if self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=2)

    def _cleanup_worker(self):
        """Periodically removes event times older than 1 minute."""
        while not self.stop_event.is_set():
            # wait() returns True if the flag is set (stop requested),
            # and False if the timeout expires (time to run cleanup).
            if self.stop_event.wait(60):
                break

            now = time.time()
            cutoff = now - 60

            with self.event_time_lock:
                keys_to_remove = [k for k, v in self.event_time.items() if v < cutoff]
                for k in keys_to_remove:
                    self.logger.debug(f"Removing event time for {k}")
                    del self.event_time[k]

    def on_any_event(self, event):
        """
        Catch-all event handler for any file system event.

        This method is primarily used for debugging purposes to log all
        events that occur, regardless of their type. It does not perform
        any specific actions based on the event.

        Args:
            event (FileSystemEvent): The event object representing the file system change.
        """
        self.logger.debug(f"on_any_event: Event type: {event.event_type}  Path: {event.src_path}")

    def on_created(self, event):
        """
        Handles file and directory creation events.

        For directory creation, the actual copy operation is postponed to the
        `on_modified` event, as directory creation often implies subsequent
        file additions. For file creation, the copy is also postponed to
        `on_modified` or `on_closed` for reliability with large files.

        Args:
            event (FileSystemEvent): The creation event object.
        """

        if is_excluded(event.src_path, self.exclude_patterns):
            self.logger.debug(
                f"Path excluded: src_path='{event.src_path}', event.is_directory={event.is_directory}, event_type={event.event_type}, type(event)={type(event).__name__}"
            )
            return

        # Queue the action
        context = ActionContext(
            event_type="created",
            src_path=event.src_path,
            is_directory=event.is_directory
        )
        self.action_dispatcher.queue_action(context)

        if event.is_directory:
            self.logger.debug(f"on_created: folder '{event.src_path}'; create postponed to on_modified event")
        else:
            # If the event is a file creation, we copy the specific file
            self.logger.debug(
                f"on_created: file '{event.src_path}'; create postponed to on_modified event"
            )

    def on_deleted(self, event):
        """
        Handles file and directory deletion events.
        """
        # Log the deletion event with the source path
        self.logger.debug(f"on_deleted: src_path='{event.src_path}'")

        if is_excluded(event.src_path, self.exclude_patterns):
            self.logger.debug(
                f"Path excluded: src_path='{event.src_path}', event.is_directory={event.is_directory}, event_type={event.event_type}, type(event)={type(event).__name__}"
            )
            return

        context = ActionContext(
            event_type="deleted",
            src_path=event.src_path,
            is_directory=event.is_directory
        )
        self.action_dispatcher.queue_action(context)

        return

    def on_modified(self, event):
        """
        Handles FileModifiedEvent events.
        """

        now = time.time()
        with self.event_time_lock:
            if event.src_path in self.event_time:
                time_diff = now - self.event_time[event.src_path]
            else:
                time_diff = 0
            self.event_time[event.src_path] = now
        # Convert now into hh:mm:ss
        time_diff_ms = int(time_diff * 1000)    # Convert to milliseconds

        self.logger.debug(
            # Log the modification event details.
            f"on_modified: time_diff_ms={time_diff_ms} ,  src_path='{event.src_path}', event.is_directory={event.is_directory}, event_type={event.event_type}"
        )

        if is_excluded(event.src_path, self.exclude_patterns):
            self.logger.debug(
                f"Path excluded: src_path='{event.src_path}', event.is_directory={event.is_directory}, event_type={event.event_type}, type(event)={type(event).__name__}"
            )
            return

        if not event.is_directory:
            context = ActionContext(
                event_type="modified",
                src_path=event.src_path,
                is_directory=event.is_directory
            )
            self.action_dispatcher.queue_action(context)

    def on_closed(self, event) -> None:
        """
        Handles FileClosedEvent
        """

        if is_excluded(event.src_path, self.exclude_patterns):
            self.logger.debug(
                f"Path excluded: src_path='{event.src_path}', event.is_directory={event.is_directory}, event_type={event.event_type}, type(event)={type(event).__name__}"
            )
            return

        # Check if the file still exists. It might have been deleted right after closing.
        if not Path(event.src_path).exists() or event.is_directory:
            return

        # Log the closed event details.
        self.logger.debug(
            f"on_closed: src_path='{event.src_path}', event.is_directory={event.is_directory}, event_type={event.event_type}, type(event)={type(event).__name__}"
        )

        context = ActionContext(
            event_type="closed",
            src_path=event.src_path,
            is_directory=event.is_directory
        )
        self.action_dispatcher.queue_action(context)

    def on_moved(self, event):
        """
        Handles file and directory move/rename events.
        """

        if is_excluded(event.src_path, self.exclude_patterns):
            self.logger.debug(
                f"Path excluded: src_path='{event.src_path}', event.is_directory={event.is_directory}, event_type={event.event_type}, type(event)={type(event).__name__}"
            )
            return

        # Log the move/rename event, showing both old and new paths.
        self.logger.debug(
            f"on_moved - renamed from {event.src_path} to {event.dest_path}"
        )

        context = ActionContext(
            event_type="moved",
            src_path=event.src_path,
            is_directory=event.is_directory,
            dest_path=event.dest_path
        )
        self.action_dispatcher.queue_action(context)


class InstantMonitorHandler(MonitorHandler):
    """
    Manages the lifecycle of a file system observer to monitor a specified folder
    for changes and instantly trigger remote operations based on those changes.
    """

    MONITOR_TYPE = MONITOR_TYPE_INSTANT

    def __init__(self, monitor, profiles, log_config):
        super().__init__(monitor=monitor, profiles=profiles, log_config=log_config)
        self.debounce_delay = 1.0
        self.observer = None
        self.action_dispatcher = None
        self.event_handler = None
        self.action_handlers: list = []

        self.monitor_path = monitor.get("monitor_path", "")
        self.remote_path = monitor.get("remote_path", "")
        self.exclude_patterns = (monitor.get("config") or {}).get("exclude_patterns", [])

        self.logger.debug("InstantMonitorHandler: exiting __init__")

    def start(self) -> bool:
        """
        Starts monitoring the specified folder for changes.

        Initializes an `RcloneHandler` and `MonitorEventHandler`, then schedule
        the observer to monitor the `monitor_path` recursively, filtering out
        `DirModifiedEvent` to reduce noise.
        """

        # If no remote profiles are specified, log an error and exit.
        if not self.profiles:
            self.logger.error(
                f"No remote profiles specified for monitor '{self.monitor.get('name')}' (id={self.monitor.get('id')}). Exiting."
            )
            return False

        # Instantiate ActionHandlers for each linked profile via ActionHandlerFactory.
        # Factory either returns a remote profile action handler or a command profile action handler
        # The remote profile categories are mutually exclusive
        action_handlers = []
        for profile in self.profiles:
            handler = ActionHandlerFactory.get_handler(
                monitor=self.monitor,
                profile=profile,
                logger=self.logger,
            )
            if handler is not None:
                action_handlers.append(handler)
            else:
                self.logger.error(
                    f"Profile {profile.get('name')} could not be instantiated by ActionHandlerFactory"
                )
                continue

        self.action_handlers = action_handlers
        self.action_dispatcher = ActionDispatcher(handlers=action_handlers, logger=self.logger)
        self.action_dispatcher.start()
        self.event_handler = MonitorEventHandler(
            action_dispatcher=self.action_dispatcher,
            monitor_config=self.monitor,
            logger=self.logger
        )
        self.observer = Observer()

        # Define the event filter:
        # Include all event types except DirModifiedEvent.
        # This means on_modified will only be called for FileModifiedEvent.
        # on_created, on_deleted, on_moved will still work for both files and directories.
        event_types_to_monitor = [
            FileCreatedEvent,
            FileDeletedEvent,
            FileModifiedEvent,
            FileMovedEvent,
            FileClosedEvent,
            DirCreatedEvent,
            DirDeletedEvent,
            DirMovedEvent,
            # DirModifiedEvent, # <--- DO NOT INCLUDE THIS IF YOU WANT TO FILTER OUT FOLDER ACCESS CHANGES (e.g., access time changes)
            # IMPORTANT: Exclude DirModifiedEvent if you don't want folder access_time changes or other non-content
            # directory modifications to trigger on_modified. Including it can lead to excessive events.
            # If you uncomment the next line, DirModifiedEvent will be included in the events processed.
        ]

        self.observer.schedule(
            event_handler=self.event_handler,
            path=self.monitor_path,
            recursive=True,
            event_filter=event_types_to_monitor,
        )

        self.observer.start()
        # For the inotify backend, the kernel watch is registered synchronously by
        # this point, so the observer is genuinely listening now.
        # The original `threading.current_thread().ident` in log message has been removed 
        # as it is the *main* thread, not the observer thread
        # The observer runs on its own daemon threads
        self.logger.info(f"Observer '{self.observer.name}' is now listening on '{self.monitor_path}'")

        return True

    def stop(self):
        """
        Stops the file system observer.
        """
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.logger.info("Monitor stopped.")
            self.observer = None

        if self.event_handler is not None:
            self.event_handler.stop()
            self.event_handler = None

        if self.action_dispatcher is not None:
            self.action_dispatcher.stop()
            self.action_dispatcher = None

        # Stop any action handlers that support graceful shutdown
        # (e.g. RemoteActionHandler stops its DebounceManager thread).
        for handler in self.action_handlers:
            if hasattr(handler, "stop"):
                handler.stop()
        self.action_handlers = []