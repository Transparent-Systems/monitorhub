from collections.abc import Callable
from typing import ClassVar

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
    This class maintains a mapping of monitor_type to the corresponding MonitorHandler subclass or factory function.
    A new montor handler can be registered by adding an entry to the _handlers dictionary. 
    """

    from app.monitor.instant_monitor_handler import InstantMonitorHandler
    from app.monitor.scheduled_monitor_handler import ScheduledMonitorHandler

    _handlers: ClassVar[dict[str, Callable[..., MonitorHandler]]] = {}
    _handlers[MONITOR_TYPE_INSTANT] = InstantMonitorHandler
    _handlers[MONITOR_TYPE_BACKUP] = lambda monitor, profiles, log_config: ScheduledMonitorHandler(
         monitor, profiles, log_config, direction=MONITOR_TYPE_BACKUP
     )
    _handlers[MONITOR_TYPE_RESTORE] = lambda monitor, profiles, log_config: ScheduledMonitorHandler(
         monitor, profiles, log_config, direction=MONITOR_TYPE_RESTORE
     )

    @classmethod
    def get_handlers(cls) -> dict[str, Callable[..., MonitorHandler]]:
        """Return the registered monitor handlers."""
        return cls._handlers    

