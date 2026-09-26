"""Unit tests for S3Handler's handling of listing failures.

These tests need no credentials or network access: they inject a fake S3
client so we can assert that a failed listing is reported as a failure
(rather than a silent success) for delete/restore, while a backup
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
from app.monitor.s3_factory import S3Factory
from app.monitor.s3_handler import S3Handler

# The failure paths under test log warning/error records on the handler logger.
# Quiet that logger by default so the test run is not polluted by expected
# output; ``assertLogs`` still captures the records for the assertions below.
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.CRITICAL)
LOGGER.propagate = False


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


class _ListedPaginator:
    """Paginator that yields a single page containing the supplied objects."""

    def __init__(self, objects: list[dict]) -> None:
        self._objects = objects

    def paginate(self, **kwargs):
        yield {"Contents": self._objects}


class _ListedS3Client:
    """Fake S3 client that lists the supplied objects and records uploads."""

    def __init__(self, objects: list[dict]) -> None:
        self._objects = objects
        self.uploaded: list[tuple[str, str, str]] = []

    def get_paginator(self, name: str):
        return _ListedPaginator(self._objects)

    def head_object(self, **kwargs):
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def upload_file(self, filename, bucket, key, **kwargs):
        self.uploaded.append((filename, bucket, key))


class _FakeHttpResponse:
    """Minimal stand-in for botocore's ``AWSResponse`` (status only)."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _make_handler(fake_client, base_monitor_path: str, base_remote_path: str = "bucket/prefix") -> S3Handler:
    """Build an S3Handler whose client is the supplied fake (no boto3 call)."""
    with mock.patch("app.monitor.s3_handler.S3Factory") as factory_cls:
        factory_cls.return_value.get_s3_client.return_value = fake_client
        return S3Handler(
            base_monitor_path=base_monitor_path,
            base_remote_path=base_remote_path,
            profile_config={},
            logger=LOGGER,
        )


class TestS3HandlerListingFailure(unittest.TestCase):
    """A2: a failed object listing must not be reported as success."""

    def test_list_objects_raises_on_failure(self):
        handler = _make_handler(_FakeS3Client(), base_monitor_path="/tmp")
        with self.assertRaises(ClientError):
            handler._list_objects("bucket", "prefix/")

    def test_delete_folder_reports_failure_when_listing_fails(self):
        handler = _make_handler(_FakeS3Client(), base_monitor_path="/tmp")
        with self.assertLogs(LOGGER, level="ERROR") as captured:
            result = handler.delete_folder("bucket/prefix")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 1)
        self.assertEqual(result.kind, RemoteErrorKind.ACCESS_DENIED)
        self.assertIn("denied", result.message)
        self.assertEqual(len(captured.output), 1)
        self.assertIn("Error deleting folder bucket/prefix:", captured.output[0])

    def test_restore_folder_reports_failure_when_listing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = _make_handler(_FakeS3Client(), base_monitor_path=tmp)
            with self.assertLogs(LOGGER, level="ERROR") as captured:
                result = handler.restore_folder("bucket/prefix")
            self.assertFalse(result.ok)
            self.assertEqual(result.code, 1)
            self.assertEqual(result.kind, RemoteErrorKind.ACCESS_DENIED)
            self.assertIn("denied", result.message)
            self.assertEqual(len(captured.output), 1)
            self.assertIn("Error listing objects for restore:", captured.output[0])

    def test_copy_folder_still_uploads_when_listing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("hello", encoding="utf-8")
            fake = _FakeS3Client()
            handler = _make_handler(fake, base_monitor_path=tmp)
            with self.assertLogs(LOGGER, level="WARNING") as captured:
                result = handler.copy_folder(tmp)
            self.assertTrue(result.ok)
            self.assertEqual(len(fake.uploaded), 1)
            self.assertEqual(len(captured.output), 1)
            self.assertIn("Could not list remote objects at s3://bucket/prefix/", captured.output[0])


