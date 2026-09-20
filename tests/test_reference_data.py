import unittest

from app.monitor.remote_handler_factory import RemoteHandlerFactory
from app.utils import reference_data
from app.utils.constants import (
    MONITOR_STATUS_ERROR,
    MONITOR_STATUS_RUNNING,
    MONITOR_STATUS_STOP,
    MONITOR_STATUS_STOPPED,
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)


class TestReferenceDataProviders(unittest.TestCase):
    def test_providers_are_all_s3(self):
        providers = reference_data.get_providers()
        self.assertTrue(len(providers) >= 5)
        names = [p.name for p in providers]
        self.assertIn("Amazon AWS S3", names)
        self.assertIn("Other", names)
        for p in providers:
            self.assertEqual(p.profile_type, "s3")

    def test_get_provider_by_name(self):
        provider = reference_data.get_provider("Backblaze")
        self.assertIsNotNone(provider)
        self.assertEqual(provider.name, "Backblaze")
        self.assertEqual(provider.profile_type, "s3")

    def test_get_provider_unknown_returns_none(self):
        self.assertIsNone(reference_data.get_provider("DoesNotExist"))


class TestReferenceDataProfileTypes(unittest.TestCase):
    def test_get_profile_category(self):
        self.assertEqual(reference_data.get_profile_category("s3"), "remote")
        self.assertEqual(reference_data.get_profile_category("ftp"), "remote")
        self.assertEqual(reference_data.get_profile_category("event_command"), "command")

    def test_is_profile_type_implemented(self):
        self.assertTrue(reference_data.is_profile_type_implemented("s3"))
        self.assertTrue(reference_data.is_profile_type_implemented("event_command"))
        self.assertFalse(reference_data.is_profile_type_implemented("ftp"))
        self.assertFalse(reference_data.is_profile_type_implemented("drive"))

    def test_get_implemented_profile_types(self):
        implemented = reference_data.get_implemented_profile_types()
        self.assertIn("s3", implemented)
        for command_type in reference_data.COMMAND_PROFILE_TYPES:
            self.assertIn(command_type, implemented)
        self.assertNotIn("ftp", implemented)
        self.assertNotIn("drive", implemented)

    def test_filter_implemented_profiles(self):
        profiles = [
            {"name": "a", "profile_type": "s3"},
            {"name": "b", "profile_type": "ftp"},
            {"name": "c", "profile_type": "event_command"},
        ]
        filtered = reference_data.filter_implemented_profiles(profiles)
        names = {p["name"] for p in filtered}
        self.assertEqual(names, {"a", "c"})


class TestReferenceDataProfileCategories(unittest.TestCase):
    def test_profile_categories(self):
        names = [name for name, _desc in reference_data.PROFILE_CATEGORIES]
        self.assertEqual(names, ["remote", "command"])

    def test_profile_categories_align_with_constants(self):
        names = [name for name, _desc in reference_data.PROFILE_CATEGORIES]
        self.assertIn(reference_data.PROFILE_CATEGORY_REMOTE, names)
        self.assertIn(reference_data.PROFILE_CATEGORY_COMMAND, names)


class TestReferenceDataMonitorTypes(unittest.TestCase):
    def test_monitor_types(self):
        names = [name for name, _desc in reference_data.MONITOR_TYPES]
        self.assertEqual(names, ["instant", "backup", "restore"])

    def test_monitor_types_align_with_constants(self):
        names = [name for name, _desc in reference_data.MONITOR_TYPES]
        self.assertIn(MONITOR_TYPE_INSTANT, names)
        self.assertIn(MONITOR_TYPE_BACKUP, names)
        self.assertIn(MONITOR_TYPE_RESTORE, names)

    def test_monitor_statuses(self):
        names = [name for name, _desc in reference_data.MONITOR_STATUSES]
        self.assertEqual(names, ["running", "stop", "stopped", "error"])

    def test_monitor_statuses_align_with_constants(self):
        names = [name for name, _desc in reference_data.MONITOR_STATUSES]
        self.assertIn(MONITOR_STATUS_RUNNING, names)
        self.assertIn(MONITOR_STATUS_STOP, names)
        self.assertIn(MONITOR_STATUS_STOPPED, names)
        self.assertIn(MONITOR_STATUS_ERROR, names)


class TestReferenceDataFactoryWiring(unittest.TestCase):
    """``reference_data`` uses RemoteHandlerFactory through a normal import."""

    def test_factory_is_imported_directly(self):
        # The lazy ``_remote_handler_factory`` helper was removed: there is no
        # circular import between reference_data and the monitor package.
        self.assertIs(reference_data.RemoteHandlerFactory, RemoteHandlerFactory)
        self.assertFalse(hasattr(reference_data, "_remote_handler_factory"))


if __name__ == "__main__":
    unittest.main()
