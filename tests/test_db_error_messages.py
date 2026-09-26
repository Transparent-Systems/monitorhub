"""Unit tests for the CLI's mapping of database constraint errors."""

import logging
import sqlite3
import tempfile
import unittest

from app.cli.db_error_messages import integrity_error_message
from app.utils.sqlite_handler import SQLiteHandler


class TestIntegrityErrorMessages(unittest.TestCase):
    def test_duplicate_monitor_name_with_context(self):
        """A caller that knows the name gets a specific, user-facing message."""
        error = self._unique_monitor_name_error()

        self.assertEqual(
            integrity_error_message(error, entity="Monitor", name="Daily backup"),
            "Monitor name: Daily backup already exists",
        )

    def test_duplicate_monitor_name_without_context(self):
        """Without the name, the constraint field identifies the entity."""
        error = self._unique_monitor_name_error()

        self.assertEqual(
            integrity_error_message(error),
            "A monitor with that name already exists.",
        )

    def test_duplicate_profile_name_without_context(self):
        """A UNIQUE violation on profiles.name maps to a profile-specific message."""
        error = self._unique_profile_name_error()

        self.assertEqual(
            integrity_error_message(error),
            "A profile with that name already exists.",
        )

    def test_duplicate_profile_map(self):
        error = sqlite3.IntegrityError(
            "UNIQUE constraint failed: monitor_profile_map.monitor_id, "
            "monitor_profile_map.profile_id"
        )

        self.assertEqual(
            integrity_error_message(error),
            "That profile is already linked to this monitor.",
        )

    def test_unknown_unique_field_falls_back(self):
        error = sqlite3.IntegrityError("UNIQUE constraint failed: widgets.code")

        self.assertEqual(
            integrity_error_message(error),
            "A record with that widgets.code already exists.",
        )

    def test_foreign_key_violation(self):
        error = sqlite3.IntegrityError("FOREIGN KEY constraint failed")

        self.assertIn("does not exist", integrity_error_message(error))

    def test_not_null_violation(self):
        error = sqlite3.IntegrityError("NOT NULL constraint failed: monitors.name")

        self.assertEqual(
            integrity_error_message(error),
            "A required value is missing (monitors.name).",
        )

    def test_other_integrity_error_is_reported_verbatim(self):
        error = sqlite3.IntegrityError("CHECK constraint failed: something")

        self.assertEqual(
            integrity_error_message(error),
            "Database constraint error: CHECK constraint failed: something",
        )

    def _unique_monitor_name_error(self) -> sqlite3.IntegrityError:
        """
        Produce a real duplicate-name error from the handler.

        Using the real database error (rather than a hand-written string) means
        a change in SQLite's message wording fails this test instead of silently
        degrading the user-facing messages.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=logging.getLogger(__name__), db_dir=tmp_dir)
            try:
                handler.create_schema()
                handler.add_monitor(
                    name="Daily backup",
                    monitor_path="/tmp/backup",
                    remote_path="/backup",
                    monitor_type="instant",
                    config={},
                    status="stopped",
                )
                try:
                    handler.add_monitor(
                        name="Daily backup",
                        monitor_path="/tmp/backup-2",
                        remote_path="/backup-2",
                        monitor_type="instant",
                        config={},
                        status="stopped",
                    )
                except sqlite3.IntegrityError as error:
                    return error
                self.fail("Expected a UNIQUE constraint violation on monitors.name")
            finally:
                handler.close()

    def _unique_profile_name_error(self) -> sqlite3.IntegrityError:
        """Produce a real duplicate-profile-name error from the handler."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=logging.getLogger(__name__), db_dir=tmp_dir)
            try:
                handler.create_schema()
                handler.add_profile(name="Daily sync", profile_type="s3", config={})
                try:
                    handler.add_profile(name="Daily sync", profile_type="s3", config={})
                except sqlite3.IntegrityError as error:
                    return error
                self.fail("Expected a UNIQUE constraint violation on profiles.name")
            finally:
                handler.close()


    def test_stale_profile_id_raises_foreign_key_error(self):
        """A mapping whose profile was deleted raises, and maps to a clear message."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=logging.getLogger(__name__), db_dir=tmp_dir)
            try:
                handler.create_schema()
                monitor_id = handler.add_monitor(
                    name="FK test monitor",
                    monitor_path="/tmp/fk",
                    remote_path="/fk",
                    monitor_type="instant",
                    config={},
                    status="stopped",
                )
                profile_id = handler.add_profile(
                    name="FK test profile", profile_type="s3", config={}
                )
                handler.delete_profile(profile_id=profile_id)

                # INSERT OR IGNORE does not suppress a FOREIGN KEY violation.
                with self.assertRaises(sqlite3.IntegrityError) as raised:
                    handler.add_monitor_profile_map(monitor_id, profile_id)

                self.assertEqual(
                    integrity_error_message(raised.exception),
                    "The referenced record does not exist (it may have been deleted).",
                )
            finally:
                handler.close()


if __name__ == "__main__":
    unittest.main()
