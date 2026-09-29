import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from app.monitor import handler_factory
from app.utils import reference_data
from app.utils.constants import (
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)


class TestReferenceDataProviders(unittest.TestCase):
    def test_providers_are_all_s3(self):
        providers = reference_data.get_providers()
        self.assertTrue(len(providers) >= 5)
        names = [p.name for p in providers]
        self.assertIn("AWS", names)
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

    def test_is_aws_provider(self):
        # Built-in name (matches the rclone key), the historical CLI name, and
        # any rclone-imported name containing "amazon".
        self.assertTrue(reference_data.is_aws_provider("AWS"))
        self.assertTrue(reference_data.is_aws_provider("aws"))
        self.assertTrue(reference_data.is_aws_provider("Amazon AWS S3"))
        self.assertFalse(reference_data.is_aws_provider("IDrive"))
        self.assertFalse(reference_data.is_aws_provider("Cloudflare"))
        self.assertFalse(reference_data.is_aws_provider(""))


class TestReferenceDataProfileTypes(unittest.TestCase):
    def test_get_profile_category(self):
        self.assertEqual(reference_data.get_profile_category("s3"), "remote")
        self.assertEqual(reference_data.get_profile_category("ftp"), "remote")
        self.assertEqual(reference_data.get_profile_category("event_command"), "command")


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


class TestReferenceDataFactoryWiring(unittest.TestCase):
    """The category table and the handler mapping must stay consistent.

    ``reference_data`` owns the profile-type *category* vocabulary that drives
    the CLI prompts; ``app.monitor.handler_factory`` owns the profile_type ->
    handler mapping. They live apart because reference_data must stay free of
    boto3, so these guards keep the two from drifting.
    """

    def test_import_does_not_load_boto3(self):
        # Importing reference_data must be cheap: the profile-type vocabulary is
        # plain code here and must not pull in the monitor stack (boto3 via
        # S3Handler). Run in a fresh interpreter because unittest discovery order
        # may already have boto3 in sys.modules by the time this test runs.
        repo_root = Path(__file__).resolve().parents[1]
        script = (
            "import sys\n"
            "import app.utils.reference_data\n"
            "raise SystemExit(0 if 'boto3' not in sys.modules else 1)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            0,
            result.returncode,
            msg="importing app.utils.reference_data loaded boto3:\n"
            f"{result.stdout}{result.stderr}",
        )

    def test_command_profile_types_are_categorized_command(self):
        for profile_type in reference_data.COMMAND_PROFILE_TYPES:
            self.assertEqual(
                reference_data.get_profile_category(profile_type), "command"
            )

    def test_remote_handlers_are_categorized_remote(self):
        for profile_type in handler_factory.REMOTE_HANDLERS:
            self.assertEqual(
                reference_data.get_profile_category(profile_type), "remote"
            )

    def test_command_and_remote_tables_are_disjoint(self):
        overlap = set(reference_data.COMMAND_PROFILE_TYPES) & set(
            handler_factory.REMOTE_HANDLERS
        )
        self.assertEqual(
            overlap,
            set(),
            "a profile type cannot be both a command type and a native remote type",
        )

    def test_native_profile_types_match_native_handlers(self):
        self.assertEqual(
            set(reference_data.NATIVE_PROFILE_TYPES),
            set(handler_factory.REMOTE_HANDLERS),
            "NATIVE_PROFILE_TYPES must mirror the native handler mapping so the "
            "rclone dependency check cannot drift from handler routing",
        )


class TestReferenceDataRemoteHandlerKeys(unittest.TestCase):
    """Default routing: native types keep their handler, the rest use rclone."""

    def test_native_types_default_to_their_own_handler(self):
        for profile_type in reference_data.NATIVE_PROFILE_TYPES:
            self.assertEqual(
                reference_data.default_remote_handler_key(profile_type),
                profile_type,
            )

    def test_other_remote_types_default_to_rclone(self):
        self.assertEqual(
            reference_data.default_remote_handler_key("ftp"),
            reference_data.RCLONE_REMOTE_HANDLER,
        )
        self.assertEqual(
            reference_data.default_remote_handler_key("sftp"),
            reference_data.RCLONE_REMOTE_HANDLER,
        )

    def test_command_types_have_no_remote_handler(self):
        for profile_type in reference_data.COMMAND_PROFILE_TYPES:
            self.assertEqual(
                reference_data.default_remote_handler_key(profile_type), ""
            )

    def test_empty_profile_type_has_no_remote_handler(self):
        self.assertEqual(reference_data.default_remote_handler_key(""), "")

    def test_remote_handler_keys_cover_native_handlers_and_rclone(self):
        self.assertEqual(
            set(reference_data.remote_handler_keys()),
            set(handler_factory.REMOTE_HANDLERS)
            | {reference_data.RCLONE_REMOTE_HANDLER},
            "remote_handler values must cover every native handler key plus rclone",
        )


class TestReferenceDataRemoteHandlerKeyResolution(unittest.TestCase):
    """A stored ``remote_handler`` key wins over profile_type routing."""

    def test_stored_key_wins_over_profile_type(self):
        profile = {
            "name": "p",
            "profile_type": "s3",
            "config": {reference_data.CONFIG_REMOTE_HANDLER: "rclone"},
        }
        self.assertEqual(reference_data.remote_handler_key(profile), "rclone")

    def test_missing_key_falls_back_to_profile_type(self):
        s3_profile = {"name": "p", "profile_type": "s3", "config": {}}
        ftp_profile = {"name": "p", "profile_type": "ftp", "config": None}
        self.assertEqual(reference_data.remote_handler_key(s3_profile), "s3")
        self.assertEqual(reference_data.remote_handler_key(ftp_profile), "rclone")

    def test_unknown_key_warns_and_falls_back(self):
        logger = mock.Mock()
        profile = {
            "name": "p",
            "profile_type": "s3",
            "config": {reference_data.CONFIG_REMOTE_HANDLER: "bogus"},
        }
        self.assertEqual(
            reference_data.remote_handler_key(profile, logger=logger), "s3"
        )
        logger.warning.assert_called_once()

    def test_is_rclone_profile(self):
        self.assertTrue(
            reference_data.is_rclone_profile(
                {"name": "p", "profile_type": "ftp", "config": {}}
            )
        )
        self.assertTrue(
            reference_data.is_rclone_profile(
                {
                    "name": "p",
                    "profile_type": "s3",
                    "config": {reference_data.CONFIG_REMOTE_HANDLER: "rclone"},
                }
            )
        )
        self.assertFalse(
            reference_data.is_rclone_profile(
                {"name": "p", "profile_type": "s3", "config": {}}
            )
        )
        self.assertFalse(
            reference_data.is_rclone_profile(
                {"name": "p", "profile_type": "event_command", "config": {}}
            )
        )


if __name__ == "__main__":
    unittest.main()
