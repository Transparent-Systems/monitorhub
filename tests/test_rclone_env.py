"""Unit tests for the rclone environment built from a MonitorHub profile.

The environment is how an rclone-routed profile is described to rclone now that
MonitorHub owns the profile configuration (no ``rclone.conf`` section): each
config key becomes ``RCLONE_CONFIG_<REMOTE>_<OPTION>``, and per-profile rclone
options become ``RCLONE_<OPTION>`` flag variables.
"""

import unittest
from unittest import mock

from app.monitor import rclone_env


class TestEnvRemoteName(unittest.TestCase):
    def test_env_safe_names_are_unchanged(self):
        self.assertEqual(rclone_env.env_remote_name("mydest"), "mydest")
        self.assertEqual(rclone_env.env_remote_name("My_Dest_2"), "My_Dest_2")

    def test_names_are_stripped(self):
        self.assertEqual(rclone_env.env_remote_name("  mydest  "), "mydest")

    def test_unsafe_characters_are_replaced(self):
        # rclone does not substitute characters, so the name we pass must be
        # expressible as an environment variable name.
        self.assertEqual(rclone_env.env_remote_name("my-dest"), "my_dest")
        self.assertEqual(rclone_env.env_remote_name("my.dest"), "my_dest")
        self.assertEqual(rclone_env.env_remote_name("my dest"), "my_dest")

    def test_empty_name_falls_back_to_profile_id(self):
        self.assertEqual(rclone_env.env_remote_name("", 7), "mh_7")
        self.assertEqual(rclone_env.env_remote_name("---", 7), "___")
        self.assertEqual(rclone_env.env_remote_name("", None), "mh_profile")


class TestBuildRcloneEnv(unittest.TestCase):
    def test_s3_profile_config_becomes_remote_variables(self):
        env = rclone_env.build_rclone_env(
            remote_name="mydest",
            profile_type="s3",
            profile_config={
                "provider_name": "Other",
                "endpoint": "https://example.invalid",
                "access_key_id": "MYKEY",
                "access_key_secret": "MYSECRET",
                "region": "us-east-1",
            },
        )
        self.assertEqual(
            env,
            {
                "RCLONE_CONFIG_MYDEST_TYPE": "s3",
                "RCLONE_CONFIG_MYDEST_PROVIDER": "Other",
                "RCLONE_CONFIG_MYDEST_ENDPOINT": "https://example.invalid",
                "RCLONE_CONFIG_MYDEST_ACCESS_KEY_ID": "MYKEY",
                "RCLONE_CONFIG_MYDEST_SECRET_ACCESS_KEY": "MYSECRET",
                "RCLONE_CONFIG_MYDEST_REGION": "us-east-1",
            },
        )

    def test_remote_name_is_uppercased(self):
        env = rclone_env.build_rclone_env(
            remote_name="My_Dest",
            profile_type="s3",
            profile_config={"endpoint": "https://example.invalid"},
        )
        self.assertEqual(env["RCLONE_CONFIG_MY_DEST_TYPE"], "s3")
        self.assertEqual(
            env["RCLONE_CONFIG_MY_DEST_ENDPOINT"], "https://example.invalid"
        )

    def test_monitorhub_only_keys_are_not_sent_to_rclone(self):
        env = rclone_env.build_rclone_env(
            remote_name="mydest",
            profile_type="s3",
            profile_config={
                "endpoint": "https://example.invalid",
                "remote_handler": "rclone",
                "comment": "legacy hint",
                "important": "legacy hint",
            },
        )
        self.assertNotIn("RCLONE_CONFIG_MYDEST_REMOTE_HANDLER", env)
        self.assertNotIn("RCLONE_CONFIG_MYDEST_COMMENT", env)
        self.assertNotIn("RCLONE_CONFIG_MYDEST_IMPORTANT", env)

    def test_empty_values_are_skipped(self):
        env = rclone_env.build_rclone_env(
            remote_name="mydest",
            profile_type="s3",
            profile_config={"endpoint": "", "region": None, "access_key_id": "K"},
        )
        self.assertNotIn("RCLONE_CONFIG_MYDEST_ENDPOINT", env)
        self.assertNotIn("RCLONE_CONFIG_MYDEST_REGION", env)
        self.assertEqual(env["RCLONE_CONFIG_MYDEST_ACCESS_KEY_ID"], "K")

    def test_missing_profile_type_is_reported(self):
        logger = mock.Mock()
        env = rclone_env.build_rclone_env(
            remote_name="mydest",
            profile_type="",
            profile_config={"endpoint": "https://example.invalid"},
            logger=logger,
        )
        self.assertNotIn("RCLONE_CONFIG_MYDEST_TYPE", env)
        logger.warning.assert_called_once()

    def test_missing_remote_name_yields_no_environment(self):
        logger = mock.Mock()
        env = rclone_env.build_rclone_env(
            remote_name="",
            profile_type="s3",
            profile_config={"endpoint": "https://example.invalid"},
            logger=logger,
        )
        self.assertEqual(env, {})
        logger.warning.assert_called_once()

    def test_rclone_options_become_flag_variables(self):
        env = rclone_env.build_rclone_env(
            remote_name="mydest",
            profile_type="s3",
            profile_config={
                "endpoint": "https://example.invalid",
                "rclone_options": {
                    "transfers": 8,
                    "s3_chunk_size": "16M",
                    "s3_storage_class": "STANDARD",
                    "s3_object_lock_mode": "GOVERNANCE",
                },
            },
        )
        self.assertEqual(env["RCLONE_TRANSFERS"], "8")
        self.assertEqual(env["RCLONE_S3_CHUNK_SIZE"], "16M")
        self.assertEqual(env["RCLONE_S3_STORAGE_CLASS"], "STANDARD")
        self.assertEqual(env["RCLONE_S3_OBJECT_LOCK_MODE"], "GOVERNANCE")
        self.assertNotIn("RCLONE_CONFIG_MYDEST_RCLONE_OPTIONS", env)

    def test_invalid_rclone_options_are_reported_and_ignored(self):
        logger = mock.Mock()
        env = rclone_env.build_rclone_env(
            remote_name="mydest",
            profile_type="s3",
            profile_config={"rclone_options": {"--transfers": 8, "ok_option": "1"}},
            logger=logger,
        )
        self.assertEqual(env["RCLONE_OK_OPTION"], "1")
        self.assertNotIn("RCLONE_--TRANSFERS", env)
        logger.warning.assert_called_once()

    def test_non_mapping_rclone_options_are_reported(self):
        logger = mock.Mock()
        env = rclone_env.build_rclone_env(
            remote_name="mydest",
            profile_type="s3",
            profile_config={"rclone_options": ["--transfers", "8"]},
            logger=logger,
        )
        self.assertEqual(env, {"RCLONE_CONFIG_MYDEST_TYPE": "s3"})
        logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
