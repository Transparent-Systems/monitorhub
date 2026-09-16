from abc import ABC, abstractmethod

from app.monitor.remote_result import RemoteResult


class RemoteHandler(ABC):
    """
    Abstract Base Class that defines the contract for all remote storage backends.

    Naming conventions (fixed perspective of the monitor):
    - monitor_path: the local path being monitored
    - remote_path: the remote/cloud storage path

    Subclasses declare their supported profile type via the ``PROFILE_TYPE``,
    ``CATEGORY`` and ``DESCRIPTION`` class attributes. These values are the
    code-level equivalent of the old ``profile_types`` database lookup table,
    and ``PROFILE_TYPE`` is what a subclass registers with
    ``RemoteHandlerFactory``.
    """

    # Subclasses override these to declare their supported profile type.
    PROFILE_TYPE: str = ""
    CATEGORY: str = "remote"
    DESCRIPTION: str = ""

    # Shared exclude patterns applied by backup/restore handlers. Subclasses
    # should accept an ``exclude_patterns`` constructor argument and assign it
    # to this instance attribute (defaults to no exclusions).
    exclude_patterns: list[str]

    @abstractmethod
    def get_remote_path(self, monitor_path: str) -> str:
        """
        Derives remote path from base monitor path and this monitor path.
        Returns a string path.
        """

    @abstractmethod
    def file_exists(self, remote_path: str) -> RemoteResult:
        """
        Check whether the remote path exists.

        Returns a successful result when the path exists, a result with
        ``kind is RemoteErrorKind.NOT_FOUND`` when it does not, and a failure
        with another kind when the check itself could not be performed.
        """

    @abstractmethod
    def copy_file(self, monitor_path: str, remote_path: str | None = None) -> RemoteResult:
        """
        Copy monitor_path to remote_path.
        If remote_path is None, the remote_path is derived from the monitor_path.
        """

    @abstractmethod
    def copy_folder(self, monitor_path: str) -> RemoteResult:
        """
        Copy the monitor path to the derived remote path.
        The remote path can be automatically derived from the monitor path.
        """

    @abstractmethod
    def restore_folder(self, remote_path: str) -> RemoteResult:
        """
        Restore the remote path to the base monitor path.
        The direction is reversed compared to copy_folder: the source is remote
        and the destination is the base monitor path.
        """

    @abstractmethod
    def delete_file(self, remote_path: str) -> RemoteResult:
        """
        Delete file at remote_path.
        """

    @abstractmethod
    def delete_folder(self, remote_path: str) -> RemoteResult:
        """
        Delete objects in remote_path.
        """

    @staticmethod
    def normalize_path(path: str) -> str:
        """
        Shared utility: S3 and most cloud providers prefer forward slashes.
        """
        return path.replace('\\', '/').strip('/')
