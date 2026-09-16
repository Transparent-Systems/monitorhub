"""Unit tests for RcloneHandler's exit-code classification and run_command.

These need no rclone binary and no network: subprocess.Popen is replaced with a
fake process so the mapping from rclone exit codes to RemoteResult is verified.
"""

import logging
import subprocess
import unittest
from unittest import mock

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
        handler = _make_handler()
        handler.rclone_path = None

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


if __name__ == "__main__":
    unittest.main()
