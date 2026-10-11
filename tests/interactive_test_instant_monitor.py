"""
Version: 1.0.0

This script runs integration tests for an instant monitor.
The script creates and starts and instant monitor. No manual action required.
It uses the unittest framework to execute tests sequentially.

Pre-requisites:
    Ensure there is at least one properly working remote profile configured in the test database

Run from the project root with:
    python -m tests.interactive_test_instant_monitor --help
"""

import argparse
import logging
import shutil
import sys
import time
import unittest
from pathlib import Path

from app.cli.monitor_commands import MonitorCommands
from app.cli.prompt_service import PromptService
from app.monitor.handler_factory import REMOTE_HANDLERS
from app.monitor.rclone_handler import RcloneHandler
from app.monitor.remote_handler import RemoteHandler
from app.monitor.remote_result import RemoteResult
from app.monitor.s3_handler import S3Handler
from app.utils import reference_data
from app.utils.constants import (
    MONITOR_STATUS_RUNNING,
    MONITOR_STATUS_STOP,
    MONITOR_STATUS_STOPPED,
    MONITOR_TYPE_INSTANT,
)
from app.utils.logger_setup import setup_logging
from app.utils.sqlite_handler import SQLiteHandler
from tests.util.testing_util import (
    create_big_file,
    create_test_data,
    delete_test_data,
)


class CheckPath:
    """
    Checks if a remote path exists.
    The main purpose of this class is to delay a test to allow monitorhub to action on the remote.

    Args:
        remote_handler (RemoteHandler): An instance of RemoteHandler.
        check_delay (int | float): Optional delay timer (in seconds) before checking.
        max_retries (int): Maximum number of poll attempts while waiting for the expected state.
        retry_interval (float): Seconds to wait between poll attempts.
    """

    def __init__(
        self,
        remote_handler: RemoteHandler,
        check_delay: float = 0,
        max_retries: int = 10,
        retry_interval: float = 1.0,
    ):
        if remote_handler is None:
            raise ValueError("remote_handler must be provided")
        self.remote_handler = remote_handler
        self.check_delay = check_delay
        self.max_retries = max_retries
        self.retry_interval = retry_interval

    def file_exists(self, remote_path: str, should_exist: bool) -> RemoteResult:
        """
        Check if remote_path exists, polling until the expected state is reached.

        When `should_exist` is True, polls until the remote path exists
        (a successful result) or `max_retries` attempts are exhausted.

        When `should_exist` is False, polls until the remote path no longer
        exists (a failed result) or `max_retries` attempts are exhausted.
        """
        if self.check_delay > 0:
            time.sleep(self.check_delay)

        result = self.remote_handler.file_exists(remote_path)
        for _ in range(self.max_retries):
            result_as_expected = result.ok if should_exist else not result.ok
            if result_as_expected:
                return result
            time.sleep(self.retry_interval)
            result = self.remote_handler.file_exists(remote_path)

        return result



