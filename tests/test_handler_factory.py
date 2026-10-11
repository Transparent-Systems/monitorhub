"""Tests for the profile routing key -> handler mapping and high-level dispatch.

The mapping is a plain declarative table (:data:`handler_factory.REMOTE_HANDLERS`)
keyed by a profile's ``remote_handler`` value, with the rclone key as the
delegated fallback; ``HandlerFactory.get_handler`` turns a profile into an
ActionHandler using that table plus the command profile-type category.
"""

import unittest
from unittest import mock

from app.monitor import handler_factory
from app.monitor.action_handler import CommandActionHandler, RemoteActionHandler
from app.monitor.handler_factory import HandlerFactory, get_remote_handler
from app.monitor.rclone_handler import RcloneHandler
from app.monitor.remote_handler import RemoteHandler
from app.monitor.s3_handler import S3Handler
from app.utils import reference_data


class _FakeRemoteHandler(RemoteHandler):
    """Minimal native handler used to verify table dispatch without boto3.

    It deliberately declares no ``PROFILE_TYPE`` so the mapping guard test does
    not expect it in the table; tests inject it under an explicit key.
    """

    def __init__(
        self,
        base_monitor_path,
        base_remote_path,
        profile_config,
        logger=None,
        exclude_patterns=None,
    ):
        self.base_monitor_path = base_monitor_path
        self.base_remote_path = base_remote_path
        self.profile_config = profile_config
        self.logger = logger
        self.exclude_patterns = exclude_patterns or []

    def get_remote_path(self, monitor_path: str) -> str:
        return monitor_path

    def file_exists(self, remote_path: str):
        return None

    def copy_file(self, monitor_path: str, remote_path: str | None = None):
        return None

    def copy_folder(self, monitor_path: str):
        return None

    def restore_folder(self, remote_path: str):
        return None

    def delete_file(self, remote_path: str):
        return None

    def delete_folder(self, remote_path: str):
        return None


def _remote_handler_subclasses() -> list[type]:
    """Return every loaded ``RemoteHandler`` subclass, direct and indirect."""
    queue = list(RemoteHandler.__subclasses__())
    found: list[type] = []
    while queue:
        cls = queue.pop()
        found.append(cls)
        queue.extend(cls.__subclasses__())
    return found


class TestRemoteHandlerMapping(unittest.TestCase):
    def test_s3_maps_to_s3_handler(self):
        self.assertIs(handler_factory.REMOTE_HANDLERS["s3"], S3Handler)

    def test_unknown_type_delegates_to_rclone(self):
        handler = get_remote_handler(
            monitor_path="/local",
            remote_path="/remote",
            profile={"profile_type": "ftp", "name": "myftp", "config": {}},
        )
        self.assertIsInstance(handler, RcloneHandler)
        self.assertEqual(handler.profile_name, "myftp")

    def test_mapped_type_uses_native_handler(self):
        # Registering a native key means both the handler table and the
        # reference-data vocabulary (a guard test keeps them in sync).
        with (
            mock.patch.object(reference_data, "NATIVE_PROFILE_TYPES", ("_fake",)),
            mock.patch.dict(
                handler_factory.REMOTE_HANDLERS, {"_fake": _FakeRemoteHandler}
            ),
        ):
            handler = get_remote_handler(
                monitor_path="/local",
                remote_path="/remote",
                profile={
                    "profile_type": "_fake",
                    "name": "fake",
                    "config": {"remote_handler": "_fake", "x": 1},
                },
            )
        self.assertIsInstance(handler, _FakeRemoteHandler)
        self.assertEqual(
            handler.profile_config, {"remote_handler": "_fake", "x": 1}
        )

    def test_empty_profile_name_falls_back_to_rclone(self):
        handler = get_remote_handler(
            monitor_path="/local",
            remote_path="/remote",
            profile={"profile_type": "", "name": "", "config": {}},
        )
        self.assertIsInstance(handler, RcloneHandler)

    def test_rclone_route_receives_the_profile_configuration(self):
        """The rclone branch gets the profile, so rclone is configured via env."""
        handler = get_remote_handler(
            monitor_path="/local",
            remote_path="/remote",
            profile={
                "id": 9,
                "profile_type": "ftp",
                "name": "myftp",
                "config": {"host": "example.com", "user": "ftpuser", "pass": "p"},
            },
        )
        self.assertIsInstance(handler, RcloneHandler)
        self.assertEqual(handler.rclone_env["RCLONE_CONFIG_MYFTP_TYPE"], "ftp")
        self.assertEqual(
            handler.rclone_env["RCLONE_CONFIG_MYFTP_HOST"], "example.com"
        )

    def test_stored_key_overrides_profile_type(self):
        """An s3 profile switched to rclone is built as an RcloneHandler."""
        handler = get_remote_handler(
            monitor_path="/local",
            remote_path="/remote",
            profile={
                "profile_type": "s3",
                "name": "myremote",
                "config": {"remote_handler": "rclone"},
            },
        )
        self.assertIsInstance(handler, RcloneHandler)
        self.assertEqual(handler.profile_name, "myremote")

    def test_stored_native_key_wins_for_a_delegated_type(self):
        """The stored key wins even when profile_type would route to rclone.

        A new native key must be registered in both the handler table and the
        reference-data vocabulary; ``test_reference_data`` guards the two from
        drifting, so here both are patched for the duration of the test.
        """
        with (
            mock.patch.object(reference_data, "NATIVE_PROFILE_TYPES", ("_fake",)),
            mock.patch.dict(
                handler_factory.REMOTE_HANDLERS, {"_fake": _FakeRemoteHandler}
            ),
        ):
            handler = get_remote_handler(
                monitor_path="/local",
                remote_path="/remote",
                profile={
                    "profile_type": "ftp",
                    "name": "fake",
                    "config": {"remote_handler": "_fake", "x": 2},
                },
            )
        self.assertIsInstance(handler, _FakeRemoteHandler)
        self.assertEqual(handler.profile_config, {"remote_handler": "_fake", "x": 2})


