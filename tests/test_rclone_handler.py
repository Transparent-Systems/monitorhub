"""Unit tests for RcloneHandler's exit-code classification and run_command.

These need no rclone binary and no network: subprocess.Popen is replaced with a
fake process so the mapping from rclone exit codes to RemoteResult is verified.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.monitor import rclone_env
from app.monitor.rclone_handler import RcloneHandler
from app.monitor.remote_result import RemoteErrorKind


class _FakeProcess:
    """Stand-in for subprocess.Popen that returns a fixed outcome."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.pid = 4242

    def communicate(self, timeout=None):
        return self._stdout, self._stderr

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class _HangingProcess:
    """Stand-in for subprocess.Popen that never finishes on its own."""

    pid = 4243

    def __init__(self) -> None:
        self.returncode = None

    def communicate(self, timeout=None):
        if timeout is not None:
            raise subprocess.TimeoutExpired("rclone", timeout)
        return "", "killed after timeout"

    def poll(self):
        return None

    def kill(self):
        self.returncode = -9


def _make_handler(command_timeout: float = 0) -> RcloneHandler:
    """Build a handler with a quiet logger and the timeout disabled by default."""
    logger = logging.getLogger("tests.test_rclone_handler")
    logger.setLevel(logging.CRITICAL)
    logger.propagate = False

    handler = RcloneHandler(
        base_monitor_path="/tmp",
        base_remote_path="remote:path",
        profile_name="remote",
        logger=logger,
        command_timeout=command_timeout,
    )
    handler.rclone_path = "rclone"
    return handler


def _make_profiled_handler(profile: dict, command_timeout: float = 0) -> RcloneHandler:
    """Build a handler from a full profile dict (env-based rclone config).

    The binary is faked: building the environment must not need rclone to be
    installed, and probing a real one would tie the assertions to whatever
    version happens to be on the machine.
    """
    logger = logging.getLogger("tests.test_rclone_handler")
    logger.setLevel(logging.CRITICAL)
    logger.propagate = False
    with (
        mock.patch.object(RcloneHandler, "get_rclone_path", return_value="rclone"),
        mock.patch.object(rclone_env, "known_rclone_flags", return_value=None),
    ):
        handler = RcloneHandler(
            base_monitor_path="/tmp",
            base_remote_path="bucket/prefix",
            profile_name=profile.get("name", ""),
            logger=logger,
            command_timeout=command_timeout,
            profile=profile,
        )
    handler.rclone_path = "rclone"
    return handler


class TestRcloneGetRemotePath(unittest.TestCase):
    """``get_remote_path`` derives the remote path from the local one."""

    def test_path_under_base_is_appended(self):
        handler = _make_handler()
        self.assertEqual(
            handler.get_remote_path("/tmp/a/b.txt"), "remote:path/a/b.txt"
        )

    def test_path_outside_base_falls_back_to_file_name(self):
        """A path outside base_monitor_path must not raise (regression)."""
        handler = _make_handler()
        self.assertEqual(
            handler.get_remote_path("/other/file.txt"), "remote:path/file.txt"
        )


class TestRcloneExitCodeClassification(unittest.TestCase):
    def test_not_found_codes(self):
        for code in (3, 4):
            self.assertEqual(
                RcloneHandler._classify_returncode(code), RemoteErrorKind.NOT_FOUND
            )

    def test_transient_codes(self):
        for code in (5, 6):
            self.assertEqual(
                RcloneHandler._classify_returncode(code), RemoteErrorKind.TRANSIENT
            )

    def test_other_codes_are_fatal(self):
        for code in (1, 2, 7, 8, 9):
            self.assertEqual(RcloneHandler._classify_returncode(code), RemoteErrorKind.FATAL)

    def test_only_exit_code_5_is_retryable(self):
        self.assertTrue(RcloneHandler._is_retryable(5))
        for code in (1, 3, 4, 6, 7):
            self.assertFalse(RcloneHandler._is_retryable(code))


