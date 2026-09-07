from collections.abc import Callable
from typing import Any

from app.utils.constants import (
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)

from app.monitor.monitor_handler import MonitorHandler
class MonitorHandlerFactory:
    """
    Factory for creating a MonitorHandler subclass based on monitor_type.

    Concrete handlers register themselves (or a callable that builds them) via
    MonitorHandlerFactory.register().
    The current implementation requires that the concrete handler class be imported in this module to register itself.
    TODO: create a central registry for monitor handlers to avoid the need for imports in this module.
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


# Register built-in monitor handlers. The concrete handler imports live here
# (after the base class and factory are defined) to avoid circular imports, and
# registration is explicit — mirroring RemoteHandlerFactory. Adding a new monitor
# type means adding a subclass plus one register() call below.
from app.monitor.instant_monitor_handler import InstantMonitorHandler
from app.monitor.scheduled_monitor_handler import ScheduledMonitorHandler

MonitorHandlerFactory.register(MONITOR_TYPE_INSTANT, InstantMonitorHandler)
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