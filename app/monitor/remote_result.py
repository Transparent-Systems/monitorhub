"""
Typed outcome for remote storage operations.

This replaces the ad-hoc ``(result_code, result_output)`` tuples that
``RemoteHandler`` implementations used to return. The tuple could not express
*why* an operation failed and gave ``file_exists`` no way to distinguish an
expected "the path does not exist" from an unexpected failure such as an
access-denied or a network outage.
"""

from dataclasses import dataclass
from enum import StrEnum


class RemoteErrorKind(StrEnum):
    """Classification of a remote operation failure."""

    NOT_FOUND = "not_found"          # Expected: the remote path does not exist.
    ACCESS_DENIED = "access_denied"  # Credentials missing or insufficient.
    TIMEOUT = "timeout"              # The operation exceeded its time budget.
    TRANSIENT = "transient"          # Temporary; a later attempt may succeed.
    FATAL = "fatal"                  # Unrecoverable, or not otherwise classified.


@dataclass(frozen=True)
class RemoteResult:
    """
    Outcome of a remote storage operation.

    ``ok`` is True when the operation succeeded. For ``file_exists`` a True
    result means "the path exists", while a False result with
    ``kind is RemoteErrorKind.NOT_FOUND`` means "the path does not exist" —
    an expected answer rather than a failure to perform the check.

    ``code`` is the provider-specific status code when one exists (an S3 error
    code is textual, so it is reported through ``kind`` instead). ``retryable``
    records whether attempting the operation again could succeed.
    """

    ok: bool
    message: str = ""
    code: int | None = None
    kind: RemoteErrorKind | None = None
    retryable: bool = False

    @classmethod
    def success(cls, message: str = "", code: int | None = None) -> "RemoteResult":
        """Build a successful result."""
        return cls(ok=True, message=message, code=code)

    @classmethod
    def failure(
        cls,
        message: str = "",
        code: int | None = None,
        kind: RemoteErrorKind | None = None,
        retryable: bool = False,
    ) -> "RemoteResult":
        """Build a failed result, defaulting ``kind`` to FATAL when unspecified."""
        return cls(
            ok=False,
            message=message,
            code=code,
            kind=kind or RemoteErrorKind.FATAL,
            retryable=retryable,
        )

    @classmethod
    def not_found(cls, message: str = "", code: int | None = None) -> "RemoteResult":
        """Build an expected "the remote path does not exist" result."""
        return cls(
            ok=False,
            message=message,
            code=code,
            kind=RemoteErrorKind.NOT_FOUND,
        )

    def __bool__(self) -> bool:
        """Allow ``if result:`` to mean ``if result.ok:``."""
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return self.message or "ok"

        details = [self.kind.value if self.kind else RemoteErrorKind.FATAL.value]
        if self.code is not None:
            details.append(f"code={self.code}")
        if self.retryable:
            details.append("retryable")
        summary = ", ".join(details)
        return f"{summary}: {self.message}" if self.message else summary
