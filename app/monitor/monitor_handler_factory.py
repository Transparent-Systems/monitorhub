from collections.abc import Callable
from typing import Any

from app.monitor.monitor_handler import MonitorHandler
from app.monitor.monitor_handler_registry import MonitorHandlerRegistry

class MonitorHandlerFactory:
    """
    Factory for creating a MonitorHandler subclass based on monitor_type.
    """

    _handlers: dict[str, Callable[..., MonitorHandler]] = MonitorHandlerRegistry.get_handlers()

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
