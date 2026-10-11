import logging
import tempfile
import unittest
from pathlib import Path


class BaseTestClass(unittest.TestCase):
    logger: logging.Logger
    db_dir: str
    dotenv_path: str
    temp_dir: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls):
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

        cls.logger = logging.getLogger(__name__)

        # Create a temporary directory for the database
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_dir = cls.temp_dir.name
        cls.dotenv_path = str(Path(cls.temp_dir.name) / ".env")

    @classmethod
    def tearDownClass(cls):
        # Clean up the temporary directory
        cls.temp_dir.cleanup()
