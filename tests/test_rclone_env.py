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

    def test_unsafe_characters_are_normalised(self):
        # rclone substitutes nothing in the env-var name, so the remote name we
        # pass must be expressible as an environment variable name.
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
                "secret_access_key": "MYSECRET",
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

    def test_backend_property_becomes_backend_flag_variable(self):
        """A bare rclone.conf property is routed to RCLONE_<BACKEND>_<OPTION>."""
        flags = frozenset({"transfers", "s3-no-check-bucket"})
        with mock.patch.object(rclone_env, "known_rclone_flags", return_value=flags):
            env = rclone_env.build_rclone_env(
                remote_name="mydest",
                profile_type="s3",
                profile_config={
                    "rclone_options": {"no_check_bucket": "true", "transfers": 8}
                },
                rclone_path="rclone",
            )
        self.assertEqual(env["RCLONE_S3_NO_CHECK_BUCKET"], "true")
        self.assertEqual(env["RCLONE_TRANSFERS"], "8")
        self.assertNotIn("RCLONE_NO_CHECK_BUCKET", env)

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


class TestResolveOptionEnvName(unittest.TestCase):
    """A bare rclone.conf property resolves against the profile's backend."""

    FLAGS = frozenset(
        {"transfers", "s3-chunk-size", "s3-no-check-bucket", "s3-env-auth"}
    )

    def test_backend_property_uses_the_backend_qualified_variable(self):
        self.assertEqual(
            rclone_env.resolve_option_env_name("no_check_bucket", "s3", self.FLAGS),
            "RCLONE_S3_NO_CHECK_BUCKET",
        )
        self.assertEqual(
            rclone_env.resolve_option_env_name("chunk_size", "s3", self.FLAGS),
            "RCLONE_S3_CHUNK_SIZE",
        )

    def test_backend_prefixed_name_still_resolves(self):
        self.assertEqual(
            rclone_env.resolve_option_env_name("s3_chunk_size", "s3", self.FLAGS),
            "RCLONE_S3_CHUNK_SIZE",
        )

    def test_global_flag_uses_its_own_variable(self):
        self.assertEqual(
            rclone_env.resolve_option_env_name("transfers", "s3", self.FLAGS),
            "RCLONE_TRANSFERS",
        )

    def test_unknown_option_returns_none(self):
        self.assertIsNone(
            rclone_env.resolve_option_env_name("no_check_buckets", "s3", self.FLAGS)
        )

    def test_without_flags_nothing_resolves(self):
        self.assertIsNone(rclone_env.resolve_option_env_name("transfers", "s3", None))


class TestUnknownRcloneOptions(unittest.TestCase):
    """Options the installed rclone does not support must be reported.

    rclone silently ignores ``RCLONE_*`` variables for unknown flags, so a typo
    or an older rclone would otherwise apply nothing without saying so.
    """

    FLAGS_OUTPUT = (
        "      --transfers int            Number of file transfers to run in parallel\n"
        "      --s3-chunk-size SizeSuffix  Chunk size to use for uploading\n"
        "      --s3-no-check-bucket       If set, don't attempt to check the bucket\n"
        "      --s3-object-lock-mode string  Object Lock mode\n"
    )

    def _flags_probe(self):
        return mock.patch(
            "app.monitor.rclone_env.subprocess.run",
            return_value=mock.Mock(stdout=self.FLAGS_OUTPUT),
        )

    def test_supported_options_are_not_reported(self):
        with mock.patch.object(rclone_env, "_KNOWN_FLAGS_CACHE", {}), self._flags_probe():
            self.assertEqual(
                rclone_env.unknown_rclone_options(
                    {
                        "transfers": 8,
                        "s3_chunk_size": "16M",
                        "s3_object_lock_mode": "GOVERNANCE",
                    },
                    "rclone",
                ),
                [],
            )

    def test_unsupported_option_is_reported(self):
        with mock.patch.object(rclone_env, "_KNOWN_FLAGS_CACHE", {}), self._flags_probe():
            self.assertEqual(
                rclone_env.unknown_rclone_options(
                    {"s3_object_lock_mod": "GOVERNANCE", "transfers": 8}, "rclone"
                ),
                ["s3_object_lock_mod"],
            )

    def test_backend_property_is_not_reported(self):
        with mock.patch.object(rclone_env, "_KNOWN_FLAGS_CACHE", {}), self._flags_probe():
            self.assertEqual(
                rclone_env.unknown_rclone_options(
                    {"no_check_bucket": "true"}, "rclone", profile_type="s3"
                ),
                [],
            )

    def test_backend_property_without_profile_type_is_reported(self):
        with mock.patch.object(rclone_env, "_KNOWN_FLAGS_CACHE", {}), self._flags_probe():
            self.assertEqual(
                rclone_env.unknown_rclone_options({"no_check_bucket": "true"}, "rclone"),
                ["no_check_bucket"],
            )

    def test_flags_are_probed_once_per_binary(self):
        with (
            mock.patch.object(rclone_env, "_KNOWN_FLAGS_CACHE", {}),
            self._flags_probe() as run,
        ):
            rclone_env.unknown_rclone_options({"transfers": 8}, "rclone")
            rclone_env.unknown_rclone_options({"transfers": 8}, "rclone")
        self.assertEqual(run.call_count, 1)

    def test_probe_failure_is_reported_and_treated_as_unknown(self):
        logger = mock.Mock()
        with (
            mock.patch.object(rclone_env, "_KNOWN_FLAGS_CACHE", {}),
            mock.patch(
                "app.monitor.rclone_env.subprocess.run", side_effect=OSError("no rclone")
            ),
        ):
            self.assertEqual(
                rclone_env.unknown_rclone_options({"bogus": 1}, "rclone", logger=logger),
                [],
            )
        logger.warning.assert_called_once()

    def test_missing_rclone_path_is_not_probed(self):
        with (
            mock.patch.object(rclone_env, "_KNOWN_FLAGS_CACHE", {}),
            mock.patch("app.monitor.rclone_env.subprocess.run") as run,
        ):
            self.assertEqual(rclone_env.unknown_rclone_options({"bogus": 1}, ""), [])
        run.assert_not_called()

    def test_empty_or_non_mapping_options_are_not_probed(self):
        with mock.patch("app.monitor.rclone_env.subprocess.run") as run:
            self.assertEqual(rclone_env.unknown_rclone_options(None, "rclone"), [])
            self.assertEqual(rclone_env.unknown_rclone_options({}, "rclone"), [])
        run.assert_not_called()


