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

from app.monitor.s3_handler import S3Handler
from botocore.exceptions import ClientError


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
        code, message = handler.delete_folder("bucket/prefix")
        self.assertEqual(code, 1)
        self.assertIn("denied", message)

    def test_restore_folder_reports_failure_when_listing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = _make_handler(_FakeS3Client(), base_monitor_path=tmp)
            code, message = handler.restore_folder("bucket/prefix")
            self.assertEqual(code, 1)
            self.assertIn("denied", message)

    def test_sync_folder_reports_failure_when_listing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("hello", encoding="utf-8")
            handler = _make_handler(_FakeS3Client(), base_monitor_path=tmp)
            code, _ = handler.sync_folder(tmp)
            self.assertEqual(code, 1)

    def test_copy_folder_still_uploads_when_listing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("hello", encoding="utf-8")
            fake = _FakeS3Client()
            handler = _make_handler(fake, base_monitor_path=tmp)
            code, _ = handler.copy_folder(tmp)
            self.assertEqual(code, 0)
            self.assertEqual(len(fake.uploaded), 1)


if __name__ == "__main__":
    unittest.main()
