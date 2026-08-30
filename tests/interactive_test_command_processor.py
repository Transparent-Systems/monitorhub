import argparse
import logging
import tempfile
import unittest

from scripts.command_processor import CommandProcessor
from tests.base_test_class import BaseTestClass
from tests.database_test_data import DatabaseTestData


class TestCommandProcessor(BaseTestClass):
    """
    Test CommandProcessor
    The main purpose of TestCommandProcessor is to test the CommandProcessor class.
    This avoids havng to manually run monitor hub with the corresponding command.
    Additionaly, this class uses the test SQLite datbase in folder testdb/dev
    You can run individual tests using paramater test_cases which is a space delimited string of test methods.
    Only part of the test method name is used for matching.
    For example: python3 tests/interactive_test_command_processor.py -tests_cases "_01 _02"
    """

    command_processor: CommandProcessor
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass() # Call the setUpClass of the base class
        cls.logger.info("Start testing CommandProcessor")
        cls.command_processor = CommandProcessor(
            logger=cls.logger,
            db_dir=cls.db_dir
        )
        cls.database_test_data = DatabaseTestData(
            logger=cls.logger,
            db_dir=cls.db_dir,
            dotenv_path=cls.dotenv_path
        )
        cls.database_test_data.remove_test_data()
        cls.database_test_data.load_test_data()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass() # Call the tearDownClass of the base class
        # Perform any necessary cleanup after all tests have run
        cls.logger.info("TearDown finished")

    def test_01_1_profile_new_command(self):
        self.command_processor.profile_new_command()

    def test_01_2_profile_new_command(self):
        self.command_processor.profile_new_remote()

    def test_02_profile_edit(self):
        self.command_processor.profile_edit()
        
    def test_03_profile_test(self):
        self.command_processor.profile_test()

    def test_04_profile_test(self):
        # Get first profile and use profile id in call to profile_test()
        profiles = self.command_processor.sqlite_handler.get_profiles()
        if not profiles:
            self.skipTest("No profiles found in database")
        first_profile_id = profiles[0]["id"]
        self.command_processor.profile_test(profile_id=first_profile_id)

    def test_05_profile_delete(self):
        self.command_processor.profile_delete()

    def test_10_monitor_new(self):
        self.command_processor.monitor_new()

    def test_11_monitor_edit(self):
        self.command_processor.monitor_edit()

    def test_12_monitor_show(self):
        self.command_processor.monitor_show()

    def test_13_monitor_delete(self):
        self.command_processor.monitor_delete()

    def test_14_monitor_test(self):
        self.command_processor.monitor_test()

    def test_90_database_sample_data_idempotent(self):
        """database_sample_data() seeds once and is idempotent on repeat."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cp = CommandProcessor(logger=self.logger, db_dir=tmp_dir)
            try:
                cp.database_sample_data()
                profiles = cp.sqlite_handler.get_profiles()
                monitors = cp.sqlite_handler.get_monitors()

                self.assertEqual(len(profiles), 1)
                self.assertEqual(profiles[0]["name"], "Example S3 profile")
                self.assertEqual(len(monitors), 1)
                self.assertEqual(monitors[0]["name"], "Example monitor")

                # Running again must not create duplicates
                cp.database_sample_data()
                self.assertEqual(len(cp.sqlite_handler.get_profiles()), 1)
                self.assertEqual(len(cp.sqlite_handler.get_monitors()), 1)

                # The example monitor and profile must be mapped together
                mapping = cp.sqlite_handler.get_profiles_for_monitor(monitors[0]["id"])
                self.assertEqual(len(mapping), 1)
            finally:
                cp.sqlite_handler.close()

    
    # def test_15_monitor_start(self):
    #     self.command_processor.monitor_start()

    # def test_16_monitor_stop(self):
    #     self.command_processor.monitor_stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run integration tests for command_processor using unittest."
    )
    parser.add_argument(
        "-d",
        "--db-dir",
        type=str,
        default="testdb/dev",
        help="Path to database file."
    )
    parser.add_argument(
        "-e",
        "--dotenv-path",
        type=str,
        default="testdata/.env",
        help="Path to .env file."
    )
    parser.add_argument(
        "-t",
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

    logger = logging.getLogger(__name__)
    logger.info("Starting command processor tests")

    # The setup is now handled by the BaseTestClass and TestCommandProcessor's setUpClass.
    # We still need to instantiate a logger for the __main__ block's local use.
    logger = logging.getLogger(__name__)
    logger.info("Starting command processor tests")

    # In case of direct execution with arguments, we need to update the TestCommandProcessor's
    # class variables *after* setUpClass has been called by unittest, so that
    # the args override the tempfile created paths.
    # This also needs to be done before running the TestLoader
    TestCommandProcessor.db_dir = args.db_dir
    TestCommandProcessor.dotenv_path = args.dotenv_path

    # We also need to setup the logger for the TestCommandProcessor class directly,
    # as the unittest runner will not call setUpClass until the tests are loaded.
    TestCommandProcessor.logger = logger

    # Populate database with test data for direct run, ensuring it uses the specified db_dir.
    database_test_data = DatabaseTestData(
        logger=logger,
        db_dir=args.db_dir,
        dotenv_path=args.dotenv_path
    )
    database_test_data.remove_test_data()
    database_test_data.load_test_data()

    # Run Tests
    test_loader = unittest.TestLoader()
    full_suite = test_loader.loadTestsFromTestCase(TestCommandProcessor)

    if args.test_cases:
        # Flatten arguments
        patterns = []
        for item in args.test_cases:
            patterns.extend(item.split())

        suite = unittest.TestSuite()
        for test in full_suite:
            if isinstance(test, unittest.TestCase):
                test_method_name = test._testMethodName
                if args.test_cases == [""] or any(pattern in test_method_name for pattern in patterns):
                    suite.addTest(test)
        
        if suite.countTestCases() == 0:
                logger.warning(f"No tests matched patterns: {patterns}")
    else:
        suite = full_suite

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    logger.info("================================")    
    
    if result.wasSuccessful():
        logger.info("All tests passed successfully.")    
    else:
        logger.info("Not all tests passed successfully.")
    logger.info("================================")    
