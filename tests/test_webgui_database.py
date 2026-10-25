"""Unit tests for the shared web GUI database guard."""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.utils.sqlite_handler import SQLiteHandler
from app.webgui import database

logger = logging.getLogger("test.webgui.database")
logger.addHandler(logging.NullHandler())
logger.setLevel(logging.CRITICAL)


class TestDatabaseReady(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_dir = str(Path(self._temp_dir.name) / "db")
        Path(self.db_dir).mkdir()
        self.handler = SQLiteHandler(logger=logger, db_dir=self.db_dir)

    def tearDown(self) -> None:
        self.handler.close()
        self._temp_dir.cleanup()

    def test_initialised_database_passes_and_renders_nothing(self):
        self.handler.create_schema()
        with mock.patch.object(database, "st") as st:
            self.assertTrue(database.database_ready(self.handler))
        st.error.assert_not_called()

    def test_uninitialised_database_is_reported_with_the_directory(self):
        with mock.patch.object(database, "st") as st:
            self.assertFalse(database.database_ready(self.handler))
        message = st.error.call_args.args[0]
        self.assertIn(self.db_dir, message)
        self.assertIn("database init", message)

    def test_missing_database_directory_is_reported(self):
        # A directory that does not exist yet: is_initialized() must not raise,
        # and the guard must still render the actionable message.
        missing = str(Path(self._temp_dir.name) / "does-not-exist")
        handler = SQLiteHandler(logger=logger, db_dir=missing)
        with mock.patch.object(database, "st") as st:
            self.assertFalse(database.database_ready(handler))
        self.assertIn(missing, st.error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
