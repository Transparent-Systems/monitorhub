import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class MonitorHandler(ABC):
    """
    Abstract base class and factory for monitor handlers.

    Each monitor_type (instant, backup, restore, ...) is implemented
    by a subclass of MonitorHandler. Monitoring processes should obtain a handler
    via MonitorHandlerFactory.create() rather than instantiating a concrete class
    directly.
    """

    # Subclasses override this with the matching monitor_type value.
    MONITOR_TYPE: str = ""

    def __init__(self, monitor: dict[str, Any], profiles: list[dict[str, Any]], log_config: dict[str, Any]):
        self.monitor = monitor
        self.profiles = profiles or []
        self.log_config = log_config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self._on_complete: Callable[[str], None] | None = None
        self._completion_thread: threading.Thread | None = None

    def notify_complete(self, reason: str = "completed") -> None:
        """
        Notify the registered completion callback that the monitor has naturally finished.
        Subclasses should call this when their task lifecycle has concluded.
        The callback is dispatched asynchronously on a separate daemon thread to decouple
        completion handling (which may invoke stop() or join()) from the worker thread.
        The thread is tracked so it can be joined on shutdown.
        """
        if self._on_complete is not None:
            callback = self._on_complete
            thread = threading.Thread(
                target=callback,
                args=(reason,),
                name=f"{self.__class__.__name__}-completion",
                daemon=True,
            )
            self._completion_thread = thread
            thread.start()

    def _join_completion_thread(self, timeout: float = 2.0) -> None:
        """Best-effort join of the completion-notification thread (if any).

        Safe to call from any thread and when no notification was sent. Skipped
        when called from the notification thread itself to avoid a self-join.
        """
        thread = self._completion_thread
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.is_alive()
        ):
            thread.join(timeout=timeout)
        self._completion_thread = None

    @abstractmethod
    def start(self, on_complete: Callable[[str], None] | None = None) -> bool:
        """
        Start the monitor and return True on success.

        :param on_complete: Optional callback invoked when the monitor naturally completes its task.
        """

    @abstractmethod
    def stop(self) -> None:
        """Stop the monitor and release resources."""