class TestMonitorHubIntegration(unittest.TestCase):
    """
    Integration tests for MonitorHub.
    This integration test class is designed to be run against a monitor that is already running in a separate process.
    It checks the instant monitor's ability to detect and synchronize file system changes to a remote location.
    The instant monitor is created and started by the integration test and requires no manual intevention
    """
    logger : logging.Logger
    monitor : dict[str, str]
    remote_handler : RemoteHandler
    check_delay = 1

    @classmethod
    def setUpClass(cls):
        if not cls.logger:
            raise ValueError("Logger not set")
        if not cls.monitor:
            raise ValueError("Monitor not set")
        if not cls.remote_handler:
            raise ValueError("Remote Handler not set")
        if not cls.check_delay:
            raise ValueError("Profile not set")

        cls.monitor_path = cls.monitor.get("monitor_path", "")
        cls.remote_path = cls.monitor.get("remote_path")
        cls.monitor_name = cls.monitor.get("name")

        # Setup CheckPath
        cls.check_path = CheckPath(remote_handler=cls.remote_handler, check_delay=cls.check_delay)
        cls.logger.info(f"Ready setUpClass for monitor: {cls.monitor_name}")

        # Wait until the monitor is actually processing filesystem events.
        cls._wait_until_monitor_listening()

    @classmethod
    def _wait_until_monitor_listening(cls, max_attempts: int = 10, wait_seconds: float = 1.0) -> None:
        """Block until the running monitor is actually processing events.

        Writes a canary file under the monitored folder and waits for it to appear
        on the remote. inotify does not replay files that existed before the watch
        was installed, so the canary is *re-written* every attempt — the first write
        after the observer goes live is what gets captured.
        """
        canary_name = ".__monitor_ready_probe__.txt"
        canary_local = Path(cls.monitor_path) / canary_name
        canary_remote = cls.remote_handler.get_remote_path(monitor_path=str(canary_local))

        try:
            for attempt in range(1, max_attempts + 1):
                # Re-write (not touch) so a fresh filesystem event fires each
                # attempt, even once the file already exists.
                canary_local.write_text(f"monitor readiness probe attempt {attempt}\n")
                time.sleep(wait_seconds)  # allow event -> dispatch -> upload

                result = cls.remote_handler.file_exists(canary_remote)
                if result.ok:
                    cls.logger.info(
                        f"Monitor '{cls.monitor_name}' is listening "
                        f"(canary detected on remote after {attempt} attempt(s))"
                    )
                    return

            raise RuntimeError(
                f"Monitor '{cls.monitor_name}' did not pick up the canary after "
                f"{max_attempts} attempts — the observer is not listening."
            )
        finally:
            if canary_local.exists():
                canary_local.unlink()

    def setUp(self):
        """Run before each test"""

    def tearDown(self):
        """Run after each test"""

    def test_01_create_new_file(self):
        """Create new file"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "test1.txt"

        # Step 1
        # Create the file regardless if it exists or not on monitor path
        file_path = create_test_data(path=self.monitor_path, files=[file_name])
        remote_path = self.remote_handler.get_remote_path(monitor_path=file_path.as_posix())
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=True)
        self.assertTrue(result.ok, f"File {file_name} should exist at {remote_path}.")

        # Step 2
        # Delete the file to ensure we create a new file in step 3
        file_path = delete_test_data(path=self.monitor_path, files=[file_name])
        remote_path = self.remote_handler.get_remote_path(monitor_path=file_path.as_posix())
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=False)
        self.assertFalse(result.ok, f"File {file_name} should not exist at {remote_path}.")

        # Step 3
        # Now create the file again
        file_path = create_test_data(path=self.monitor_path, files=[file_name])
        remote_path = self.remote_handler.get_remote_path(monitor_path=file_path.as_posix())
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=True)
        self.assertTrue(result.ok, f"File {file_name} should exist at {remote_path}.")

    def test_03_delete_file_with_spaces(self):
        """Delete a file"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "file with spaces test1.txt"
        
        # Ensure file exists first (setup)
        create_test_data(path=self.monitor_path, files=[file_name])
        # Wait for sync
        time.sleep(self.check_delay)
        file_path = delete_test_data(path=self.monitor_path, files=[file_name])
        self.logger.debug(f"Deleted source file : '{file_path}'")
        remote_path = self.remote_handler.get_remote_path(monitor_path=file_path.as_posix())
        time.sleep(self.check_delay)
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=False)
        self.assertFalse(result.ok, f"File {file_name} should not exist at {remote_path}.")


    def test_04_create_subfolder_with_files(self):
        """Create subfolder with files. Check last file only"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        files = [
            "Subfolder3/test1.txt",
            "Subfolder3/test2.txt",
            "Subfolder3/test3.txt"
        ]
        
        # Clean up
        delete_test_data(path=self.monitor_path, files=["Subfolder3"])
        time.sleep(self.check_delay)
        file_path = create_test_data(path=self.monitor_path, files=files)
        remote_path = self.remote_handler.get_remote_path(monitor_path=file_path.as_posix())
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=True)
        self.assertTrue(result.ok, f"File {remote_path} should exist.")

    def test_05_delete_subfolder(self):
        """Delete subfolder"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        # Wait for sync
        time.sleep(self.check_delay)

        file_path = delete_test_data(path=self.monitor_path, files=["Subfolder4"])
        remote_path = self.remote_handler.get_remote_path(monitor_path=file_path.as_posix())
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=False)
        self.assertFalse(result.ok, f"File {remote_path} should not exist.")
        
    def test_06_rename_file(self):
        """Rename file"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        files = ["old_file.txt"]
        
        # Clean
        delete_test_data(path=self.monitor_path, files=["old_file.txt", "new_file.txt"])
        
        old_file_path = create_test_data(path=self.monitor_path, files=files)
        # Wait for files to be created
        time.sleep(self.check_delay)
        
        # Rename the file
        new_file_path = Path(self.monitor_path) / Path("new_file.txt")
        if new_file_path.exists():
            new_file_path.unlink()

        old_file_path.rename(new_file_path)

        # Check if old file has been deleted from destination
        remote_path = self.remote_handler.get_remote_path(monitor_path=old_file_path)
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=False)
        self.assertFalse(result.ok, f"Old file {remote_path} should not exist.")

        # Check if new file exists at destination
        remote_path = self.remote_handler.get_remote_path(monitor_path=new_file_path)
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=True)
        self.assertTrue(result.ok, f"New file {remote_path} should exist.")

    def test_07_rename_subfolder(self):
        """Rename subfolder"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        files = ["Subfolder-old/test1.txt", "Subfolder-old/test2.txt"]
        
        # Clean up source
        if (Path(self.monitor_path) / "Subfolder-old").exists():
            shutil.rmtree(Path(self.monitor_path) / "Subfolder-old")
        if (Path(self.monitor_path) / "Subfolder-new").exists():
            shutil.rmtree(Path(self.monitor_path) / "Subfolder-new")
            
        file_path = create_test_data(path=self.monitor_path, files=files)
        # Wait for monitorhub upload
        time.sleep(self.check_delay + 1)

        # Rename Subfolder-old to Subfolder-new
        new_path = Path(self.monitor_path) / Path("Subfolder-new")
        head_old = file_path.parent
        head_old.replace(target=new_path.as_posix())
        
        # Check if new file exists at remote
        new_path = Path(self.monitor_path) / "Subfolder-new" / "test1.txt"
        remote_path = self.remote_handler.get_remote_path(new_path)
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=True)
        self.assertTrue(result.ok, f"New file {remote_path} should exist.")

    def test_08_write_big_file(self):
        """Write big file"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "big-test-file.txt"

        # Delete big file first
        delete_test_data(path=self.monitor_path, files=[file_name])
        # Create big file
        file_path = create_big_file(path=self.monitor_path, filename=file_name, write_duration_seconds=10)
        # Wait for sync
        time.sleep(self.check_delay)
        remote_path = self.remote_handler.get_remote_path(monitor_path=file_path.as_posix())
        result = self.check_path.file_exists(remote_path=remote_path, should_exist=True)
        self.assertTrue(result.ok, f"New file {remote_path} should exist.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run integration tests for monitor hubs using unittest."
    )
    parser.add_argument(
        "-d", "--db-dir",
        type=str,
        default="testdb/dev",
        metavar="<PATH>",
        help="Directory of SQlite database"
    )
    parser.add_argument(
        "--log-file-name",
        type=str,
        default="interactive_test_instant_monitor.log",
        help="Log file name."
    )
    parser.add_argument(
        "-l", "--log",
        type=str,
        default="conf/log.yaml",
        help="Path to the log configuration file",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override the log level from the configuration file",
    )
    parser.add_argument(
        "--dependency-log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=(
            "Override the log level of the third-party libraries "
            "(boto3/botocore/s3transfer/urllib3); defaults to WARNING"
        ),
    )
    parser.add_argument(
        "--check-delay",
        type=float,
        default=1.0,
        help="Delay in seconds to wait before checking results."
    )
    parser.add_argument(
        "-t",
        "--test-cases",
        type=str,
        nargs="+",
        help="Space-separated list of test method names (or substrings) to run."
    )
    parser.add_argument(
        "-p",
        "--profile-type",
        type=str,
        default="ftp",
        help="Profile type you want to link to the test monitor created for this test, For example 'ftp' will select an ftp profile"
    )
    args = parser.parse_args()

    # Setup logging
    logger, log_config = setup_logging(
        args.log,
        log_level=args.log_level,
        log_file=args.log_file_name,
        dependency_log_level=args.dependency_log_level,
    )
    logger.info("Starting script")

    # Iterate over monitors
    sqlite_handler = SQLiteHandler(
        logger=logger,
        db_dir=args.db_dir
    )

    overall_success = True

    monitor_path = Path("testdata/source/instant-monitor")
    if not monitor_path.exists():
        logger.warning(f"Monitor path '{monitor_path}' does not exist. Creating it.")
        if not create_test_data(monitor_path, []):
            logger.warning(f"Failed to create path {monitor_path}.")
            sys.exit(1)

    # Remove test monitor and linked profile if test monitor exists
    monitor_name="interactive_test_monitor-1"
    remote_path="test-monitorhub/instant-monitor"
    monitor_type=MONITOR_TYPE_INSTANT

    monitor = sqlite_handler.get_monitor(monitor_name=monitor_name)
    if monitor:
        # If monitor stil running them stop it
        if monitor.get("status", "") == MONITOR_STATUS_RUNNING:
            # Set status to stop
            monitor_id = monitor.get("id","0")
            if not sqlite_handler.update_monitor_status(monitor_id=monitor_id, status=MONITOR_STATUS_STOP):
                logger.warning(f"Cannot set monitor status to {MONITOR_STATUS_STOP} if monitor {monitor_name}")
                sys.exit(1)
            # Wait for 10 seconds
            time.sleep(10)            

        # Get linked profiles and remove them
        monitor_id = monitor.get("id","0")
        profiles = sqlite_handler.get_profiles_for_monitor(monitor_id)
        for profile in profiles:
            profile_id = profile.get("id", "0")
            if not sqlite_handler.delete_monitor_profile_map(monitor_id=monitor_id, profile_id=profile_id):
                logger.warning(f"Cannot remove monitor {monitor_id} , profile {profile_id} from monitor-profile map")
        if not sqlite_handler.delete_monitor(monitor_id=monitor_id):
            logger.warning(f"Cannot remove test monitor {monitor_name}")
            sys.exit(1)

    monitor_id = sqlite_handler.add_monitor(
        name=f"{monitor_name}",
        monitor_path=f"{monitor_path}",
        remote_path=f"{remote_path}",
        monitor_type=MONITOR_TYPE_INSTANT,
        config={},
        status=MONITOR_STATUS_STOPPED
    )

    if monitor_id is None:
        logger.warning("Failed to create new test monitor ")
        sys.exit(1)

    monitor = sqlite_handler.get_monitor(monitor_id=monitor_id)
    # Add an existing profile selected by args.profile_type
    profile_type_selected: str = args.profile_type
    test_monitor_profiles = []
    profiles = sqlite_handler.get_profiles()
    for profile in profiles:
        # Filter on remote profiles
        profile_type: str = profile.get("profile_type", "")
        if reference_data.get_profile_category(profile_type=profile_type) != "remote":
            continue
        if profile_type.lower() == profile_type_selected.lower():
            # Add profile to monitor as it is used in run_monitor
            profile_id = profile.get("id", "0")
            if not sqlite_handler.add_monitor_profile_map(monitor_id=monitor_id, profile_id=profile_id):
                logger.debug(f"Cannot add profile {profile_id} to monitor {monitor_id}")
                sys.exit(1)
            test_monitor_profiles.append(profile)
            break   # One profile only simplifies testing

    # Start monitor exactly as from the command line
    prompt = PromptService()
    monitor_commands = MonitorCommands(
        logger=logger,
        log_level=args.log_level,
        dependency_log_level=args.dependency_log_level,
        log_config=args.log,
        sqlite_handler=sqlite_handler,
        db_dir=args.db_dir,
        prompt=prompt
    )

    monitor_commands.start(monitor_id=monitor_id)
    # Get latest monitor from database
    monitor = sqlite_handler.get_monitor(monitor_id=monitor_id)
    pid = monitor.get("pid", "0")
    logger.info(f"Started monitor process (pid={pid}) for monitor_id={monitor_id}")

    # Iterate all profiles of this monitor
    for profile in test_monitor_profiles:
        # If the profile type maps to a native handler we instantiate a
        # MonitorHub handler (currently an s3 handler); otherwise an Rclone handler.
        profile_type = profile.get("profile_type")
        if profile_type in REMOTE_HANDLERS:
            s3_handler = S3Handler(
                logger=logger,
                base_monitor_path=monitor.get("monitor_path", ""),
                base_remote_path=monitor.get("remote_path", ""),
                profile_config=profile.get("config", {})
            )
            remote_handler = s3_handler
        else:
            rclone_handler = RcloneHandler(
                logger=logger,
                base_monitor_path=monitor.get("monitor_path", ""),
                base_remote_path=monitor.get("remote_path", ""),
                profile_name=profile.get("name", "")
            )
            remote_handler = rclone_handler

        # Inject configuration into Test Class
        TestMonitorHubIntegration.logger = logger
        TestMonitorHubIntegration.monitor = monitor
        TestMonitorHubIntegration.remote_handler = remote_handler
        TestMonitorHubIntegration.check_delay = args.check_delay

        logger.info(f"Running tests for monitor: {monitor.get('name')}")
        
        # Run Tests
        loader = unittest.TestLoader()
        full_suite = loader.loadTestsFromTestCase(TestMonitorHubIntegration)

        if args.test_cases is None or len(args.test_cases) == 1 and (args.test_cases[0] == "" or args.test_cases[0] == "*"):
            suite = full_suite
        elif args.test_cases:    # Flatten arguments in case they were passed as a single string with spaces
            patterns = []
            for item in args.test_cases:
                patterns.extend(item.split())

            suite = unittest.TestSuite()
            for test in full_suite:
                # test._testMethodName contains the name of the test method
                if isinstance(test, unittest.TestCase) and any(
                    pattern in test._testMethodName for pattern in patterns
                ):
                    suite.addTest(test)
            
            if suite.countTestCases() == 0:
                logger.warning(f"No tests matched patterns: {patterns}")
        else:
            suite = full_suite

        result = unittest.TextTestRunner(verbosity=2).run(suite)
        
        if not result.wasSuccessful():
            overall_success = False
            logger.error(f"Tests failed for monitor: {monitor.get('name')}")

        # For now, test one profile only
        break

    # Stop monitor gracefully
    monitor_commands.stop(monitor_id=monitor_id)
    # Remove monitor from monitor_profile_map
    for profile in test_monitor_profiles:
        profile_id = profile.get("id", 0)
        if sqlite_handler.delete_monitor_profile_map(monitor_id=monitor_id, profile_id=profile_id):
            logger.info(f"Removed monitor {monitor_id} , profile {profile_id} from monitor_profile_map")
        else:
            logger.warning(f"Failed to remove monitor {monitor_id} , profile {profile_id} from monitor_profile_map")

    # Wait till monitor status is "stopped"
    for i in range(10):
        monitor = sqlite_handler.get_monitor(monitor_id=monitor_id)
        if monitor.get("status", "") == MONITOR_STATUS_STOPPED:
            break
        time.sleep(1)

    # Remove the test monitor created for this test run
    if sqlite_handler.delete_monitor(monitor_id=monitor_id):
        logger.info(f"Removed test monitor (id={monitor_id})")
    else:
        logger.warning(f"Failed to remove test monitor (id={monitor_id})")

    sqlite_handler.close()

    if not overall_success:
        logger.warning("Not all tests tests passed successfully.")
    else:
        logger.info("All tests passed successfully.")