class TestS3HandlerCopyFolderMetadataRace(unittest.TestCase):
    """A file that vanishes or becomes unreadable must not abort the backup.

    Regression: ``copy_folder`` compared metadata with an unguarded
    ``stat()``/``_calculate_md5()``. An ``OSError`` there escaped ``copy_folder``
    and killed the scheduled backup worker thread, silently stopping every
    subsequent run for that monitor.
    """

    def test_missing_file_is_recorded_and_other_files_still_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "present.txt").write_text("hello", encoding="utf-8")
            fake = _ListedS3Client(
                [{"Key": "prefix/ghost.txt", "Size": 1, "ETag": '"etag"'}]
            )
            handler = _make_handler(fake, base_monitor_path=tmp)

            def fake_walk(_path):
                # ghost.txt is listed remotely but no longer exists on disk.
                yield (tmp, [], ["present.txt", "ghost.txt"])

            with mock.patch("app.monitor.s3_handler.os.walk", side_effect=fake_walk):
                with self.assertLogs(LOGGER, level="ERROR") as captured:
                    result = handler.copy_folder(tmp)

            self.assertFalse(result.ok)
            self.assertIn("ghost.txt", result.message)
            uploaded_keys = [key for _, _, key in fake.uploaded]
            self.assertIn("prefix/present.txt", uploaded_keys)
            self.assertNotIn("prefix/ghost.txt", uploaded_keys)
            self.assertTrue(
                any("Skipping" in line for line in captured.output)
            )

    def test_unreadable_file_is_recorded_and_other_files_still_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("hello", encoding="utf-8")
            (Path(tmp) / "b.txt").write_text("world", encoding="utf-8")
            fake = _ListedS3Client(
                [{"Key": "prefix/a.txt", "Size": 5, "ETag": '"deadbeef"'}]
            )
            handler = _make_handler(fake, base_monitor_path=tmp)

            def failing_md5(_path):
                raise OSError("cannot read")

            with mock.patch.object(
                S3Handler, "_calculate_md5", side_effect=failing_md5
            ):
                with self.assertLogs(LOGGER, level="ERROR") as captured:
                    result = handler.copy_folder(tmp)

            self.assertFalse(result.ok)
            self.assertIn("cannot read", result.message)
            uploaded_keys = [key for _, _, key in fake.uploaded]
            self.assertIn("prefix/b.txt", uploaded_keys)
            self.assertNotIn("prefix/a.txt", uploaded_keys)
            self.assertTrue(any("Skipping" in line for line in captured.output))


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


class TestS3FactoryProviderDetection(unittest.TestCase):
    """The AWS branch matches the provider names MonitorHub and rclone use.

    The built-in provider is named ``AWS`` (the rclone remote key); a legacy
    CLI-created name (``Amazon AWS S3``) and any rclone-imported name containing
    ``amazon`` must take the same region-only path.  Regression: the check once
    compared the provider name to the bare string ``"aws"``, so those names never
    took the region-only path.
    """

    def _client_kwargs(self, profile_config: dict) -> dict:
        with mock.patch("app.monitor.s3_factory.boto3.client") as client:
            S3Factory(logger=LOGGER).get_s3_client(profile_config)
        return client.call_args.kwargs

    def test_amazon_provider_omits_endpoint_url(self):
        kwargs = self._client_kwargs(
            {
                "provider_name": "Amazon AWS S3",
                "access_key_id": "key",
                "secret_access_key": "secret",
                "region": "us-east-1",
            }
        )
        self.assertNotIn("endpoint_url", kwargs)
        self.assertEqual(kwargs["region_name"], "us-east-1")

    def test_bare_aws_rclone_key_omits_endpoint_url(self):
        kwargs = self._client_kwargs(
            {
                "provider_name": "AWS",
                "access_key_id": "key",
                "secret_access_key": "secret",
                "region": "eu-west-1",
            }
        )
        self.assertNotIn("endpoint_url", kwargs)

    def test_non_amazon_provider_uses_endpoint_url(self):
        kwargs = self._client_kwargs(
            {
                "provider_name": "IDrive",
                "access_key_id": "key",
                "secret_access_key": "secret",
                "endpoint": "example.invalid",
            }
        )
        self.assertIn("endpoint_url", kwargs)

    def test_secret_access_key_is_passed_to_client(self):
        # An rclone-imported profile stores the secret under rclone's own key
        # name; the built-in handler reads that same key.  Regression: it read
        # ``access_key_secret`` only, so switching an imported profile from
        # rclone to the built-in handler failed with PartialCredentialsError.
        kwargs = self._client_kwargs(
            {
                "provider_name": "AWS",
                "access_key_id": "key",
                "secret_access_key": "secret",
                "region": "us-east-1",
            }
        )
        self.assertEqual(kwargs["aws_secret_access_key"], "secret")
        self.assertEqual(kwargs["aws_access_key_id"], "key")


