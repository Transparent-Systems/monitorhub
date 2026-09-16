import logging
import queue
import shlex
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from app.monitor.remote_handler import RemoteHandler
from app.monitor.remote_handler_factory import RemoteHandlerFactory
from app.monitor.remote_result import RemoteResult
from app.monitor.worker import StoppableWorker
from app.utils import reference_data
from app.utils.generic_util import convert_to_seconds

# Bounds for the number of concurrent command processes spawned by a
# CommandActionHandler. The pool bounds *concurrency* (and therefore the number
# of simultaneous child processes); it never drops events - excess commands are
# queued FIFO and executed as workers free up.
DEFAULT_COMMAND_MAX_WORKERS = 100
MIN_COMMAND_MAX_WORKERS = 1
MAX_COMMAND_MAX_WORKERS = 1000


def clamp_command_max_workers(
    value: int | str | None,
    logger: logging.Logger | None = None,
) -> int:
    """Clamp a configured ``command_max_workers`` value into the supported range.

    Returns ``DEFAULT_COMMAND_MAX_WORKERS`` when the value is missing or not a
    valid integer, and clamps out-of-range values to
    ``[MIN_COMMAND_MAX_WORKERS, MAX_COMMAND_MAX_WORKERS]`` (logging a warning).
    """
    if value is None:
        return DEFAULT_COMMAND_MAX_WORKERS
    try:
        workers = int(value)
    except (TypeError, ValueError):
        if logger is not None:
            logger.warning(
                f"Invalid command_max_workers {value!r}; using default "
                f"{DEFAULT_COMMAND_MAX_WORKERS}"
            )
        return DEFAULT_COMMAND_MAX_WORKERS

    clamped = max(MIN_COMMAND_MAX_WORKERS, min(MAX_COMMAND_MAX_WORKERS, workers))
    if logger is not None and clamped != workers:
        logger.warning(
            f"command_max_workers {workers} is out of range "
            f"[{MIN_COMMAND_MAX_WORKERS}, {MAX_COMMAND_MAX_WORKERS}]; using {clamped}"
        )
    return clamped


@dataclass
class ActionContext:
    """
    Context information for an action to be handled.
    """
    event_type: str  # e.g., "created", "deleted", "modified", "moved", "closed"
    src_path: str
    is_directory: bool
    dest_path: str | None = None  # For moved events

class ActionHandler(ABC):
    """
    Abstract base class for action handlers.
    """
    @abstractmethod
    def handle_action(self, context: ActionContext):
        pass

class DebounceManager(StoppableWorker):
    """
    Manages delayed execution of events to prevent duplicates (debouncing)
    and handle file stability waiting.

    An event is handled if:
    - The deadline is passed
    - Or the caller cancels the event and processes the event themselves.

    The worker thread blocks on a threading.Condition and is woken when a
    new event is added, an event is cancelled, or a shutdown is requested.
    This avoids busy-waiting/polling. Inherits unified lifecycle management
    from StoppableWorker.
    """
    def __init__(self, callback, logger: logging.Logger, delay: float = 2.0):
        super().__init__(name="DebounceManager", logger=logger)
        self.callback = callback
        self.delay = delay
        self.pending_files: dict[str, float] = {}  # {file_path: execute_timestamp}
        self.condition = threading.Condition()

    def _on_stop(self) -> None:
        """Wakes up the worker waiting on condition when stop is requested."""
        with self.condition:
            self.condition.notify_all()

    def add_event(self, file_path: str):
        """
        Adds a new file event with a delay deadline.
        Or updates an existing file event with a new delay deadline.
        """
        with self.condition:
            self.pending_files[file_path] = time.time() + self.delay
            self.condition.notify_all()

    def cancel_event(self, file_path: str):
        """
        Cancels a pending event for the given file path.
        """
        with self.condition:
            if file_path in self.pending_files:
                del self.pending_files[file_path]
                self.condition.notify_all()

    def _next_deadline(self) -> float | None:
        """Returns the earliest deadline among pending events, or None."""
        if not self.pending_files:
            return None
        return min(self.pending_files.values())

    def _collect_expired(self, now: float) -> list[str]:
        """Removes and returns all paths whose deadlines have passed."""
        triggered = [
            path for path, deadline in self.pending_files.items()
            if now >= deadline
        ]
        for path in triggered:
            del self.pending_files[path]
        return triggered

    def run(self):
        """Main debounce loop running in a background thread."""
        while not self.is_stopped:
            triggered_files: list[str] = []
            with self.condition:
                while not self.is_stopped:
                    now = time.time()
                    triggered_files = self._collect_expired(now)
                    if triggered_files:
                        break
                    # No expired events: wait until the next deadline or a
                    # notify (add_event / cancel_event / stop).
                    deadline = self._next_deadline()
                    if deadline is None:
                        self.condition.wait()
                    else:
                        timeout = max(deadline - now, 0.0)
                        self.condition.wait(timeout=timeout)

            # Process triggered events outside the lock.
            for path in triggered_files:
                try:
                    self.callback(path)
                except Exception as e:  # noqa: BLE001
                    self.logger.error(f"Error in DebounceManager callback for {path}: {e}")
            


