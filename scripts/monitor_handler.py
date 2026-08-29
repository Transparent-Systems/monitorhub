"""
Abstract base class and factory for monitor handlers.

Each monitor_type (instant, backup, restore, ...) is implemented
by a subclass of MonitorHandler. Monitoring processes should obtain a handler
via MonitorHandlerFactory.create() rather than instantiating a concrete class
directly.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class MonitorHandler(ABC):
    """
    Abstract base class for all monitor handlers.

    Subclasses must implement start() and stop() and should set MONITOR_TYPE
    to the monitor_type value they are responsible for.
    """

    # Subclasses override this with the matching monitor_type value.
    MONITOR_TYPE: str = ""

    def __init__(self, monitor: dict[str, Any], profiles: list[dict[str, Any]], log_config: dict[str, Any]):
        self.monitor = monitor
        self.profiles = profiles or []
        self.log_config = log_config or {}
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def start(self) -> bool:
        """Start the monitor and return True on success."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the monitor and release resources."""


class MonitorHandlerFactory:
    """
    Factory for creating a MonitorHandler subclass based on monitor_type.

    Concrete handlers register themselves (or a callable that builds them) via
    MonitorHandlerFactory.register(). This keeps the factory extensible without
    requiring edits each time a new monitor type is added.
    """

    _handlers: dict[str, Callable[..., MonitorHandler]] = {}

    @classmethod
    def register(cls, monitor_type: str, handler_factory: Callable[..., MonitorHandler]) -> None:
        """Register a handler class or callable for a monitor_type."""
        if not monitor_type:
            raise ValueError("monitor_type must not be empty")
        cls._handlers[monitor_type] = handler_factory

    @classmethod
    def create(
        cls,
        monitor_type: str,
        monitor: dict[str, Any],
        profiles: list[dict[str, Any]],
        log_config: dict[str, Any],
    ) -> MonitorHandler:
        """Create a MonitorHandler instance for the given monitor_type."""
        handler_factory = cls._handlers.get(monitor_type)
        if handler_factory is None:
            raise ValueError(f"Unsupported monitor_type: {monitor_type!r}")
        return handler_factory(monitor=monitor, profiles=profiles, log_config=log_config)