class TestS3FactoryRetryLogging(unittest.TestCase):
    """Only genuinely retryable S3 responses may be logged as retries.

    Regression: the ``needs-retry`` callback logged every error code, so the
    benign 404 from a HEAD on a not-yet-uploaded object was reported as
    "Retrying S3 request due to: 404" even though botocore did not retry.
    """

    def setUp(self):
        self.factory = S3Factory(logger=LOGGER)

    @staticmethod
    def _response(status_code: int, code: str | None = None) -> tuple:
        parsed: dict = {"ResponseMetadata": {"HTTPStatusCode": status_code}}
        if code is not None:
            parsed["Error"] = {"Code": code}
        return (_FakeHttpResponse(status_code), parsed)

    def _call(self, **kwargs):
        """Invoke the callback and return the patched debug/warning mocks."""
        with mock.patch.object(LOGGER, "debug") as debug, mock.patch.object(
            LOGGER, "warning"
        ) as warning:
            self.factory._log_retry_events(**kwargs)
        return debug, warning

    def test_missing_object_404_is_not_logged_as_a_retry(self):
        debug, warning = self._call(attempts=1, response=self._response(404, "404"))
        debug.assert_not_called()
        warning.assert_not_called()

    def test_successful_response_is_not_logged(self):
        debug, warning = self._call(attempts=1, response=self._response(200))
        debug.assert_not_called()
        warning.assert_not_called()

    def test_access_denied_is_not_logged_as_a_retry(self):
        debug, warning = self._call(
            attempts=1, response=self._response(403, "AccessDenied")
        )
        debug.assert_not_called()
        warning.assert_not_called()

    def test_throttling_code_logs_a_warning(self):
        debug, warning = self._call(attempts=1, response=self._response(400, "SlowDown"))
        warning.assert_called_once()
        self.assertIn("THROTTLED", warning.call_args.args[0])
        self.assertIn("SlowDown", warning.call_args.args[0])
        debug.assert_not_called()

    def test_transient_error_code_logs_a_retry(self):
        debug, warning = self._call(
            attempts=1, response=self._response(400, "RequestTimeout")
        )
        debug.assert_called_once()
        self.assertIn(
            "Retrying S3 request due to: RequestTimeout", debug.call_args.args[0]
        )
        warning.assert_not_called()

    def test_transient_status_code_logs_a_retry(self):
        debug, warning = self._call(attempts=1, response=self._response(503))
        debug.assert_called_once()
        self.assertIn(
            "Retrying S3 request due to: HTTP 503", debug.call_args.args[0]
        )
        warning.assert_not_called()

    def test_connection_exception_logs_a_retry(self):
        debug, warning = self._call(
            attempts=1,
            response=None,
            caught_exception=EndpointConnectionError(
                endpoint_url="https://example.invalid"
            ),
        )
        debug.assert_called_once()
        self.assertIn("EndpointConnectionError", debug.call_args.args[0])
        warning.assert_not_called()

    def test_final_attempt_is_not_logged(self):
        """On the last attempt botocore will not retry, so nothing is logged."""
        debug, warning = self._call(
            attempts=self.factory._MAX_ATTEMPTS,
            response=self._response(400, "SlowDown"),
        )
        debug.assert_not_called()
        warning.assert_not_called()

    def test_max_attempts_matches_botocore_total_attempts(self):
        """The logging cap must match botocore's derived total attempt count.

        Client ``max_attempts`` means *retries*; botocore adds one for the
        initial request (and drops the ``max_attempts`` key), so the cap has to
        be ``_MAX_RETRIES + 1``.
        """
        client = S3Factory(logger=LOGGER).get_s3_client(
            {
                "provider_name": "Amazon AWS S3",
                "access_key_id": "key",
                "secret_access_key": "secret",
                "region": "us-east-1",
            }
        )
        retries = client.meta.config.retries
        self.assertEqual(retries["mode"], "standard")
        self.assertNotIn("max_attempts", retries)
        self.assertEqual(retries["total_max_attempts"], S3Factory._MAX_ATTEMPTS)
        self.assertEqual(S3Factory._MAX_ATTEMPTS, S3Factory._MAX_RETRIES + 1)


if __name__ == "__main__":
    unittest.main()