class TestRcloneRunCommand(unittest.TestCase):
    def test_success_returns_stdout_as_message(self):
        handler = _make_handler()

        with mock.patch(
            "app.monitor.rclone_handler.subprocess.Popen",
            return_value=_FakeProcess(0, stdout="file.txt\n"),
        ):
            result = handler.run_command(["ls", "remote:path"])

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "file.txt")
        self.assertEqual(result.code, 0)

    def test_transient_failure_is_retryable(self):
        handler = _make_handler()

        with mock.patch(
            "app.monitor.rclone_handler.subprocess.Popen",
            return_value=_FakeProcess(5, stderr="temporary failure"),
        ):
            result = handler.run_command(["copy", "a", "b"])

        self.assertFalse(result.ok)
        self.assertEqual(result.code, 5)
        self.assertEqual(result.kind, RemoteErrorKind.TRANSIENT)
        self.assertTrue(result.retryable)
        self.assertEqual(result.message, "temporary failure")

    def test_not_found_failure(self):
        handler = _make_handler()

        with mock.patch(
            "app.monitor.rclone_handler.subprocess.Popen",
            return_value=_FakeProcess(3, stderr="directory not found"),
        ):
            result = handler.run_command(["ls", "remote:missing"])

        self.assertFalse(result.ok)
        self.assertEqual(result.kind, RemoteErrorKind.NOT_FOUND)
        self.assertFalse(result.retryable)

    def test_missing_rclone_reports_failure(self):
        """A missing rclone binary must return a failure, never raise.

        Regression: ``get_rclone_path`` returns ``""`` (not ``None``) when
        rclone is absent, so the handler must treat an empty path as
        "not found"; otherwise ``Popen([""])`` raises instead of reporting.
        """
        logger = logging.getLogger("tests.test_rclone_handler")
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False

        previous = RcloneHandler.rclone_path
        RcloneHandler.rclone_path = None
        self.addCleanup(setattr, RcloneHandler, "rclone_path", previous)
        with mock.patch.object(shutil, "which", return_value=None):
            handler = RcloneHandler(
                base_monitor_path="/tmp",
                base_remote_path="remote:path",
                profile_name="remote",
                logger=logger,
                command_timeout=0,
            )

        self.assertEqual(handler.rclone_path, "")
        result = handler.run_command(["ls", "remote:path"])

        self.assertFalse(result.ok)
        self.assertEqual(result.code, 1)
        self.assertIn("rclone executable not found", result.message)

    def test_bad_additional_args_reports_failure(self):
        handler = _make_handler()

        result = handler.run_command(["ls", "remote:path"], additional_args_str='"unterminated')

        self.assertFalse(result.ok)
        self.assertEqual(result.code, 1)
        self.assertIn("Error parsing arguments", result.message)

    def test_timeout_is_reported_as_retryable(self):
        handler = _make_handler(command_timeout=0.01)

        with mock.patch(
            "app.monitor.rclone_handler.subprocess.Popen",
            return_value=_HangingProcess(),
        ):
            result = handler.run_command(["copy", "a", "b"])

        self.assertFalse(result.ok)
        self.assertEqual(result.kind, RemoteErrorKind.TIMEOUT)
        self.assertTrue(result.retryable)
        self.assertEqual(result.code, 1)


