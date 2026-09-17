from collections.abc import Callable
from typing import ClassVar

from app.monitor.instant_monitor_handler import InstantMonitorHandler
from app.monitor.monitor_handler import MonitorHandler
from app.monitor.scheduled_monitor_handler import ScheduledMonitorHandler
from app.utils.constants import (
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)


class MonitorHandlerRegistry:
    """
    Registry for monitor handlers.

    Maintains a mapping of monitor_type to the corresponding MonitorHandler
    subclass or factory callable. Extension is explicit: register a new monitor
    type via ``register()`` and ``MonitorHandlerFactory.create()`` picks it up.

    Built-in handlers are registered at the bottom of this module; adding a new
    monitor type means one ``register()`` call.
    """

    _handlers: ClassVar[dict[str, Callable[..., MonitorHandler]]] = {}

    @classmethod
    def register(
        cls, monitor_type: str, handler_factory: Callable[..., MonitorHandler]
    ) -> None:
        """Register a handler class or callable for a monitor_type."""
        if not monitor_type:
            raise ValueError("monitor_type must not be empty")
        cls._handlers[monitor_type] = handler_factory

    @classmethod
    def unregister(cls, monitor_type: str) -> None:
        """Remove a previously registered handler for monitor_type, if present."""
        cls._handlers.pop(monitor_type, None)

    @classmethod
    def get_handler(cls, monitor_type: str) -> Callable[..., MonitorHandler] | None:
        """Return the handler factory registered for monitor_type, or None."""
        return cls._handlers.get(monitor_type)

    @classmethod
    def is_registered(cls, monitor_type: str) -> bool:
        """Return True if a handler is registered for monitor_type."""
        return monitor_type in cls._handlers

    @classmethod
    def get_handlers(cls) -> dict[str, Callable[..., MonitorHandler]]:
        """Return a copy of the registered monitor handlers.

        A copy is returned so callers cannot mutate registry state through the
        returned mapping; register new handlers via ``register()``.
        """
        return dict(cls._handlers)


# Register the built-in handlers. Adding a new monitor type means adding one
# register() call here.
MonitorHandlerRegistry.register(MONITOR_TYPE_INSTANT, InstantMonitorHandler)
MonitorHandlerRegistry.register(
    MONITOR_TYPE_BACKUP,
    lambda monitor, profiles, log_config: ScheduledMonitorHandler(
        monitor, profiles, log_config, direction=MONITOR_TYPE_BACKUP
    ),
)
MonitorHandlerRegistry.register(
    MONITOR_TYPE_RESTORE,
    lambda monitor, profiles, log_config: ScheduledMonitorHandler(
        monitor, profiles, log_config, direction=MONITOR_TYPE_RESTORE
    ),
)

