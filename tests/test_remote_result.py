"""Unit tests for RemoteResult and its error classification."""

import unittest
from dataclasses import FrozenInstanceError

from app.monitor.remote_result import RemoteErrorKind, RemoteResult


class TestRemoteResult(unittest.TestCase):
    def test_success_is_truthy_and_carries_message_and_code(self):
        result = RemoteResult.success(message="uploaded", code=0)

        self.assertTrue(result.ok)
        self.assertTrue(result)
        self.assertEqual(result.message, "uploaded")
        self.assertEqual(result.code, 0)
        self.assertIsNone(result.kind)
        self.assertFalse(result.retryable)

    def test_failure_defaults_to_fatal_kind(self):
        result = RemoteResult.failure(message="boom", code=7)

        self.assertFalse(result.ok)
        self.assertFalse(result)
        self.assertEqual(result.kind, RemoteErrorKind.FATAL)
        self.assertEqual(result.code, 7)
        self.assertFalse(result.retryable)

    def test_failure_keeps_explicit_kind_and_retryable(self):
        result = RemoteResult.failure(
            message="try later",
            code=5,
            kind=RemoteErrorKind.TRANSIENT,
            retryable=True,
        )

        self.assertEqual(result.kind, RemoteErrorKind.TRANSIENT)
        self.assertTrue(result.retryable)

    def test_not_found_is_an_expected_negative(self):
        result = RemoteResult.not_found(message="no such key", code=4)

        self.assertFalse(result)
        self.assertEqual(result.kind, RemoteErrorKind.NOT_FOUND)
        self.assertEqual(result.code, 4)

    def test_is_immutable(self):
        result = RemoteResult.success()

        with self.assertRaises(FrozenInstanceError):
            result.ok = False  # type: ignore[misc]

    def test_value_equality(self):
        self.assertEqual(RemoteResult.success("a"), RemoteResult(ok=True, message="a"))
        self.assertNotEqual(RemoteResult.success("a"), RemoteResult.success("b"))

    def test_str_reports_success(self):
        self.assertEqual(str(RemoteResult.success()), "ok")
        self.assertEqual(str(RemoteResult.success("uploaded")), "uploaded")

    def test_str_reports_failure_details(self):
        result = RemoteResult.failure("denied", code=1, kind=RemoteErrorKind.ACCESS_DENIED)

        rendered = str(result)
        self.assertIn("access_denied", rendered)
        self.assertIn("code=1", rendered)
        self.assertIn("denied", rendered)

        retryable = RemoteResult.failure("later", kind=RemoteErrorKind.TRANSIENT, retryable=True)
        self.assertIn("retryable", str(retryable))


if __name__ == "__main__":
    unittest.main()