class TestEveryConcreteRemoteHandlerIsMapped(unittest.TestCase):
    def test_declared_profile_types_are_in_the_mapping(self):
        """Every class declaring a PROFILE_TYPE must be in REMOTE_HANDLERS.

        Adding a native handler is a one-step change: define the
        ``RemoteHandler`` subclass and add its ``PROFILE_TYPE`` to the
        ``REMOTE_HANDLERS`` table.  ``RcloneHandler`` is the delegated fallback,
        not a native registrant, and stays out of the table by inheriting an
        empty ``PROFILE_TYPE``.
        """
        for cls in _remote_handler_subclasses():
            profile_type = getattr(cls, "PROFILE_TYPE", "")
            if not profile_type:
                continue
            self.assertIn(
                profile_type,
                handler_factory.REMOTE_HANDLERS,
                f"{cls.__name__} declares PROFILE_TYPE='{profile_type}' but is "
                "not in REMOTE_HANDLERS; add it to the mapping table",
            )
            self.assertTrue(
                issubclass(handler_factory.REMOTE_HANDLERS[profile_type], RemoteHandler),
                f"REMOTE_HANDLERS['{profile_type}'] must be a RemoteHandler subclass",
            )


class TestHandlerFactory(unittest.TestCase):
    def test_command_profile_gets_command_action_handler(self):
        monitor = {"name": "m", "monitor_path": "/tmp/m"}
        profile = {
            "name": "cmd-prof",
            "profile_type": "event_command",
            "config": {"command": "echo hi"},
        }
        handler = HandlerFactory.get_handler(monitor=monitor, profile=profile)
        self.assertIsInstance(handler, CommandActionHandler)

    def test_legacy_string_events_are_split_into_a_list(self):
        """A legacy comma-separated string must not be used for substring match."""
        monitor = {"name": "m", "monitor_path": "/tmp/m"}
        profile = {
            "name": "cmd-prof",
            "profile_type": "event_command",
            "config": {"command": "echo hi", "command_events": "created, modified"},
        }
        handler = HandlerFactory.get_handler(monitor=monitor, profile=profile)
        self.assertIsInstance(handler, CommandActionHandler)
        assert isinstance(handler, CommandActionHandler)
        self.assertEqual(handler.events, ["created", "modified"])

    def test_event_filter_normalization(self):
        normalize = HandlerFactory._normalize_command_events
        self.assertEqual(normalize("created,modified"), ["created", "modified"])
        self.assertEqual(normalize(["created", "timer"]), ["created", "timer"])
        self.assertEqual(normalize("timer"), ["timer"])
        self.assertIsNone(normalize(""))
        self.assertIsNone(normalize("  ,  "))
        self.assertIsNone(normalize([]))
        self.assertIsNone(normalize(None))
        self.assertIsNone(normalize(123))

    def test_mapped_remote_profile_gets_remote_action_handler(self):
        with (
            mock.patch.object(reference_data, "NATIVE_PROFILE_TYPES", ("_fake",)),
            mock.patch.dict(
                handler_factory.REMOTE_HANDLERS, {"_fake": _FakeRemoteHandler}
            ),
        ):
            monitor = {"name": "m", "monitor_path": "/tmp/m", "remote_path": "r:d"}
            profile = {
                "name": "fake",
                "profile_type": "_fake",
                "config": {"remote_handler": "_fake"},
            }
            handler = HandlerFactory.get_handler(monitor=monitor, profile=profile)
            self.assertIsInstance(handler, RemoteActionHandler)
            assert isinstance(handler, RemoteActionHandler)
            self.assertIsInstance(handler.remote_handler, _FakeRemoteHandler)
            handler.stop()

    def test_unmapped_remote_profile_gets_rclone_action_handler(self):
        monitor = {"name": "m", "monitor_path": "/tmp/m", "remote_path": "r:d"}
        profile = {"name": "myftp", "profile_type": "ftp", "config": {}}
        handler = HandlerFactory.get_handler(monitor=monitor, profile=profile)
        self.assertIsInstance(handler, RemoteActionHandler)
        assert isinstance(handler, RemoteActionHandler)
        self.assertIsInstance(handler.remote_handler, RcloneHandler)
        handler.stop()

    def test_remote_profile_routed_by_stored_key(self):
        """An s3 profile with remote_handler=rclone gets the rclone handler."""
        monitor = {"name": "m", "monitor_path": "/tmp/m", "remote_path": "r:d"}
        profile = {
            "name": "myremote",
            "profile_type": "s3",
            "config": {"remote_handler": "rclone"},
        }
        handler = HandlerFactory.get_handler(monitor=monitor, profile=profile)
        self.assertIsInstance(handler, RemoteActionHandler)
        assert isinstance(handler, RemoteActionHandler)
        self.assertIsInstance(handler.remote_handler, RcloneHandler)
        handler.stop()

    def test_missing_profile_returns_none(self):
        monitor = {"name": "m", "monitor_path": "/tmp/m", "remote_path": "r:d"}
        self.assertIsNone(HandlerFactory.get_handler(monitor=monitor, profile=None))
        self.assertIsNone(HandlerFactory.get_handler(monitor=monitor, profile={}))


if __name__ == "__main__":
    unittest.main()