"""
Version: 2.3.0

Test integration script for rclone handler.
The script iterates over monitors
The same test suite is used for each monitor.
Ensure no monitor hub is currently running on any configured test monitor to avoid conflicts.
"""

import argparse
import logging
import logging.handlers
import sys
import unittest
from pathlib import Path

import yaml
from app.utils import reference_data
from app.monitor.rclone_handler import RcloneHandler
from app.utils.sqlite_handler import SQLiteHandler

from tests.database_test_data import DatabaseTestData
from tests.util.testing_util import create_test_data


class TestRcloneHandlerIntegration(unittest.TestCase):
    monitor = {}
    profile_name : str
    logger : logging.Logger
    
    @classmethod
    def setUpClass(cls):
        # Skip gracefully when run via `unittest discover` (make test-unit):
        # monitor/profile are only injected when this module is run directly.
        if not cls.monitor or not getattr(cls, "profile_name", ""):
            raise unittest.SkipTest(
                "Integration test: no monitor/profile injected. "
                "Run directly: python -m tests.test_rclone_handler_integration "
                "(or `make test-integration`)."
            )

        cls.monitor_name = cls.monitor.get("name")
        cls.logger.info(f"Setting up tests for monitor: {cls.monitor_name}")
        subfolder = "test-rclone-handler-integration"
        
        # Setup Monitor Path
        raw_source = cls.monitor.get("monitor_path", "")
        raw_source_stripped = raw_source.rstrip('/')
        cls.monitor_path = f"{raw_source_stripped}/{subfolder}"
        
        # Setup Remote Path
        # In v2 the remote_profile is not in the remote_path of RcloneHandler anymore
        # That allows us to have a single monitor propagated to one or more remote paths
        raw_dest = cls.monitor.get("remote_path", "")
        raw_dest_stripped = raw_dest.rstrip('/')
        cls.remote_path = f"{raw_dest_stripped}/{subfolder}"
        cls.rclone_handler = RcloneHandler(
            logger=cls.logger,
            base_monitor_path=cls.monitor_path,
            base_remote_path=cls.remote_path,
            profile_name=cls.profile_name,
        )
        
        # Ensure monitor directory exists
        Path(cls.monitor_path).mkdir(parents=True, exist_ok=True)

    def test_01_get_version(self):
        """Get Version"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        (result_code, result_output) = self.rclone_handler.get_rclone_version()
        self.assertIn("rclone", result_output.lower(), "Output should contain 'rclone'")

    def test_02_list_remotes(self):
        """List Remotes"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        (result_code, result_output) = self.rclone_handler.list_remotes()
        self.assertEqual(result_code, 0, f"List remotes failed. Output: {result_output}")

    def test_03_copy_file_to_remote_and_check_exist(self):
        """Testing file exists"""
        self.logger.debug(f"==> Monitor: {self.monitor_name} -> {self._testMethodName}")
        file_name = "Subfolder1/test1.txt"
        
        # Create test file
        file_path = create_test_data(path=self.monitor_path, files=[file_name])
        
        # Copy file to remote
        (result_code, result_output) = self.rclone_handler.copy_file(monitor_path=file_path.as_posix())
        self.assertEqual(result_code, 0, f"Copied file {file_name}. Output: {result_output}")

        # Check file exists
        remote_path = self.rclone_handler.get_remote_path(monitor_path=file_path.as_posix())
        (result_code, result_output) = self.rclone_handler.file_exists(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"File exist: {remote_path}")

        # Check non-existent file
        remote_path_missing = Path(self.monitor_path) / "file-does-not-exists.txt"
        remote_path = self.rclone_handler.get_remote_path(monitor_path=remote_path_missing.as_posix())
        (result_code, result_output) = self.rclone_handler.file_exists(remote_path=remote_path)
        self.assertNotEqual(result_code, 0, f"File should not exist: {remote_path_missing}")

    def test_04_delete_file_at_remote(self):
        """Delete a file at remote"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "test2.txt"
        file_path = create_test_data(path=self.monitor_path, files=[file_name])

        # Copy first
        (result_code, result_output) = self.rclone_handler.copy_file(monitor_path=file_path.as_posix())
        self.assertEqual(result_code, 0, "Setup failed: Copy file")

        # Delete
        remote_path = self.rclone_handler.get_remote_path(monitor_path=file_path.as_posix())
        (result_code, result_output) = self.rclone_handler.delete_file(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"Delete file failed. Output: {result_output}")

        # Check file has been deleted
        remote_path = self.rclone_handler.get_remote_path(monitor_path=file_path.as_posix())
        (result_code, result_output) = self.rclone_handler.file_exists(remote_path=remote_path)
        self.assertNotEqual(result_code, 0, f"File should have been deleted: {remote_path}")    

    def test_05_create_folder_with_files(self):
        """Create folder with files"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        files = ["Subfolder1/test1.txt", "Subfolder1/test2.txt", "Subfolder1/test3.txt"]
        
        # Create files
        file_path = create_test_data(path=self.monitor_path, files=files)
        head = file_path.parent # Subfolder1

        # Copy folder
        (result_code, result_output) = self.rclone_handler.copy_folder(monitor_path=head.as_posix())
        self.assertEqual(result_code, 0, f"Copied folder. Output: {result_output}")

        # Check one file
        remote_path = self.rclone_handler.get_remote_path(monitor_path=file_path.as_posix())
        found = self.rclone_handler.file_exists(remote_path=remote_path)
        self.assertTrue(found, f"File exist: {remote_path}")

    def test_06_remove_folder_from_remote(self):
        """Remove folder from remote"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        files = ["Subfolder2/test1.txt", "Subfolder2/test2.txt", "Subfolder2/test3.txt"]
        
        # Create test data first
        file_path = create_test_data(path=self.monitor_path, files=files)
        head = file_path.parent

        # Copy folder
        (result_code, result_output) = self.rclone_handler.copy_folder(monitor_path=head.as_posix())
        self.assertEqual(result_code, 0, "Rclone copy_folder succeeded")

        # Delete folder
        remote_path = self.rclone_handler.get_remote_path(head.as_posix())
        (result_code, result_output) = self.rclone_handler.delete_folder(remote_path=remote_path)
        self.assertEqual(result_code, 0, f"Rclone delete_folder failed for {remote_path}. Output: {result_output}")

    def test_07_file_with_space(self):
        """Testing file with space"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "Subfolder1/file with space.txt"
        file_path = create_test_data(path=self.monitor_path, files=[file_name])
        
        (result_code, result_output) = self.rclone_handler.copy_file(monitor_path=file_path.as_posix())
        self.assertEqual(result_code, 0, f"Copy file with space failed. Output: {result_output}")

    def test_08_folder_with_space(self):
        """Testing folder with space"""
        self.logger.debug(f"==> Monitor {self.monitor_name} -> {self._testMethodName}")
        file_name = "Subfolder with Space/test1.txt"
        file_path = create_test_data(path=self.monitor_path, files=[file_name])
        
        (result_code, result_output) = self.rclone_handler.copy_file(monitor_path=file_path.as_posix())
        self.assertEqual(result_code, 0, f"Copy file in folder with space failed. Output: {result_output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run integration tests for rclone_handler using unittest."
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
        help="Path to .env file with credentials."
    )
    parser.add_argument(
        "--log-filename",
        type=str,
        default="test_rclone_handler_integration.log",
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

    log_file = Path("./conf/log.yaml")
    with open(log_file.as_posix(), "r") as file:
        log_config = yaml.safe_load(file)

    # Setup File Logging
    LOG_FILE = log_config.get("file_name", args.log_filename)
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

    # Iterate over monitors and find one with profile_type implemented=false
    sqlite_handler = SQLiteHandler(
        logger=logger,
        db_dir=args.db_dir
    )

    found_rclone_profile = False
    monitor = {}
    profile = {}
    monitor_config = {}
    monitors = sqlite_handler.get_monitors()
    for monitor in monitors:
        # Get a monitor with an rclone profile
        if found_rclone_profile:
            break
        
        profiles = sqlite_handler.get_profiles_for_monitor(monitor_id=monitor.get("id", 0))
        if not profiles:
            continue
        
        for profile in profiles:
            profile_type = profile.get("profile_type", "")
            if not reference_data.is_profile_type_implemented(profile_type=profile_type):
                found_rclone_profile = True
                break

    if not found_rclone_profile:
        logger.info("No monitors found with an Rclone profile.")
        sys.exit(0)

    # Inject monitor configuration into Test Class
    TestRcloneHandlerIntegration.monitor = monitor
    TestRcloneHandlerIntegration.profile_name = profile.get("name", "")
    TestRcloneHandlerIntegration.logger = logger
    logger.info(f"Running tests for monitor: {monitor.get('name')}")
    loader = unittest.TestLoader()
    full_suite = loader.loadTestsFromTestCase(TestRcloneHandlerIntegration)

    # Run Tests
    overall_success = True
    if args.test_cases:
        # Flatten arguments
        patterns = []
        for item in args.test_cases:
            patterns.extend(item.split())

        suite = unittest.TestSuite()
        for test in full_suite:
            if isinstance(test, unittest.TestCase):
                if len(args.test_cases) == 1 and (args.test_cases[0] == "" or args.test_cases[0] == "*"):
                    suite.addTest(test)
                    continue
                
                testMethodName = test._testMethodName
                if any(pattern in testMethodName for pattern in patterns):
                    suite.addTest(test)
        
        if suite.countTestCases() == 0:
                logger.warning(f"No tests matched patterns: {patterns}")
    else:
        suite = full_suite

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    
    if not result.wasSuccessful():
        overall_success = False
        logger.error(f"Tests failed for monitor: {monitor_config.get('name')}")

    if overall_success:
        logger.info("All tests passed successfully.")    
    else:
        logger.info("Not all tests passed successfully.")

