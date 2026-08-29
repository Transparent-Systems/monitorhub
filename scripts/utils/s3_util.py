"""
Utility functions and classes for S3 operations.
"""
import time

from scripts.s3_handler import S3Handler


class S3CheckPath:
    """
    Checks if a remote path exists on S3.
    Allows specifying an optional delay before checking for asynchronous test validation.

    Args:
        s3_handler (S3Handler): An instance of S3Handler.
        check_delay (int | float): Optional delay timer (in seconds) before checking.
    """

    def __init__(self, s3_handler: S3Handler, check_delay: float = 0):
        self.s3_handler = s3_handler
        self.check_delay = check_delay

    def file_exists(self, remote_path: str) -> bool:
        """
        Check if remote_path exists in S3.
        Returns True when the remote path exists, False otherwise.
        """
        if self.check_delay > 0:
            time.sleep(self.check_delay)
        code, _ = self.s3_handler.file_exists(remote_path)
        return code == 0