class RemoteActionHandler(ActionHandler):
    """
    Action handler that executes remote sync operations for any class that extends RemoteHandler.
    """
    def __init__(
        self,
        remote_handler: RemoteHandler,
        logger: logging.Logger | None = None,
        debounce_delay: float = 1.0,
    ):
        """
        :param remote_handler: An instance of a class that extends RemoteHandler (e.g., S3Handler or RcloneHandler).
        :param logger: Optional logger instance
        :param debounce_delay: Debounce delay in seconds
        """
        if remote_handler is None:
            raise ValueError("remote_handler must be provided")
        self.remote_handler = remote_handler
        self.logger = logger or logging.getLogger(__name__)
        self.debounce_manager = DebounceManager(self._execute_copy, self.logger, delay=debounce_delay)
        self.debounce_manager.start()

    def stop(self):
        self.debounce_manager.stop()

    def handle_action(self, context: ActionContext):
        try:
            if context.event_type == "created":
                self._handle_created(context)
            elif context.event_type == "deleted":
                self._handle_deleted(context)
            elif context.event_type == "modified":
                self._handle_modified(context)
            elif context.event_type == "moved":
                self._handle_moved(context)
            elif context.event_type == "closed":
                self._handle_closed(context)
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error handling action {context.event_type} for {context.src_path}: {e}")

    def _execute_copy(self, src_path: str):
        """
        Executes the copy operation. Used by both DebounceManager and immediate calls.
        """
        self._log_if_failed(
            "Copy", src_path, self.remote_handler.copy_file(monitor_path=src_path)
        )

    def _log_if_failed(self, operation: str, path: str, result: RemoteResult) -> None:
        """Log a warning when a remote operation did not succeed."""
        if not result.ok:
            self.logger.warning(
                f"{operation} failed for {path}. Code: {result.code}. Message: {result.message}"
            )

    def _handle_created(self, context: ActionContext):
        # Intentional no-op: file copies are deferred to the modified/closed
        # events to avoid copying incomplete files. Directory creation events
        # are also ignored since empty directories are not synced.
        pass

    def _handle_deleted(self, context: ActionContext):
        # Cancel any pending debounce for this file
        self.debounce_manager.cancel_event(context.src_path)

        remote_path = self.remote_handler.get_remote_path(context.src_path)
        
        if context.is_directory:
             # watchdog typically doesn't send DirDeletedEvent but if it did:
            result = self.remote_handler.delete_folder(remote_path=remote_path)
        else:
            result = self.remote_handler.delete_file(remote_path=remote_path)
        self._log_if_failed("Delete", remote_path, result)

    def _handle_modified(self, context: ActionContext):
        if context.is_directory:
            return

        # Instead of copying immediately, add to debounce manager
        self.debounce_manager.add_event(context.src_path)

    def _handle_closed(self, context: ActionContext):
        if context.is_directory:
            return
            
        # Cancel pending debounce as we will process it now
        self.debounce_manager.cancel_event(context.src_path)

        # Execute copy immediately
        self._execute_copy(context.src_path)

    def _handle_moved(self, context: ActionContext):
        # Cancel pending debounce for the old path
        self.debounce_manager.cancel_event(context.src_path)

        dest_path = context.dest_path
        if dest_path is None:
            self.logger.warning(f"Moved event missing dest_path: {context.src_path}")
            return

        # Delete the old remote path, then copy from the new local path.
        # The delete/copy operations differ only by file vs directory.
        remote_old = self.remote_handler.get_remote_path(context.src_path)
        if context.is_directory:
            self._log_if_failed(
                "Delete", remote_old, self.remote_handler.delete_folder(remote_path=remote_old)
            )
            self._log_if_failed(
                "Copy", dest_path, self.remote_handler.copy_folder(monitor_path=dest_path)
            )
        else:
            self._log_if_failed(
                "Delete", remote_old, self.remote_handler.delete_file(remote_path=remote_old)
            )
            self._log_if_failed(
                "Copy", dest_path, self.remote_handler.copy_file(monitor_path=dest_path)
            )



