import logging
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

    def notify_complete(self, reason: str = "completed") -> None:
        """
        Notify the registered completion callback that the monitor has naturally finished.
        Subclasses should call this when their task lifecycle has concluded.
        """
        if self._on_complete is not None:
            self._on_complete(reason)

    @abstractmethod
    def start(self, on_complete: Callable[[str], None] | None = None) -> bool:
        """
        Start the monitor and return True on success.

        :param on_complete: Optional callback invoked when the monitor naturally completes its task.
        """

    @abstractmethod
    def stop(self) -> None:
        """Stop the monitor and release resources."""