class TestBuildEnvironment(unittest.TestCase):
    """The profile-to-rclone mapping is owned by rclone_env, not the handler."""

    PROFILE = {
        "id": 3,
        "name": "s3-test",
        "profile_type": "s3",
        "config": {
            "provider_name": "Other",
            "endpoint": "https://example.invalid",
            "access_key_id": "MYKEY",
            "secret_access_key": "MYSECRET",
            "remote_handler": "rclone",
        },
    }

    def test_returns_remote_name_and_variables(self):
        environment = rclone_env.build_environment(self.PROFILE)

        self.assertEqual(environment.remote_name, "s3_test")
        self.assertEqual(environment.variables["RCLONE_CONFIG_S3_TEST_TYPE"], "s3")
        self.assertEqual(
            environment.variables["RCLONE_CONFIG_S3_TEST_SECRET_ACCESS_KEY"],
            "MYSECRET",
        )
        self.assertEqual(environment.unsupported_options, ())

    def test_normalised_name_is_reported_at_debug(self):
        logger = mock.Mock()

        rclone_env.build_environment(self.PROFILE, logger=logger)

        logger.debug.assert_called_once()
        self.assertIn("s3_test", logger.debug.call_args.args[0])
        logger.warning.assert_not_called()

    def test_env_safe_name_is_not_reported(self):
        logger = mock.Mock()

        environment = rclone_env.build_environment(
            dict(self.PROFILE, name="s3_test"), logger=logger
        )

        self.assertEqual(environment.remote_name, "s3_test")
        logger.debug.assert_not_called()

    def test_unsupported_options_are_warned_about_and_returned(self):
        logger = mock.Mock()
        profile = dict(
            self.PROFILE,
            config={
                **self.PROFILE["config"],
                "rclone_options": {"s3_object_lock_mod": "GOVERNANCE"},
            },
        )
        with (
            mock.patch.object(
                rclone_env, "unknown_rclone_options", return_value=["s3_object_lock_mod"]
            ),
            mock.patch.object(rclone_env, "known_rclone_flags", return_value=frozenset()),
        ):
            environment = rclone_env.build_environment(
                profile, rclone_path="rclone", logger=logger
            )

        self.assertEqual(environment.unsupported_options, ("s3_object_lock_mod",))
        logger.warning.assert_called_once()
        self.assertIn("s3_object_lock_mod", logger.warning.call_args.args[0])

    def test_backend_property_is_resolved_and_not_warned(self):
        logger = mock.Mock()
        profile = dict(
            self.PROFILE,
            config={
                **self.PROFILE["config"],
                "rclone_options": {"no_check_bucket": "true"},
            },
        )
        flags = frozenset({"s3-no-check-bucket"})
        with mock.patch.object(rclone_env, "known_rclone_flags", return_value=flags):
            environment = rclone_env.build_environment(
                profile, rclone_path="rclone", logger=logger
            )

        self.assertEqual(environment.variables["RCLONE_S3_NO_CHECK_BUCKET"], "true")
        self.assertEqual(environment.unsupported_options, ())
        logger.warning.assert_not_called()

    def test_options_are_not_validated_without_an_rclone_path(self):
        with mock.patch.object(rclone_env, "unknown_rclone_options") as unknown:
            environment = rclone_env.build_environment(self.PROFILE)

        unknown.assert_not_called()
        self.assertEqual(environment.unsupported_options, ())

    def test_profile_without_name_or_config(self):
        environment = rclone_env.build_environment({"name": "", "profile_type": "s3"})

        self.assertEqual(environment.remote_name, "mh_profile")
        self.assertEqual(
            environment.variables, {"RCLONE_CONFIG_MH_PROFILE_TYPE": "s3"}
        )


if __name__ == "__main__":
    unittest.main()
