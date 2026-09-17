import unittest

from app.monitor.rclone_handler import RcloneHandler
from app.monitor.remote_handler import RemoteHandler
from app.monitor.remote_handler_factory import RemoteHandlerFactory


class _FakeHandler:
    """Minimal handler used to verify registry dispatch without boto3."""

    def __init__(self, base_monitor_path, base_remote_path, profile_config, logger=None):
        self.base_monitor_path = base_monitor_path
        self.base_remote_path = base_remote_path
        self.profile_config = profile_config
        self.logger = logger


def _remote_handler_subclasses() -> list[type]:
    """Return every loaded ``RemoteHandler`` subclass, direct and indirect."""
    queue = list(RemoteHandler.__subclasses__())
    found: list[type] = []
    while queue:
        cls = queue.pop()
        found.append(cls)
        queue.extend(cls.__subclasses__())
    return found


class TestRemoteHandlerFactory(unittest.TestCase):
    def test_s3_is_registered(self):
        self.assertIn("s3", RemoteHandlerFactory.registered_types())
        self.assertTrue(RemoteHandlerFactory.is_registered("s3"))

    def test_unknown_type_not_registered(self):
        self.assertFalse(RemoteHandlerFactory.is_registered("ftp"))
        self.assertFalse(RemoteHandlerFactory.is_registered("drive"))

    def test_register_empty_type_raises(self):
        with self.assertRaises(ValueError):
            RemoteHandlerFactory.register("", _FakeHandler)

    def test_register_and_dispatch_custom_handler(self):
        RemoteHandlerFactory.register("_fake", _FakeHandler)
        try:
            handler = RemoteHandlerFactory.get_handler(
                monitor_path="/local",
                remote_path="/remote",
                profile={"profile_type": "_fake", "name": "fake", "config": {"x": 1}},
            )
            self.assertIsInstance(handler, _FakeHandler)
            self.assertEqual(handler.profile_config, {"x": 1})
        finally:
            # Clean up so other tests are unaffected.
            RemoteHandlerFactory.unregister("_fake")

    def test_unknown_profile_type_falls_back_to_rclone(self):
        handler = RemoteHandlerFactory.get_handler(
            monitor_path="/local",
            remote_path="/remote",
            profile={"profile_type": "ftp", "name": "myftp", "config": {}},
        )
        self.assertIsInstance(handler, RcloneHandler)
        self.assertEqual(handler.profile_name, "myftp")

    def test_every_concrete_remote_handler_is_registered(self):
        """Every class that declares a PROFILE_TYPE must be registered.

        A new native handler (e.g. FTP) must do two things to work: define a
        ``RemoteHandler`` subclass and make one ``RemoteHandlerFactory.register()``
        call.  This guard fails the suite if the registration call is forgotten.
        ``RcloneHandler`` is the delegated fallback, not a native registrant, and
        stays unregistered by inheriting an empty PROFILE_TYPE.
        """
        for cls in _remote_handler_subclasses():
            profile_type = getattr(cls, "PROFILE_TYPE", "")
            if not profile_type:
                continue
            self.assertTrue(
                RemoteHandlerFactory.is_registered(profile_type),
                f"{cls.__name__} declares PROFILE_TYPE='{profile_type}' but is "
                "not registered; add a RemoteHandlerFactory.register() call",
            )


if __name__ == "__main__":
    unittest.main()