class ActionDispatcher(StoppableWorker):
    """
    Dispatches actions to registered handlers in a separate thread.

    Extends StoppableWorker for standardized lifecycle management.
    Shutdown is triggered by StoppableWorker.stop(), which sets stop_event
    and invokes _on_stop() to enqueue a None sentinel, unblocking the worker
    thread waiting on queue.get().
    """
    def __init__(self, handlers: list[ActionHandler], logger: logging.Logger | None = None):
        super().__init__(name="ActionDispatcher", logger=logger)
        self.handlers = handlers
        self.queue = queue.Queue()

    def _on_stop(self) -> None:
        """Enqueues None sentinel to unblock the worker thread waiting on queue.get()."""
        self.queue.put(None)

    def queue_action(self, context: ActionContext):
        self.queue.put(context)

    def run(self):
        """Worker loop that dequeues ActionContext items and forwards them to handlers."""
        while not self.is_stopped:
            context = self.queue.get()
            try:
                if context is None:
                    # Sentinel received: shut down the worker.
                    break
                for handler in self.handlers:
                    try:
                        handler.handle_action(context)
                    except Exception as e:  # noqa: BLE001
                        self.logger.error(f"Error in handler {type(handler).__name__}: {e}")
            finally:
                self.queue.task_done()


class CommandActionHandler(ActionHandler):
    """
    Runs a shell command when a matching event occurs.

    The command template may contain placeholders that are replaced with the
    event details before execution:

        {monitor_name}  name of the monitor
        {profile_name}  name of the attached profile
        {event_name}    event type: "created", "deleted", "modified", "moved", "closed", "timer"
        {src_path}      absolute source file path

    By default the command is executed without a shell (shell=False) to avoid
    shell injection. Set shell=True (opt-in) to enable pipes/redirects.
    """

    _PLACEHOLDER_NAMES = ("monitor_name", "profile_name", "event_name", "src_path")

    def __init__(
        self,
        command: str,
        monitor_name: str = "",
        profile_name: str = "",
        events: list[str] | None = None,
        cooldown: str = "0s",
        shell: bool = False,
        timeout:  str = "60s",
        logger: logging.Logger | None = None,
        max_workers: int | str | None = None,
    ):
        if not command or not command.strip():
            raise ValueError("command must not be empty")
        self.command = command
        self.monitor_name = monitor_name
        self.profile_name = profile_name
        self.events = events or None
        self.cooldown_seconds = convert_to_seconds(cooldown)
        self.shell = bool(shell)
        self.timeout_seconds = convert_to_seconds(timeout)
        self.logger = logger or logging.getLogger(__name__)
        self.max_workers = clamp_command_max_workers(max_workers, self.logger)
        self._last_fired: float | None = None
        self._lock = threading.Lock()
        # Bounded executor guarding concurrent command processes. Created lazily
        # on first dispatch; shut down by stop(). The same lock also protects
        # the in-flight future set used for observability and clean shutdown.
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()
        self._stopped = False
        self._futures: set[Future] = set()
        self._backlog_warned = False

    def _build_values(self, context: ActionContext) -> dict[str, str]:
        return {
            "monitor_name": self.monitor_name,
            "profile_name": self.profile_name,
            "event_name": context.event_type,
            "src_path": context.src_path or "",
        }

    def _substitute_shell(self, values: dict[str, str]) -> str:
        quoted = {k: shlex.quote(v) for k, v in values.items()}
        return self.command.format(**quoted)

    def _build_argv(self, values: dict[str, str]) -> list[str]:
        try:
            tokens = shlex.split(self.command)
        except ValueError as e:
            self.logger.error(f"Invalid command template: {e}")
            return []

        formatted: list[str] = []
        for token in tokens:
            try:
                formatted.append(token.format(**values))
            except KeyError as e:
                self.logger.error(f"Unknown placeholder {e} in command template")
                return []
        return formatted

    def handle_action(self, context: ActionContext):
        if self.events and context.event_type not in self.events:
            self.logger.debug(
                f"Skipping command for event '{context.event_type}' (not in filter)"
            )
            return

        now = time.time()
        with self._lock:
            if self._last_fired is not None and self.cooldown_seconds > 0:  # noqa: SIM102
                if now - self._last_fired < self.cooldown_seconds:
                    self.logger.debug(
                        f"Command suppressed by cooldown for '{context.event_type}'"
                    )
                    return
            self._last_fired = now

        values = self._build_values(context)
        # Run the command on a bounded worker pool so the dispatcher is never
        # blocked, while capping the number of concurrent command processes.
        self._dispatch(values)

    def _dispatch(self, values: dict[str, str]) -> None:
        """Submit a command for execution without blocking the caller.

        The executor bounds concurrency only; commands are never dropped. When
        all workers are busy the command is queued (FIFO) and runs once a worker
        is free. Called under the executor lock so submission cannot race with
        :meth:`stop`.
        """
        with self._executor_lock:
            if self._stopped:
                self.logger.debug("Command dispatch ignored: handler already stopped")
                return
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.max_workers,
                    thread_name_prefix="cmd",
                )
                self.logger.debug(
                    f"Command executor started (max_workers={self.max_workers})"
                )
            future = self._executor.submit(self._run_command, values)
            self._futures.add(future)
            backlog = len(self._futures)
            if backlog > self.max_workers and not self._backlog_warned:
                # One warning per overload episode so a storm is visible without
                # flooding the log. Commands are queued in order, never dropped.
                self._backlog_warned = True
                self.logger.warning(
                    f"Command backlog: {backlog} commands queued/running "
                    f"(max_workers={self.max_workers}). Commands are queued and "
                    f"will not be dropped."
                )
        # Register the callback outside the lock: add_done_callback may invoke
        # it synchronously for an already-completed future.
        future.add_done_callback(self._on_future_done)

    def _on_future_done(self, future: Future) -> None:
        """Discard a finished future and surface any unexpected error."""
        with self._executor_lock:
            self._futures.discard(future)
            if self._backlog_warned and len(self._futures) <= self.max_workers:
                self._backlog_warned = False
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            self.logger.error(f"Command worker raised an unexpected error: {exc}")

    @property
    def pending_commands(self) -> int:
        """Number of submitted commands not yet finished (queued + running)."""
        with self._executor_lock:
            return len(self._futures)

    def stop(self, wait: bool = False, cancel_futures: bool = True) -> None:
        """Shut down the command executor.

        Defaults to ``wait=False, cancel_futures=True`` so monitor shutdown is
        not delayed by in-flight commands and queued (not yet started) commands
        are cancelled. The handler ignores further dispatches afterwards.
        """
        with self._executor_lock:
            self._stopped = True
            executor = self._executor
            self._executor = None
            self._futures.clear()
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            self.logger.debug(
                f"Command executor stopped (wait={wait}, cancel_futures={cancel_futures})"
            )

    def _run_command(self, values: dict[str, str]):
        try:
            if self.shell:
                try:
                    cmd = self._substitute_shell(values)
                except KeyError as e:
                    self.logger.error(f"Unknown placeholder {e} in command template")
                    return
                self.logger.debug(
                    f"Running command: {cmd}"
                )
                result = subprocess.run(
                    cmd,
                    shell=True,
                    timeout=self.timeout_seconds,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                argv = self._build_argv(values)
                if not argv:
                    return
                self.logger.debug(
                    f"Running command: {argv}"
                )
                result = subprocess.run(
                    argv,
                    shell=False,
                    timeout=self.timeout_seconds,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            if result.returncode != 0:
                self.logger.warning(
                    f"Command exited with code {result.returncode}: "
                    f"stdout={result.stdout!r}, stderr={result.stderr!r}"
                )
            else:
                self.logger.debug(
                    f"Command succeeded: stdout={result.stdout!r}, stderr={result.stderr!r}"
                )
        except subprocess.TimeoutExpired:
            self.logger.error(f"Command timed out after {self.timeout_seconds}s")
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error executing command: {e}")


class ActionHandlerFactory:
    """
    Factory for creating ActionHandler instances (RemoteActionHandler, CommandActionHandler)
    from profile and monitor configuration.
    Dispatches first by profile category (command vs remote), then by specific profile_type.
    """

    @classmethod
    def get_handler(
        cls,
        monitor: dict,
        profile: dict | None,
        logger: logging.Logger | None = None,
        debounce_delay: float = 1.0,
        category: str | None = None,
    ) -> ActionHandler | None:
        """
        Creates an ActionHandler instance based on profile category and profile type.

        :param monitor: Monitor dictionary containing 'path', 'remote_path', 'name', etc.
        :param profile: Profile dictionary containing 'profile_type', 'config', etc.
        :param logger: Optional logger instance.
        :param debounce_delay: Delay for debounce in remote handlers (default 1.0s).
        :param category: Optional explicit category ('command' or 'remote'). If not provided,
                         determined from profile['category'] or inferred from profile_type.
        :return: ActionHandler (RemoteActionHandler or CommandActionHandler) or None if unsupported.
        """
        logger = logger or logging.getLogger(__name__)
        if not profile:
            return None

        profile_type = profile.get("profile_type", "").strip()

        # 1. Determine category (explicit parameter > profile field > inferred from profile_type)
        resolved_category = category or profile.get("category")
        if not resolved_category:
            resolved_category = reference_data.get_profile_category(profile_type)

        # 2. Dispatch by category
        if resolved_category == "command":
            return cls._create_command_handler(
                monitor=monitor,
                profile=profile,
                profile_type=profile_type,
                logger=logger,
            )
        if resolved_category == "remote":
            return cls._create_remote_handler(
                monitor=monitor,
                profile=profile,
                logger=logger,
                debounce_delay=debounce_delay,
            )

        logger.warning(
            f"Unknown profile category '{resolved_category}' for profile '{profile.get('name')}'"
        )
        return None

    @classmethod
    def _create_command_handler(
        cls,
        monitor: dict,
        profile: dict,
        profile_type: str,
        logger: logging.Logger,
    ) -> ActionHandler | None:
        """
        Creates a CommandActionHandler for command category profiles.
        """
        config_obj = profile.get("config")
        cfg: dict = config_obj if isinstance(config_obj, dict) else {}

        cmd = profile.get("command") or cfg.get("command", "")
        cmd_str = cmd.strip() if isinstance(cmd, str) else ""
        if not cmd_str:
            logger.warning(
                f"Profile '{profile.get('name')}' is a command profile ({profile_type}) but has no 'command' configured"
            )
            return None

        events = cfg.get("command_events", "")
        cooldown = cfg.get("command_cooldown", "0s")
        shell = cfg.get("command_shell", False)
        timeout = cfg.get("command_timeout", 60.0)
        max_workers = cfg.get("command_max_workers", DEFAULT_COMMAND_MAX_WORKERS)

        return CommandActionHandler(
            command=cmd_str,
            monitor_name=monitor.get("name", ""),
            profile_name=profile.get("name", ""),
            events=events,
            cooldown=cooldown,
            shell=bool(shell),
            timeout=timeout,
            logger=logger,
            max_workers=max_workers,
        )

    @classmethod
    def _create_remote_handler(
        cls,
        monitor: dict,
        profile: dict,
        logger: logging.Logger,
        debounce_delay: float,
    ) -> ActionHandler | None:
        """
        Creates a RemoteActionHandler for remote category profiles.
        """
        monitor_path = monitor.get("monitor_path") or monitor.get("path", "")
        remote_path = monitor.get("remote_path", "")
        remote_handler = RemoteHandlerFactory.get_handler(
            monitor_path=monitor_path,
            remote_path=remote_path,
            profile=profile,
            logger=logger,
        )
        return RemoteActionHandler(
            remote_handler=remote_handler,
            logger=logger,
            debounce_delay=debounce_delay,
        )
