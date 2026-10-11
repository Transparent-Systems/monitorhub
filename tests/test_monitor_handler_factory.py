"""
Unit tests for MonitorHandlerFactory and MonitorHandlerRegistry.

Covers create() dispatch, the built-in registrations, and the explicit
register()/unregister() extension API. Also pins that the factory reads the
registry at create() time (not via a class-definition-time alias) and that
get_handlers() returns a defensive copy.
"""

import unittest

from app.monitor.instant_monitor_handler import InstantMonitorHandler
from app.monitor.monitor_handler import MonitorHandler
from app.monitor.monitor_handler_factory import MonitorHandlerFactory
from app.monitor.monitor_handler_registry import MonitorHandlerRegistry
from app.monitor.scheduled_monitor_handler import ScheduledMonitorHandler
from app.utils.constants import (
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)


class _FakeHandler(MonitorHandler):
    """Minimal handler used to verify registry extension without heavy setup."""

    MONITOR_TYPE = "_fake"

    def start(self, on_complete=None) -> bool:
        return True

    def stop(self) -> None:
        pass


class TestMonitorHandlerFactory(unittest.TestCase):
    def test_create_instant_returns_instant_monitor_handler(self):
        handler = MonitorHandlerFactory.create(
            monitor_type=MONITOR_TYPE_INSTANT,
            monitor={"name": "test"},
            profiles=[],
            log_config={},
        )
        self.assertIsInstance(handler, InstantMonitorHandler)

    def test_create_backup_returns_scheduled_handler_with_direction(self):
        handler = MonitorHandlerFactory.create(
            monitor_type=MONITOR_TYPE_BACKUP,
            monitor={"name": "test"},
            profiles=[],
            log_config={},
        )
        self.assertIsInstance(handler, ScheduledMonitorHandler)
        assert isinstance(handler, ScheduledMonitorHandler)
        self.assertEqual(handler.direction, MONITOR_TYPE_BACKUP)

    def test_create_restore_returns_scheduled_handler_with_direction(self):
        handler = MonitorHandlerFactory.create(
            monitor_type=MONITOR_TYPE_RESTORE,
            monitor={"name": "test"},
            profiles=[],
            log_config={},
        )
        self.assertIsInstance(handler, ScheduledMonitorHandler)
        assert isinstance(handler, ScheduledMonitorHandler)
        self.assertEqual(handler.direction, MONITOR_TYPE_RESTORE)

    def test_create_unknown_type_raises_value_error(self):
        with self.assertRaises(ValueError):
            MonitorHandlerFactory.create(
                monitor_type="unknown",
                monitor={},
                profiles=[],
                log_config={},
            )

    def test_handler_registered_after_import_is_picked_up_at_create_time(self):
        MonitorHandlerRegistry.register(_FakeHandler.MONITOR_TYPE, _FakeHandler)
        try:
            handler = MonitorHandlerFactory.create(
                monitor_type=_FakeHandler.MONITOR_TYPE,
                monitor={},
                profiles=[],
                log_config={},
            )
            self.assertIsInstance(handler, _FakeHandler)
        finally:
            MonitorHandlerRegistry.unregister(_FakeHandler.MONITOR_TYPE)

        with self.assertRaises(ValueError):
            MonitorHandlerFactory.create(
                monitor_type=_FakeHandler.MONITOR_TYPE,
                monitor={},
                profiles=[],
                log_config={},
            )


class TestMonitorHandlerRegistry(unittest.TestCase):
    def test_builtins_are_registered(self):
        self.assertTrue(MonitorHandlerRegistry.is_registered(MONITOR_TYPE_INSTANT))
        self.assertTrue(MonitorHandlerRegistry.is_registered(MONITOR_TYPE_BACKUP))
        self.assertTrue(MonitorHandlerRegistry.is_registered(MONITOR_TYPE_RESTORE))
        self.assertFalse(MonitorHandlerRegistry.is_registered("unknown"))

    def test_register_empty_type_raises(self):
        with self.assertRaises(ValueError):
            MonitorHandlerRegistry.register("", _FakeHandler)

    def test_get_handler_returns_registered_factory(self):
        self.assertIs(
            MonitorHandlerRegistry.get_handler(MONITOR_TYPE_INSTANT),
            InstantMonitorHandler,
        )
        self.assertIsNone(MonitorHandlerRegistry.get_handler("unknown"))

    def test_get_handlers_returns_a_defensive_copy(self):
        snapshot = MonitorHandlerRegistry.get_handlers()
        snapshot.pop(MONITOR_TYPE_INSTANT, None)
        snapshot["_injected"] = _FakeHandler

        # Mutating the returned mapping must not affect the registry.
        self.assertTrue(MonitorHandlerRegistry.is_registered(MONITOR_TYPE_INSTANT))
        self.assertNotIn("_injected", MonitorHandlerRegistry.get_handlers())
        self.assertFalse(MonitorHandlerRegistry.is_registered("_injected"))


if __name__ == "__main__":
    unittest.main()