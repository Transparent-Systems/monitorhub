import unittest

from app.monitor.rclone_handler import RcloneHandler
from app.monitor.remote_handler_factory import RemoteHandlerFactory


class _FakeHandler:
    """Minimal handler used to verify registry dispatch without boto3."""

    def __init__(self, base_monitor_path, base_remote_path, profile_config, logger=None):
        self.base_monitor_path = base_monitor_path
        self.base_remote_path = base_remote_path
        self.profile_config = profile_config
        self.logger = logger


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
            RemoteHandlerFactory._handlers.pop("_fake", None)

    def test_unknown_profile_type_falls_back_to_rclone(self):
        handler = RemoteHandlerFactory.get_handler(
            monitor_path="/local",
            remote_path="/remote",
            profile={"profile_type": "ftp", "name": "myftp", "config": {}},
        )
        self.assertIsInstance(handler, RcloneHandler)
        self.assertEqual(handler.profile_name, "myftp")


if __name__ == "__main__":
    unittest.main()