class TestRcloneProfileEnvironment(unittest.TestCase):
    """A profile is described to rclone through the environment, not rclone.conf.

    The variables are passed per subprocess, so they only affect the rclone
    process that belongs to this handler.
    """

    PROFILE = {
        "id": 3,
        "name": "my-dest",
        "profile_type": "s3",
        "config": {
            "provider": "Other",
            "endpoint": "https://example.invalid",
            "access_key_id": "MYKEY",
            "secret_access_key": "MYSECRET",
            "remote_handler": "rclone",
            "rclone_options": {"transfers": 8},
        },
    }

    def test_remote_name_is_normalised_and_used_for_paths(self):
        handler = _make_profiled_handler(self.PROFILE)

        self.assertEqual(handler.profile_name, "my_dest")
        self.assertEqual(handler.base_remote_path.as_posix(), "my_dest:bucket/prefix")
        self.assertEqual(handler.rclone_env["RCLONE_CONFIG_MY_DEST_TYPE"], "s3")
        self.assertEqual(
            handler.rclone_env["RCLONE_CONFIG_MY_DEST_SECRET_ACCESS_KEY"], "MYSECRET"
        )
        self.assertEqual(handler.rclone_env["RCLONE_TRANSFERS"], "8")
        self.assertNotIn("RCLONE_CONFIG_MY_DEST_REMOTE_HANDLER", handler.rclone_env)

    def test_popen_receives_merged_environment_and_no_secret_in_argv(self):
        handler = _make_profiled_handler(self.PROFILE)

        with mock.patch(
            "app.monitor.rclone_handler.subprocess.Popen",
            return_value=_FakeProcess(0, stdout="ok"),
        ) as popen:
            handler.run_command(["copy", "/local", "my_dest:bucket/prefix"])

        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["RCLONE_CONFIG_MY_DEST_TYPE"], "s3")
        # The inherited environment is kept (rclone needs PATH/HOME).
        self.assertTrue(set(os.environ.items()) <= set(env.items()))
        # Secrets are only in the environment, never on the command line.
        argv = popen.call_args.args[0]
        self.assertNotIn("MYSECRET", argv)

    def test_handler_without_profile_keeps_the_inherited_environment(self):
        handler = _make_handler()

        with mock.patch(
            "app.monitor.rclone_handler.subprocess.Popen",
            return_value=_FakeProcess(0),
        ) as popen:
            handler.run_command(["ls", "remote:path"])

        self.assertIsNone(popen.call_args.kwargs["env"])

    def test_unsupported_rclone_options_are_warned_about(self):
        """rclone ignores unknown RCLONE_* variables, so MonitorHub warns."""
        logger = mock.Mock()
        profile = {
            "id": 5,
            "name": "mh_env_live",
            "profile_type": "s3",
            "config": {"rclone_options": {"s3_object_lock_mod": "GOVERNANCE"}},
        }
        with (
            mock.patch.object(RcloneHandler, "get_rclone_path", return_value="rclone"),
            mock.patch.object(rclone_env, "known_rclone_flags", return_value=None),
            mock.patch.object(
                rclone_env, "unknown_rclone_options", return_value=["s3_object_lock_mod"]
            ),
        ):
            RcloneHandler(
                base_monitor_path="/tmp",
                base_remote_path="bucket/prefix",
                profile_name="mh_env_live",
                logger=logger,
                profile=profile,
            )
        messages = [call.args[0] for call in logger.warning.call_args_list]
        self.assertTrue(
            any("s3_object_lock_mod" in message for message in messages), messages
        )

    def test_backend_property_is_not_warned_about(self):
        """A bare rclone.conf property resolves to RCLONE_<BACKEND>_<OPTION>."""
        logger = mock.Mock()
        profile = {
            "id": 6,
            "name": "mh_backend_live",
            "profile_type": "s3",
            "config": {"rclone_options": {"no_check_bucket": "true"}},
        }
        flags = frozenset({"s3-no-check-bucket"})
        with (
            mock.patch.object(RcloneHandler, "get_rclone_path", return_value="rclone"),
            mock.patch.object(rclone_env, "known_rclone_flags", return_value=flags),
        ):
            handler = RcloneHandler(
                base_monitor_path="/tmp",
                base_remote_path="bucket/prefix",
                profile_name="mh_backend_live",
                logger=logger,
                profile=profile,
            )
        self.assertEqual(handler.rclone_env["RCLONE_S3_NO_CHECK_BUCKET"], "true")
        self.assertNotIn("RCLONE_NO_CHECK_BUCKET", handler.rclone_env)
        messages = [call.args[0] for call in logger.warning.call_args_list]
        self.assertFalse(
            any("no_check_bucket" in message for message in messages), messages
        )

    def test_test_connection_uses_the_profile_environment(self):
        prompt = mock.Mock()

        with (
            mock.patch.object(RcloneHandler, "get_rclone_path", return_value="rclone"),
            mock.patch.object(rclone_env, "known_rclone_flags", return_value=None),
            mock.patch(
                "app.monitor.rclone_handler.subprocess.Popen",
                return_value=_FakeProcess(0, stdout="bucket"),
            ) as popen,
        ):
            RcloneHandler.test_connection(
                profile_name="my-dest",
                logger=logging.getLogger("tests.test_rclone_handler"),
                prompt=prompt,
                profile=self.PROFILE,
            )

        argv = popen.call_args.args[0]
        self.assertEqual(argv[1:3], ["lsd", "my_dest:"])
        self.assertEqual(
            popen.call_args.kwargs["env"]["RCLONE_CONFIG_MY_DEST_TYPE"], "s3"
        )


class TestRcloneEnvAgainstRealBinary(unittest.TestCase):
    """End-to-end: rclone resolves the profile from the environment alone.

    Hermetic: the endpoint is a refused loopback port, so no network and no
    credentials are needed.  rclone's error names the endpoint it actually used,
    which is how resolution and precedence are asserted.
    """

    PROFILE = {
        "id": 11,
        "name": "mh_env_live",
        "profile_type": "s3",
        "config": {
            "provider": "Other",
            "endpoint": "http://127.0.0.1:1",
            "access_key_id": "KEYID",
            "secret_access_key": "SECRETVALUE",
            # Fail after one attempt instead of retrying for a minute.
            "rclone_options": {"retries": 1, "low_level_retries": 1},
        },
    }

    def _run_lsd(self, config_path: str) -> object:
        with mock.patch.dict(os.environ, {"RCLONE_CONFIG": config_path}):
            handler = _make_profiled_handler(self.PROFILE, command_timeout=30)
            return handler.run_command(["lsd", "mh_env_live:"])

    @unittest.skipUnless(shutil.which("rclone"), "rclone not installed")
    def test_remote_is_resolved_without_rclone_conf(self):
        result = self._run_lsd("/tmp/monitorhub_missing_rclone.conf")

        # Resolved from the environment: the failure is the refused endpoint,
        # not a missing config section.
        self.assertNotIn("didn't find section in config file", result.message)
        self.assertIn("127.0.0.1:1", result.message)

    @unittest.skipUnless(shutil.which("rclone"), "rclone not installed")
    def test_monitorhub_environment_wins_over_rclone_conf(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "rclone.conf"
            conf.write_text(
                "[mh_env_live]\n"
                "type = s3\n"
                "provider = Other\n"
                "endpoint = http://127.0.0.1:2\n"
                "access_key_id = FROM_CONF\n"
                "secret_access_key = FROM_CONF\n",
                encoding="utf-8",
            )
            result = self._run_lsd(str(conf))

        self.assertIn("127.0.0.1:1", result.message)
        self.assertNotIn("127.0.0.1:2", result.message)


if __name__ == "__main__":
    unittest.main()
