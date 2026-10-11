"""Unit tests for the DatabaseTestData helper.

``DatabaseTestData`` is test scaffolding rather than production code, but its
cleanup guard (``remove_test_data``) is worth pinning: it previously probed
``sqlite_handler.connection is None``, which could never be true, so a closed
handler was not detected. It now uses the explicit ``SQLiteHandler.is_closed()``
state accessor.
"""

import logging
import tempfile
import unittest

from tests.database_test_data import DatabaseTestData


class TestDatabaseTestDataCleanup(unittest.TestCase):
    logger = logging.getLogger(__name__)

    def test_remove_test_data_skips_when_connection_is_closed(self):
        """A closed handler makes cleanup log a warning and return quietly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            helper = DatabaseTestData(
                logger=self.logger, db_dir=tmp_dir, dotenv_path=None
            )
            try:
                helper.sqlite_handler.close()
                self.assertTrue(helper.sqlite_handler.is_closed())

                with self.assertLogs(self.logger, level="WARNING") as captured:
                    helper.remove_test_data()  # must not raise

                self.assertTrue(
                    any("already closed" in line for line in captured.output)
                )
            finally:
                helper.sqlite_handler.close()


if __name__ == "__main__":
    unittest.main()
