"""
Version: 1.0.0

Test integration script for S3 handler.
The script iterates over monitors configured in a yaml file.
The same test suite is used for each monitor.
Refactored to use unittest.TestCase.
Ensure no monitor hub is currently running on any configured test monitor to avoid conflicts.
"""

import argparse
import logging
import logging.handlers
import sys
import unittest
from pathlib import Path

import yaml

from scripts.s3_handler import S3Handler
from scripts.sqlite_handler import SQLiteHandler
from tests.util.testing_util import create_test_data
from tests.database_test_data import DatabaseTestData


class TestS3HandlerIntegration(unittest.TestCase):
    monitor = {}
    profile_config = {}
    logger : logging.Logger
    
    @classmethod
    def setUpClass(cls):
        # Skip gracefully when run via `unittest discover` (make test-unit):
        # monitor/profile_config are only injected when this module is run directly.
        if not cls.monitor or not cls.profile_config or not getattr(cls, "logger", None):
            raise unittest.SkipTest(
                "Integration test: no monitor/profile injected. "
                "Run directly: python -m tests.test_s3_handler_integration "
                "(or `make test-integration`)."
            )

        cls.monitor_name = cls.monitor.get("name")
        cls.logger.info(f"Setting up tests for monitor: {cls.monitor_name}")

        # Setup Source Path
        raw_source = cls.monitor.get("monitor_path", "")
        raw_source_stripped = raw_source.rstrip('/')
        subfolder = "test-s3-handler-integration"
        cls.monitor_path = f"{raw_source_stripped}/{subfolder}"
        
        # Setup Destination Path
        raw_dest = cls.monitor.get("remote_path", "")
        raw_dest_stripped = raw_dest.rstrip('/')
        cls.remote_path =f"{raw_dest_stripped}/{subfolder}"
        cls.s3_handler = S3Handler(
            logger=cls.logger,
            base_monitor_path=cls.monitor_path,
            base_remote_path=cls.remote_path,
            profile_config=cls.profile_config,
        )
        
        # For testing purpose ensure source directory exists 
        Path(cls.monitor_path).mkdir(parents=True, exist_ok=True)

    def test_01_copy_file(self):
        """Test copy file and check path exists)"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "subfolder/test1.txt"
        
        # Create source file
        file_path = create_test_data(path=self.monitor_path, files=[file_name])
        # Copy file to remote to setup state for following tests
        (result_code, result_output) = self.s3_handler.copy_file(
            monitor_path=file_path.as_posix()
        )
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Check file exists
        remote_path =self.s3_handler.get_remote_path(monitor_path=file_path.as_posix())
        (result_code, result_output) = self.s3_handler.file_exists(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Check non-existent file
        remote_path_missing = Path(self.monitor_path) / "file-does-not-exists.txt"
        remote_path =self.s3_handler.get_remote_path(monitor_path=remote_path_missing.as_posix())
        (result_code, result_output) = self.s3_handler.file_exists(remote_path=remote_path)
        self.assertGreater(result_code, 0, f"File does not exists: {remote_path}. ResultCode: {result_output}")
        # Checking directory exists is pointless for Object Storage as is stored as file meta data

    def test_02_create_file_with_spaces(self):
        """Test copy file and check path exists)"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "file with spaces.txt"
        
        # Create source file
        file_path = create_test_data(path=self.monitor_path, files=[file_name])
        # Copy file to remote
        (result_code, result_output) = self.s3_handler.copy_file(
            monitor_path=file_path.as_posix()
        )
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Check file exists
        remote_path =self.s3_handler.get_remote_path(monitor_path=file_path.as_posix())
        (result_code, result_output) = self.s3_handler.file_exists(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        if result_code != 0:
            self.logger.error(f"Could not find file in remote: {remote_path}. ResultCode: {result_code}. Output: {result_output}")
            return
        
        if result_code != 0:
            self.logger.error(f"Could not find file in remote: {remote_path}. ResultCode: {result_code}. Output: {result_output}")
            return
        
        # Check if we can delete a file with spaces
        (result_code, result_output) = self.s3_handler.delete_file(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Check that file does not exist anymore
        (result_code, result_output) = self.s3_handler.file_exists(remote_path=remote_path)
        self.assertNotEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")


    def test_05_delete_file_at_remote(self):
        """Delete a file at remote"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "test2.txt"
        file_path = create_test_data(path=self.monitor_path, files=[file_name])

        # Copy first
        (result_code, result_output) = self.s3_handler.copy_file(monitor_path=file_path.as_posix())
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Delete file
        remote_path = self.s3_handler.get_remote_path(monitor_path=file_path.as_posix())
        (result_code, result_output) = self.s3_handler.delete_file(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

    def test_06_create_several_files(self):
        """Create several files"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        files = ["Subfolder1/test1.txt", "Subfolder1/test2.txt", "Subfolder1/test3.txt"]
        
        # Create files
        file_path = create_test_data(path=self.monitor_path, files=files)
        folder_path = file_path.parent # Subfolder1

        # Copy folder
        (result_code, result_output) = self.s3_handler.copy_folder(monitor_path=folder_path.as_posix())
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Check one file
        file_path = Path(folder_path / "test1.txt")
        remote_path = self.s3_handler.get_remote_path(monitor_path=file_path.as_posix())
        (result_code, result_output) = self.s3_handler.file_exists(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

    def test_07_remove_folder_from_remote(self):
        """Remove folder from remote"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        # Create files
        files = ["Subfolder2/test1.txt", "Subfolder2/test2.txt", "Subfolder2/test3.txt"]
        file_path = create_test_data(path=self.monitor_path, files=files)
        folder_path = file_path.parent

        # Copy folder
        (result_code, result_output) = self.s3_handler.copy_folder(monitor_path=folder_path.as_posix())
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Delete folder
        remote_path =self.s3_handler.get_remote_path(monitor_path=folder_path.as_posix())
        (result_code, result_output) = self.s3_handler.delete_folder(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")
 
    def test_08_file_with_space(self):
        """Testing file with space"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "Subfolder1/file with space.txt"
        file_path = create_test_data(path=self.monitor_path, files=[file_name])

        # Copy file
        (result_code, result_output) = self.s3_handler.copy_file(monitor_path=file_path.as_posix())
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Check file exists
        remote_path = self.s3_handler.get_remote_path(monitor_path=file_path.as_posix())
        result_code, result_output = self.s3_handler.file_exists(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

    def test_09_restore_folder(self):
        """Restore a remote folder back to the local source path."""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        folder_name = "RestoreFolder"
        files = [
            f"{folder_name}/restored1.txt",
            f"{folder_name}/nested/restored2.txt",
        ]

        # Create and upload local data.
        file_path = create_test_data(path=self.monitor_path, files=files)
        folder_path = file_path.parent.resolve()

        (result_code, result_output) = self.s3_handler.copy_folder(
            monitor_path=folder_path.as_posix()
        )
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Simulate data loss locally.
        import shutil
        shutil.rmtree(folder_path)

        # Restore from remote.
        remote_path = self.s3_handler.get_remote_path(monitor_path=folder_path.as_posix())
        (result_code, result_output) = self.s3_handler.restore_folder(
            remote_path=remote_path
        )
        self.assertEqual(result_code, 0, f"ResultCode: {result_code}. Output: {result_output}")

        # Verify each restored file exists locally. The restored prefix
        # (RestoreFolder) is stripped, so files land directly under monitor_path,
        # preserving their paths relative to the restored folder.
        restored_paths = [
            Path(self.monitor_path) / "restored1.txt",
            Path(self.monitor_path) / "nested" / "restored2.txt",
        ]
        for restored_path in restored_paths:
            self.assertTrue(
                restored_path.exists(),
                f"Expected restored file does not exist: {restored_path}",
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run integration tests for s3_handler using unittest."
    )
    parser.add_argument(
        "-d", "--db-dir",
        type=str,
        default="testdb/dev",
        metavar="<PATH>",
        help="Directory of SQlite database"
    )

    parser.add_argument(
        "-e",
        "--dotenv-path",
        type=str,
        default="testdata/.env",
        help="Path to the SQLite database file."
    )

    parser.add_argument(
        "--log-filename",
        type=str,
        default="test-s3-handler-integration.log",
        help="Log file name."
    )
    parser.add_argument(
        "--test-cases",
        type=str,
        nargs="+",
        help="Space-separated list of test method names (or substrings) to run."
    )
    args = parser.parse_args()

    # Setup logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Clean handlers
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # Console Handler
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Load Config
    log_configuration_file = "tests/conf/log.yaml"
    with open(log_configuration_file, "r") as file:
        log_config = yaml.safe_load(file)

    # Setup File Logging
    log_config = log_config.get("logging", {})
    LOG_FILE = log_config.get("log_file_name", args.log_filename)
    LOG_FOLDER = log_config.get("folder", "logs")
    MAX_BYTES = log_config.get("max_bytes", 10 * 1024 * 1024)
    BACKUP_COUNT = log_config.get("backup_count", 5)

    folder_path = Path(LOG_FOLDER)
    if not folder_path.exists():
        folder_path.mkdir(parents=True)

    file_handler = logging.handlers.RotatingFileHandler(
        (folder_path / LOG_FILE).as_posix(),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logger = logging.getLogger(__name__)
    logger.info("Starting Rclone Handler Integration Tests")

    # Setup test data in database
    database_test_data = DatabaseTestData(
        logger=logger,
        db_dir=args.db_dir,
        dotenv_path=args.dotenv_path
    )
    database_test_data.remove_test_data()
    database_test_data.load_test_data()

    # Run tests
    overall_success = True
    sqlite_handler = SQLiteHandler(
        logger=logger,
        db_dir=args.db_dir
    )

    monitor = {}
    profile = {}
    monitors = sqlite_handler.get_monitors()
    for monitor in monitors:
        # Get a monitor with an s3 profile
        profiles = sqlite_handler.get_profiles_for_monitor(monitor_id=monitor.get("id", 0))
        if not profiles:
            continue
        
        for profile in profiles:
            if profile.get("type", "").lower() == "s3":
                break
        else:
            continue

    if not monitor:
        logger.info("No monitors found with an s3 profile.")
        sys.exit(0)

    # Inject configuration into Test Class
    TestS3HandlerIntegration.monitor = monitor
    TestS3HandlerIntegration.profile_config = profile.get("config", {})
    TestS3HandlerIntegration.logger = logger
    
    logger.info(f"Running tests for monitor: {monitor.get('name')}")
    
    # Run Tests
    loader = unittest.TestLoader()
    full_suite = loader.loadTestsFromTestCase(TestS3HandlerIntegration)

    if args.test_cases:
        # Flatten arguments
        patterns = []
        for item in args.test_cases:
            patterns.extend(item.split())

        suite = unittest.TestSuite()
        for test in full_suite:
            if isinstance(test, unittest.TestCase):
                test_method_name = test._testMethodName
                if any(pattern in test_method_name for pattern in patterns):
                    suite.addTest(test)
        
        if suite.countTestCases() == 0:
                logger.warning(f"No tests matched patterns: {patterns}")
    else:
        suite = full_suite

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    
    if not result.wasSuccessful():
        overall_success = False
        logger.error(f"Tests failed for monitor: {monitor.get('name')}")

    logger.info("================================")    
    if overall_success:
        logger.info("All tests passed successfully.")    
    else:
        logger.info("Not all tests passed successfully.")
    logger.info("================================")    
