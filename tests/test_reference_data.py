import unittest

from scripts import reference_data


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
        self.assertEqual(reference_data.get_profile_category("file_event_command"), "command")
        self.assertEqual(reference_data.get_profile_category("command"), "command")
        self.assertEqual(reference_data.get_profile_category("timer_event_command"), "command")

    def test_is_profile_type_implemented(self):
        self.assertTrue(reference_data.is_profile_type_implemented("s3"))
        self.assertTrue(reference_data.is_profile_type_implemented("file_event_command"))
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
            {"name": "c", "profile_type": "file_event_command"},
        ]
        filtered = reference_data.filter_implemented_profiles(profiles)
        names = {p["name"] for p in filtered}
        self.assertEqual(names, {"a", "c"})


class TestReferenceDataMonitorTypes(unittest.TestCase):
    def test_monitor_types(self):
        names = [name for name, _desc in reference_data.MONITOR_TYPES]
        self.assertEqual(names, ["instant", "backup", "restore"])

    def test_monitor_statuses(self):
        names = [name for name, _desc in reference_data.MONITOR_STATUSES]
        self.assertEqual(names, ["running", "stop", "stopped", "error"])


if __name__ == "__main__":
    unittest.main()
