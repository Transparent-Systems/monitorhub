"""
rclone_handler.py
Author: John Zoetebier
Date: 2025-05-10

Description:
    This script implements the RcloneHandler class, which provides functionality
    to copy or delete files and folders using the rclone tool. The class is
    designed to handle file operations in a reliable manner, ensuring compatibility
    with versioned file systems and folder structures.

    The script uses the rclone tool to copy or delete files and folders using rclone.
    You can download rclone from https://rclone.org/downloads/

Requirements:
- rclone must be installed and available in the system's PATH.
  You can download rclone from: https://rclone.org/downloads/

Usage:
- The RcloneHandler class can be used to copy files or folders to a specified
  destination or delete them if allowed. It is particularly useful for
  automating file operations in monitored folders.
- The class has been tested with Python >= 3.10 and rclone v1.64.2.
- The class is designed to be used in conjunction with a monitor hubing script.
"""

import logging
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from app.monitor.remote_handler import RemoteHandler


class RcloneHandler(RemoteHandler):
    """
    A class to copy or delete files and folders using rclone.
    The class has been tested with Python >= 3.10 and rclone v1.64.2.
    Rclone handler copy, delete and sync operations always use the same root monitor_path and root remote_path.
    """

    rclone_path = None
    is_windows = sys.platform.startswith('win')

    @classmethod
    def get_rclone_path(cls, logger: logging.Logger | None = None) -> str:
        if logger is None:
            logger = logging.getLogger(__name__)

        if RcloneHandler.rclone_path:
            return RcloneHandler.rclone_path
        
        RcloneHandler.rclone_path = shutil.which("rclone")
        if RcloneHandler.rclone_path is None:
            logger.error("rclone executable not found in the system's PATH.") 
            return ""

        # Convert RcloneHandler.rclone_path to posix string
        RcloneHandler.rclone_path = str(Path(RcloneHandler.rclone_path).as_posix())
        return RcloneHandler.rclone_path

    # Default timeout (in seconds) for rclone subprocesses. This guards against
    # a hung rclone process blocking the monitor indefinitely.
    DEFAULT_COMMAND_TIMEOUT = 3600.0

    # Interval (seconds) at which a still-running rclone command logs a warning.
    # This makes a hung rclone visible in the logs well before the timeout above.
    HANG_WARNING_INTERVAL = 30.0

    def __init__(
        self,
        base_monitor_path: str,
        base_remote_path: str,
        profile_name: str,
        logger: logging.Logger | None = None,
        command_timeout: float | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        """
        Docstring for __init__
        
        :param self: Instance of this class
        :param base_monitor_path: Local monitor path. Files are copied from/to this path.
        :param base_remote_path: remote path to copy to. This path is without the profile name commonly used in rclone.
        :profile_name: The profile name used in Rclone commands in format profile_name:remote_path
        :param logger: logger instance
        :param command_timeout: Optional timeout (seconds) for each rclone subprocess.
            Defaults to DEFAULT_COMMAND_TIMEOUT. Set to None to disable the timeout.
        """    
        self.logger = logger or logging.getLogger(__name__)
        self.command_timeout = (
            RcloneHandler.DEFAULT_COMMAND_TIMEOUT
            if command_timeout is None
            else command_timeout
        )

        # Get rclone_path
        self.rclone_path = RcloneHandler.get_rclone_path(logger=self.logger)

        if (profile_name is None):
            self.profile_name = ""
        else:
            self.profile_name = profile_name

        if self.profile_name != "":
            # Check if remote_path is in the conventional rclone format with remote_profile prefix (remote_profile:)
            remote_path_str = str(Path(base_remote_path).as_posix())
            if not remote_path_str.startswith(profile_name + ":"):
                base_remote_path = profile_name + ":" + base_remote_path

        self.base_remote_path = Path(base_remote_path)
        self.base_monitor_path = Path(base_monitor_path)
        self.exclude_patterns = exclude_patterns or []

    @staticmethod
    def test_connection(profile_name: str, logger: logging.Logger, prompt) -> tuple[int, str]:
        """
        Test Rclone connectivity by running the 'lsd' command.

        Prints results via the provided prompt service.
        """
        base_remote_path = f"{profile_name}:"
        handler = RcloneHandler(
            logger=logger,
            base_monitor_path="profile_test_temp_source",
            base_remote_path=base_remote_path,
            profile_name=profile_name,
        )
        rclone_parms = ["lsd", f"{profile_name}:"]
        try:
            result_code, result_output = handler.run_command(rclone_parms=rclone_parms)
            if result_code == 0:
                if "failed to create file system" in result_output.lower():
                    prompt.print(f"Connection failed to remote: {profile_name}")
                    prompt.print(f"Error output: {result_output}")
                else:
                    prompt.print(f"Connection successful to remote: {profile_name}")
                    prompt.print(f"Output: {result_output}")
            else:
                prompt.print(f"Connection failed to remote: {profile_name}")
                prompt.print(f"Error output: {result_output}")
                prompt.print("Test failed")
            return result_code, result_output
        except Exception as e:  # noqa: BLE001
            prompt.print(f"Connection failed to remote: {profile_name}")
            prompt.print(f"Error: {e}")
            return (1, f"Connection failed to remote: {profile_name}. Error: {e}")
    
    def run_command(
        self,
        rclone_parms: list[str],
        additional_args_str: str = "",
        timeout: float | None = None,
    ) -> tuple[int, str]:
        """
        Run rclone_command as a subprocess
        Return tuple (result_code and result_output)
        Param rclone_parms: list of commands
        Param additional_args_str: a string with arguments
        Param timeout: optional per-call timeout override (seconds). Falls back
            to the instance `command_timeout`. Pass 0 or a negative value to
            disable the timeout for this call.
        """

        if self.rclone_path is None:
            self.logger.error("rclone executable not found in the system's PATH.")
            return (1, "rclone executable not found in the system's PATH.")

        try:
            # Parse Additional Arguments Safely
            extra_args_list = shlex.split(additional_args_str, posix=not RcloneHandler.is_windows)
        except ValueError as e:
            self.logger.error(f"Error parsing arguments: {e}")
            return (1, f"Error parsing arguments: {e}")
        
        # Add rclone executable
        rclone_command = rclone_parms.copy()
        rclone_command.insert(0, RcloneHandler.get_rclone_path(logger=self.logger))
        # Add extra_args_list to rclone_command
        rclone_command.extend(extra_args_list)

        # Resolve the effective timeout for this invocation.
        effective_timeout = timeout if timeout is not None else self.command_timeout
        if effective_timeout is not None and effective_timeout <= 0:
            effective_timeout = None

        self.logger.debug(f"Running command: {' '.join(rclone_command)}")

        # Launch rclone and wait in short slices so we can detect (and log) a
        # hung command well before the overall timeout. We keep draining
        # stdout/stderr to avoid pipe-buffer deadlocks on large outputs.
        process = subprocess.Popen(
            rclone_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        start_time = time.monotonic()
        stdout = ""
        stderr = ""

        try:
            while True:
                # Compute how long to wait before the next hang check.
                wait = RcloneHandler.HANG_WARNING_INTERVAL
                if effective_timeout is not None:
                    remaining = effective_timeout - (time.monotonic() - start_time)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(rclone_command, effective_timeout)
                    wait = min(wait, remaining)

                try:
                    stdout, stderr = process.communicate(timeout=wait)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = time.monotonic() - start_time
                    if process.poll() is None:
                        self.logger.warning(
                            f"rclone command still running after {elapsed:.1f}s "
                            f"(pid={process.pid}): {' '.join(rclone_command)}"
                        )
                    else:
                        # Finished right at the boundary; collect the output.
                        stdout, stderr = process.communicate()
                        break
        except subprocess.TimeoutExpired:
            self.logger.error(
                f"Command timed out after {effective_timeout}s: {' '.join(rclone_command)}"
            )
            if process.poll() is None:
                process.kill()
                stdout, stderr = process.communicate()
            return (1, stderr or f"Command timed out after {effective_timeout}s")

        returncode = process.returncode
        elapsed = time.monotonic() - start_time
        self.logger.debug(
            f"Command finished in {elapsed:.2f}s (code={returncode}): {' '.join(rclone_command)}"
        )
        if returncode == 0:
            return (0, stdout.strip())

        return (returncode, stderr)

    def get_remote_path(self, monitor_path: str) -> str:
        """
        Derives remote path from base monitor path and this monitor_path
        """

        monitor_path_obj = Path(monitor_path)
        relative_path = monitor_path_obj.relative_to(self.base_monitor_path)
        remote_path = self.base_remote_path / relative_path
        return remote_path.as_posix()

    def get_rclone_version(self) -> tuple[int, str]:
        return self.run_command(["--version"])

    def list_remotes(self) -> tuple[int, str]:
        """
        List remotes configured
        """
        return self.run_command(["listremotes"])

    def file_exists(self, remote_path: str) -> tuple[int, str]:
        """
        Docstring for file_exists
        
        :param self: Instance of this class
        :param remote_path: Remote path to check for existence
        :type remote_path: str
        """
        (return_value, result_output) = self.run_command(
            ["ls", remote_path]
            )

        return (return_value, result_output)

    def copy_file(self, monitor_path: str, remote_path: str | None = None) -> tuple[int, str]:
        """
        Copy monitor_path to remote_path.
        If remote_path is None, the remote_path is derived from the monitor_path
        Returns:
            (result_code, result_output)
        """

        if remote_path is None:
            # Derive remote_path from monitor_path
            # Remote path will inlude the profile_name prefix
            remote_path = self.get_remote_path(monitor_path=monitor_path)
        else:
            # Check if profile_name is prefixed to remote_path, if not, prefix it
            if self.profile_name and not remote_path.startswith(self.profile_name + ":"):
                remote_path = f"{self.profile_name}:{remote_path}"

        # copyto can fail if the file has been deleted at the destination on a versioned file system
        (return_value, result_output) = self.run_command(
            ["copyto", monitor_path, remote_path]
        )

        if return_value == 0:
            return (return_value, result_output)

        # rclone copyto can fail if a file has been deleted at the destination on a versioned file system
        # If copyto fails, we try to copy the file using rclone --include
        # This is a fallback mechanism
        # Check result_output for MethodNotAllowed
        if "MethodNotAllowed" in result_output:
            monitor_path_obj = Path(monitor_path)
            file_name = monitor_path_obj.name
            monitor_folder = monitor_path_obj.parent
            remote_folder = self.get_remote_path(monitor_path=str(monitor_folder))
            return self.run_command(
                [
                    "copy",
                    str(monitor_folder),
                    remote_folder,
                    "--include",
                    file_name,
                ]
            )
        # Log copy_file failed
        self.logger.warning(f"copy_file failed; return_value={return_value}")
        return (return_value, result_output)

    def _exclude_args(self) -> list[str]:
        """Build repeated rclone ``--exclude`` flags from the configured patterns."""
        args: list[str] = []
        for pattern in self.exclude_patterns:
            args += ["--exclude", pattern]
        return args

    def copy_folder(self, monitor_path: str) -> tuple[int, str]:
        """
        Copy the monitor path to the derived remote path
        """

        remote_path = self.get_remote_path(monitor_path=monitor_path)

        # Copy the folder contents
        # This will not delete files at the destination that are not present in the source
        return self.run_command(
            ["copy", monitor_path, remote_path] + self._exclude_args()
        )
    
    def restore_folder(self, remote_path: str) -> tuple[int, str]:
        """
        Restore the remote path to the base monitor path.

        The direction is reversed compared to copy_folder: remote_path is
        the source and the destination is base_monitor_path.
        """

        # Prefix the profile name first if it's not already present in the remote_path
        if self.profile_name and not remote_path.startswith(self.profile_name + ":"):
            remote_path = f"{self.profile_name}:{remote_path}"
        return self.run_command(
            ["copy", remote_path, str(self.base_monitor_path)] + self._exclude_args()
        )

    def delete_file(self, remote_path: str) -> tuple[int, str]:
        """
        Delete file at remote_path
        """

        # Check if profile_name is prefixed to remote_path, if not, prefix it
        if self.profile_name and not remote_path.startswith(self.profile_name + ":"):
            remote_path = f"{self.profile_name}:{remote_path}"

        # We use rclone delete (instead of deletefile) as it also works when file does not exist on remote_path
        # This could happen is DirDeleteEvent is triggered before FileDeleteEvent
        # Using rclone delete reduces noise in the log
        return self.run_command(["delete", remote_path])

    def delete_folder(self, remote_path: str) -> tuple[int, str]:
        """
        Delete contents inside remote_path
        """

        return self.run_command(
            ["delete", "--rmdirs", remote_path]
        )

