"""Unit tests for S3Handler's handling of listing failures.

These tests need no credentials or network access: they inject a fake S3
client so we can assert that a failed listing is reported as a failure
(rather than a silent success) for delete/restore/sync, while a backup
(copy_folder) still uploads every local file.
"""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from app.monitor.remote_result import RemoteErrorKind
from app.monitor.s3_handler import S3Handler


class _FailingPaginator:
    """Paginator whose ``paginate`` always raises, simulating a list failure."""

    def paginate(self, **kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "ListObjectsV2",
        )


class _FakeS3Client:
    """Minimal fake S3 client: listing fails, other calls are recorded."""

    def __init__(self) -> None:
        self.uploaded: list[tuple[str, str, str]] = []
        self.deleted_batches: list[dict] = []

    def get_paginator(self, name: str):
        return _FailingPaginator()

    def head_object(self, **kwargs):
        # Simulate a not-yet-uploaded object.
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def upload_file(self, filename, bucket, key, **kwargs):
        self.uploaded.append((filename, bucket, key))

    def delete_objects(self, **kwargs):
        self.deleted_batches.append(kwargs)
        return {}


def _make_handler(fake_client, base_monitor_path: str, base_remote_path: str = "bucket/prefix") -> S3Handler:
    """Build an S3Handler whose client is the supplied fake (no boto3 call)."""
    with mock.patch("app.monitor.s3_handler.S3Factory") as factory_cls:
        factory_cls.return_value.get_s3_client.return_value = fake_client
        return S3Handler(
            base_monitor_path=base_monitor_path,
            base_remote_path=base_remote_path,
            profile_config={},
            logger=logging.getLogger(__name__),
        )


class TestS3HandlerListingFailure(unittest.TestCase):
    """A2: a failed object listing must not be reported as success."""

    def test_list_objects_raises_on_failure(self):
        handler = _make_handler(_FakeS3Client(), base_monitor_path="/tmp")
        with self.assertRaises(ClientError):
            handler._list_objects("bucket", "prefix/")

    def test_delete_folder_reports_failure_when_listing_fails(self):
        handler = _make_handler(_FakeS3Client(), base_monitor_path="/tmp")
        result = handler.delete_folder("bucket/prefix")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 1)
        self.assertEqual(result.kind, RemoteErrorKind.ACCESS_DENIED)
        self.assertIn("denied", result.message)

    def test_restore_folder_reports_failure_when_listing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = _make_handler(_FakeS3Client(), base_monitor_path=tmp)
            result = handler.restore_folder("bucket/prefix")
            self.assertFalse(result.ok)
            self.assertEqual(result.code, 1)
            self.assertEqual(result.kind, RemoteErrorKind.ACCESS_DENIED)
            self.assertIn("denied", result.message)

    def test_sync_folder_reports_failure_when_listing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("hello", encoding="utf-8")
            handler = _make_handler(_FakeS3Client(), base_monitor_path=tmp)
            result = handler.sync_folder(tmp)
            self.assertFalse(result.ok)
            self.assertEqual(result.code, 1)

    def test_copy_folder_still_uploads_when_listing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("hello", encoding="utf-8")
            fake = _FakeS3Client()
            handler = _make_handler(fake, base_monitor_path=tmp)
            result = handler.copy_folder(tmp)
            self.assertTrue(result.ok)
            self.assertEqual(len(fake.uploaded), 1)


class TestS3ErrorClassification(unittest.TestCase):
    """_classify_exception maps boto3 errors onto RemoteErrorKind."""

    def test_client_error_not_found_codes(self):
        for code in ("404", "NoSuchKey", "NotFound", "NoSuchBucket"):
            exc = ClientError({"Error": {"Code": code}}, "HeadObject")
            self.assertEqual(S3Handler._classify_exception(exc), RemoteErrorKind.NOT_FOUND)

    def test_client_error_access_denied_codes(self):
        for code in ("403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            exc = ClientError({"Error": {"Code": code}}, "ListObjectsV2")
            self.assertEqual(S3Handler._classify_exception(exc), RemoteErrorKind.ACCESS_DENIED)

    def test_connection_errors_are_timeouts(self):
        for exc in (
            ConnectTimeoutError(endpoint_url="https://example.invalid"),
            ReadTimeoutError(endpoint_url="https://example.invalid"),
            EndpointConnectionError(endpoint_url="https://example.invalid"),
        ):
            self.assertEqual(S3Handler._classify_exception(exc), RemoteErrorKind.TIMEOUT)

    def test_unknown_exception_is_fatal(self):
        self.assertEqual(
            S3Handler._classify_exception(RuntimeError("boom")), RemoteErrorKind.FATAL
        )

    def test_file_exists_reports_not_found_as_expected_negative(self):
        """A missing key is NOT_FOUND, not an opaque failure."""
        handler = _make_handler(_FakeS3Client(), base_monitor_path="/tmp")

        result = handler.file_exists("bucket/prefix/missing.txt")

        self.assertFalse(result.ok)
        self.assertEqual(result.kind, RemoteErrorKind.NOT_FOUND)

    def test_failure_from_exception_marks_timeouts_retryable(self):
        handler = _make_handler(_FakeS3Client(), base_monitor_path="/tmp")

        result = handler._failure_from_exception(
            EndpointConnectionError(endpoint_url="https://example.invalid")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.kind, RemoteErrorKind.TIMEOUT)
        self.assertTrue(result.retryable)
        self.assertEqual(result.code, 1)

    def test_failure_from_exception_marks_access_denied_not_retryable(self):
        handler = _make_handler(_FakeS3Client(), base_monitor_path="/tmp")

        result = handler._failure_from_exception(
            ClientError({"Error": {"Code": "AccessDenied"}}, "HeadObject")
        )

        self.assertEqual(result.kind, RemoteErrorKind.ACCESS_DENIED)
        self.assertFalse(result.retryable)


if __name__ == "__main__":
    unittest.main()
