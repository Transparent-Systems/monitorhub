"""
Call this script using the "-m" flag from the root folder.
This avoids sys.path manipulation
Call example:
python3 -m tests.test_sqlite_handler
"""
import argparse
import gc
import logging
import sqlite3
import tempfile
import unittest

from app.utils.schema_versioning import DATABASE_SCHEMA_VERSION, SCHEMA_MIGRATIONS
from app.utils.sqlite_handler import SQLiteHandler
from tests.base_test_class import BaseTestClass


class TestSqliteHandler(BaseTestClass):
    profile_id: int = 0
    profile_name: str = ""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.logger.info(f"Using database dir: {cls.db_dir}")
        cls.sqlite_handler = SQLiteHandler(
            logger=cls.logger,
            db_dir=cls.db_dir)
        cls.sqlite_handler.create_schema()

    @classmethod
    def tearDownClass(cls):
        cls.sqlite_handler.close()
        super().tearDownClass()


    def test_00_is_initialized_false_on_new_db(self):
        """A brand new database should not be considered initialised."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                self.assertFalse(
                    handler.is_initialized(),
                    "New database should not report as initialised",
                )
            finally:
                handler.close()

    def test_01_create_scheme(self):
        self.sqlite_handler.create_schema()
        self.logger.info("Schema created successfully.")

    def test_01_01_is_initialized_true_after_create_schema(self):
        """Calling create_schema should mark the database as initialised."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                handler.create_schema()
                self.assertTrue(
                    handler.is_initialized(),
                    "Database should report as initialised after create_schema",
                )
            finally:
                handler.close()

    def test_01_02_drop_schema_then_not_initialized(self):
        """drop_schema should remove the schema so is_initialized is False."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                handler.create_schema()
                handler.drop_schema()
                self.assertFalse(
                    handler.is_initialized(),
                    "Database should not report as initialised after drop_schema",
                )
            finally:
                handler.close()

    def test_01_03_schema_version_recorded_with_description(self):
        """create_schema should record every schema version with a description."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                handler.create_schema()

                versions = handler.get_schema_versions()
                # create_schema applies (and records) the whole migration
                # registry, so the history holds one row per migration.
                self.assertEqual(len(versions), len(SCHEMA_MIGRATIONS))
                self.assertEqual(versions[0]["version"], "1.0.0")
                self.assertEqual(versions[0]["description"], "Initial schema")

                self.assertEqual(
                    handler.get_current_schema_version(), DATABASE_SCHEMA_VERSION
                )

                # Applying migrations again must be a no-op.
                self.assertEqual(handler.apply_pending_migrations(), [])
            finally:
                handler.close()

    def test_01_04_get_current_schema_version_is_numeric(self):
        """The highest version must be chosen numerically, not lexicographically."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                handler.create_schema()
                handler.update_schema_version("9.0.0")
                handler.update_schema_version("10.0.0")

                # Lexicographically "9.0.0" > "10.0.0", but numerically 10 > 9.
                self.assertEqual(handler.get_current_schema_version(), "10.0.0")
            finally:
                handler.close()

    def test_02_update_schema_version(self):
        self.sqlite_handler.update_schema_version(version="2.0.0")
        self.logger.info("Scheme version updated successfully.")

    def test_03_get_current_schema_version(self):
        current_version = self.sqlite_handler.get_current_schema_version()
        self.logger.info(f"Current scheme version: {current_version}")

    def test_03_01_get_schema_versions(self):
        schema_versions = self.sqlite_handler.get_schema_versions()
        for schema_version in schema_versions:
            self.logger.info(f"Schema version: {schema_version}")

    def test_04_add_monitor(self):
        monitor_id = self.sqlite_handler.add_monitor(
            name="test_monitor",
            monitor_path="/tmp/test",
            remote_path="/remote/test",
            monitor_type="periodic_upload",
            config={
                "monitor_period": "10m",
                "test": "value"},
            status="active"
        )

        if monitor_id is None:
            self.fail("add_monitor returned None")

        TestSqliteHandler.profile_id = monitor_id
        self.logger.info(f"Monitor added with ID: {monitor_id}")

    def test_05_get_monitor(self):
        monitor_id = TestSqliteHandler.profile_id
        monitor = self.sqlite_handler.get_monitor(monitor_id)
        self.logger.info(f"Monitor retrieved: {monitor}")

        # Now check the config is correctly deserialized
        config = monitor.get("config", {})
        self.assertIsInstance(config, dict, "config should be a dictionary")
        self.assertEqual(config.get("monitor_period"), "10m", "config monitor_period value mismatch")
        self.assertEqual(config.get("test"), "value", "config test value mismatch")

    def test_06_update_monitor_status(self):
        monitor_id = TestSqliteHandler.profile_id
        status = "stopped"
        self.sqlite_handler.update_monitor_status(monitor_id, status)
        self.logger.info(f"Monitor status updated to: {status}")
    
    def test_07_update_monitor_last_run(self):
        monitor_id = TestSqliteHandler.profile_id
        last_run = "2023-01-01 00:00:00"
        self.sqlite_handler.update_monitor_last_run(monitor_id, last_run)
        self.logger.info(f"Monitor last run updated to: {last_run}")

    def test_08_update_monitor_last_heartbeat(self):
        monitor_id = TestSqliteHandler.profile_id
        last_heartbeat = "2023-01-01 00:00:00"
        self.sqlite_handler.update_monitor_last_heartbeat(monitor_id, last_heartbeat)
        self.logger.info(f"Monitor last heartbeat updated to: {last_heartbeat}")

    def test_09_update_monitor_config(self):
        monitor_id = TestSqliteHandler.profile_id
        config = {"new_config": "value"}
        self.sqlite_handler.update_monitor_config(monitor_id, config)
        self.logger.info(f"Monitor config updated to: {config}")


    def test_10_get_all_monitors(self):
        monitors = self.sqlite_handler.get_monitors()
        self.logger.info(f"All monitors retrieved: {monitors}")

    def test_11_delete_monitor(self):
        monitor_id = TestSqliteHandler.profile_id
        self.sqlite_handler.delete_monitor(monitor_id)
        self.logger.info(f"Monitor deleted with ID: {monitor_id}")

    def test_20_add_profile(self):
        profile_id = self.sqlite_handler.add_profile(
            name="test_profile",
            profile_type="aws",
            config={
                "access_key_id": "AKIA...",
                "access_key_secret": "SECRET...",
                "default_region": "us-east-1",
                "end_point": "my-endpoint"
            }
        )
        self.logger.info(f"Profile added with ID: {profile_id}")
        # Now add a second profile with a complex nested config to test JSON handling
        # For example Google Drive has a token that is a JSON object with nested fields
        complex_config = {
            "handler": "monitorhub",
            "token": {
                "access_token": "fake-access-token",
                "token_type": "Bearer",
                "refresh_token": "fake-refresh-token",
                "expiry": "2026-03-03T10:36:59.063709164+13:00"
            },
            "team_drive": {
                "id": "0Axxxxxx",
                "name": "My Team Drive"
            }
        }
        complex_profile_id = self.sqlite_handler.add_profile(
            name="complex_profile",
            profile_type="drive",
            config=complex_config
        )
        TestSqliteHandler.profile_id = complex_profile_id if complex_profile_id is not None else 0
        TestSqliteHandler.profile_name = "test_profile"
        self.logger.info(f"Complex profile added with ID: {complex_profile_id}")

    def test_21_get_profile_by_id(self):
        profile_id = TestSqliteHandler.profile_id
        profile = self.sqlite_handler.get_profile(profile_id=profile_id)
        self.logger.info(f"Profile retrieved: {profile}")

        # Now check the config is correctly deserialized
        config = profile.get("config", {})
        self.assertIsInstance(config, dict, "config should be a dictionary")
        self.assertEqual(config.get("handler"), "monitorhub", "config handler value mismatch")
        token = config.get("token", {})
        self.assertIsInstance(token, dict, "config token should be a dictionary")
        expected_access_token = "fake-access-token"
        access_token = token.get("access_token")
        self.assertEqual(access_token, expected_access_token, "config access_token value mismatch")

    def test_21_get_profile_by_name(self):
        profile_name = TestSqliteHandler.profile_name
        profile = self.sqlite_handler.get_profile(profile_name=profile_name)
        self.logger.info(f"Profile retrieved: {profile}")

        # Now check the config is correctly deserialized
        config = profile.get("config", {})
        self.assertIsInstance(config, dict, "config should be a dictionary")
            
    def test_22_update_profile(self):
        profile_id = TestSqliteHandler.profile_id
        self.sqlite_handler.update_profile(
            profile_id=profile_id,
            name="updated_profile",
            profile_type="aws",
            config={
                "access_key_id": "AKIA_UPDATED...",
                "access_key_secret": "SECRET_UPDATED...",
                "default_region": "us-west-2",
                "end_point": "my-endpoint"
                }
        
        )
        self.logger.info(f"Profile updated with ID: {profile_id}")

    def test_23_get_all_profiles(self):
        profiles = self.sqlite_handler.get_profiles()
        self.logger.info(f"All profiles retrieved: {profiles}")

    def test_24_delete_profile(self):
        profile_id = TestSqliteHandler.profile_id
        self.sqlite_handler.delete_profile(profile_id)
        self.logger.info(f"Profile deleted with ID: {profile_id}")

    def test_30_get_nonexistent_monitor(self):
        monitor_id = 9999
        monitor = self.sqlite_handler.get_monitor(monitor_id)
        self.logger.info(f"Non-existent monitor retrieved: {monitor}")
        self.assertIsNone(monitor, "Expected None for non-existent monitor")

    def test_31_get_nonexistent_profile_id(self):
        profile_id = 9999
        profile = self.sqlite_handler.get_profile(profile_id)
        self.logger.info(f"Non-existent profile retrieved: {profile}")
        self.assertIsNone(profile, "Expected None for non-existent profile")

    def test_32_update_nonexistent_monitor(self):
        monitor_id = 9999
        status = "stopped"
        updated = self.sqlite_handler.update_monitor_status(monitor_id, status)
        self.logger.info(f"Attempted to update non-existent monitor with ID: {monitor_id}")
        self.assertFalse(updated, "Expected False for a non-existent monitor")

    def test_33_delete_nonexistent_monitor(self):
        monitor_id = 9999
        deleted = self.sqlite_handler.delete_monitor(monitor_id)
        self.logger.info(f"Attempted to delete non-existent monitor with ID: {monitor_id}")
        self.assertFalse(deleted, "Expected False for a non-existent monitor")
    
    def test_34_delete_nonexistent_profile(self):
        profile_id = 9999
        deleted = self.sqlite_handler.delete_profile(profile_id)
        self.logger.info(f"Attempted to delete non-existent profile with ID: {profile_id}")
        self.assertFalse(deleted, "Expected False for a non-existent profile")

    def test_40_map_monitor_to_profile(self):
        # Create monitor and profile first
        monitor_id = self.sqlite_handler.add_monitor(
            name="test_monitor",
            monitor_path="/tmp/test",
            remote_path="/remote/test",
            monitor_type="instant",
            config={"test": "value"},
            status="active"
        )
        self.logger.info(f"Monitor added with ID: {monitor_id}")

        profile_id = self.sqlite_handler.add_profile(
            name="map_monitor_profile",
            profile_type="aws",
            config={
                "access_key_id": "AKIA_UPDATED...",
                "access_key_secret": "SECRET_UPDATED...",
                "default_region": "us-west-2",
                "end_point": "my-endpoint"
                }
        )
        self.logger.info(f"Profile added with ID: {profile_id}")

        if monitor_id is None or profile_id is None:
            self.fail("add_monitor or add_profile returned None")

        self.sqlite_handler.add_monitor_profile_map(monitor_id, profile_id)
        self.logger.info(f"Mapped monitor ID {monitor_id} to profile ID {profile_id}")

    def test_41_get_profiles_for_monitor(self):
        # Get all monitors, select the first one, and get its profiles
        monitors = self.sqlite_handler.get_monitors()
        if not monitors:
            self.fail("No monitors found")
        monitor_id = monitors[0]["id"]
        profiles = self.sqlite_handler.get_profiles_for_monitor(monitor_id)
        self.logger.info(f"Profiles mapped to monitor ID {monitor_id}: {profiles}")

    def test_42_get_monitors_for_profile(self):
        # Get all profiles, select the first one, and get its monitors
        profiles = self.sqlite_handler.get_profiles()
        if not profiles:
            self.fail("No profiles found")
        profile_id = profiles[0]["id"]
        monitors = self.sqlite_handler.get_monitors_for_profile(profile_id)
        self.logger.info(f"Monitors mapped to profile ID {profile_id}: {monitors}")
            
    def test_43_unmap_monitor_from_profile(self):
        monitor_id = TestSqliteHandler.profile_id
        profile_id = 1
        self.sqlite_handler.delete_monitor_profile_map(monitor_id, profile_id)
        self.logger.info(f"Unmapped monitor ID {monitor_id} from profile ID {profile_id}")

    def test_50_cleanup(self):
        # First delete all monitor-profile mappings
        self.sqlite_handler.cursor.execute("DELETE FROM monitor_profile_map")
        self.sqlite_handler.connection.commit()

        monitors = self.sqlite_handler.get_monitors()
        for monitor in monitors:
            self.sqlite_handler.delete_monitor(monitor["id"])
            self.logger.info(f"Deleted monitor with ID: {monitor['id']}")

        profiles = self.sqlite_handler.get_profiles()
        for profile in profiles:
            self.sqlite_handler.delete_profile(profile["id"])
            self.logger.info(f"Deleted profile with ID: {profile['id']}")


    def test_60_get_monitor_missing_arguments_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.sqlite_handler.get_monitor()

    def test_61_get_profile_missing_arguments_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.sqlite_handler.get_profile()

    def test_62_delete_profile_missing_arguments_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.sqlite_handler.delete_profile()


class TestSqliteHandlerErrorConvention(BaseTestClass):
    """
    Expected absence returns None/False; unexpected database errors are raised.

    The handler distinguishes "nothing matched" (an expected outcome) from
    "the database is broken" (an unexpected sqlite3.Error, which is logged and
    re-raised so the caller can decide how to report it).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sqlite_handler = SQLiteHandler(logger=cls.logger, db_dir=cls.db_dir)
        cls.sqlite_handler.create_schema()

    @classmethod
    def tearDownClass(cls):
        cls.sqlite_handler.close()
        super().tearDownClass()

    def test_missing_monitor_and_profile_return_none(self):
        self.assertIsNone(self.sqlite_handler.get_monitor(monitor_id=9999))
        self.assertIsNone(self.sqlite_handler.get_monitor(monitor_name="missing"))
        self.assertIsNone(self.sqlite_handler.get_profile(profile_id=9999))
        self.assertIsNone(self.sqlite_handler.get_profile(profile_name="missing"))

    def test_update_missing_monitor_and_profile_return_none(self):
        self.assertIsNone(
            self.sqlite_handler.update_monitor(
                monitor_id=9999,
                name="missing",
                monitor_path="/tmp/missing",
                remote_path="/missing",
                monitor_type="instant",
                config={},
                status="stopped",
            )
        )
        self.assertIsNone(
            self.sqlite_handler.update_profile(
                profile_id=9999,
                name="missing",
                profile_type="s3",
                config={},
            )
        )

    def test_mutations_that_match_no_row_return_false(self):
        self.assertFalse(self.sqlite_handler.update_monitor_status(9999, "stopped"))
        self.assertFalse(self.sqlite_handler.update_monitor_pid(9999, 0))
        self.assertFalse(self.sqlite_handler.update_monitor_last_run(9999, "2026-01-01"))
        self.assertFalse(
            self.sqlite_handler.update_monitor_last_heartbeat(9999, "2026-01-01")
        )
        self.assertFalse(self.sqlite_handler.update_monitor_config(9999, {}))
        self.assertFalse(self.sqlite_handler.delete_monitor(9999))
        self.assertFalse(self.sqlite_handler.delete_profile(profile_id=9999))
        self.assertFalse(self.sqlite_handler.delete_monitor_profile_map(9999, 9999))

    def test_duplicate_monitor_profile_map_returns_false(self):
        monitor_id = self.sqlite_handler.add_monitor(
            name="map_test_monitor",
            monitor_path="/tmp/map_test",
            remote_path="/map_test",
            monitor_type="instant",
            config={},
            status="stopped",
        )
        profile_id = self.sqlite_handler.add_profile(
            name="map_test_profile", profile_type="s3", config={}
        )
        try:
            self.assertTrue(
                self.sqlite_handler.add_monitor_profile_map(monitor_id, profile_id)
            )
            # Already mapped / already removed: expected no-ops, not errors.
            self.assertFalse(
                self.sqlite_handler.add_monitor_profile_map(monitor_id, profile_id)
            )
            self.assertTrue(
                self.sqlite_handler.delete_monitor_profile_map(monitor_id, profile_id)
            )
            self.assertFalse(
                self.sqlite_handler.delete_monitor_profile_map(monitor_id, profile_id)
            )
        finally:
            self.sqlite_handler.delete_monitor(monitor_id)
            self.sqlite_handler.delete_profile(profile_id)

    def test_unexpected_database_error_is_raised(self):
        """An uninitialised database raises instead of being swallowed as False."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                statements = {
                    "update_monitor_status": lambda: handler.update_monitor_status(1, "stopped"),
                    "update_monitor_pid": lambda: handler.update_monitor_pid(1, 0),
                    "update_monitor_last_run": lambda: handler.update_monitor_last_run(1, "x"),
                    "update_monitor_last_heartbeat": lambda: handler.update_monitor_last_heartbeat(1, "x"),
                    "update_monitor_config": lambda: handler.update_monitor_config(1, {}),
                    "delete_monitor": lambda: handler.delete_monitor(1),
                    "delete_profile": lambda: handler.delete_profile(profile_id=1),
                    "add_monitor_profile_map": lambda: handler.add_monitor_profile_map(1, 1),
                    "delete_monitor_profile_map": lambda: handler.delete_monitor_profile_map(1, 1),
                }
                for name, statement in statements.items():
                    with self.subTest(statement=name), self.assertRaises(sqlite3.Error):
                        statement()
            finally:
                handler.close()

    def test_schema_readers_raise_when_the_schema_is_missing(self):
        """The schema readers do not probe for the table; a missing table raises."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                with self.assertRaises(sqlite3.Error):
                    handler.get_current_schema_version()
                with self.assertRaises(sqlite3.Error):
                    handler.get_schema_versions()
            finally:
                handler.close()

    def test_schema_readers_tolerate_an_empty_version_table(self):
        """An existing but empty schema_version table still yields "" and []."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                handler.create_schema()
                with handler.transaction() as cur:
                    cur.execute("DELETE FROM schema_version")

                self.assertEqual(handler.get_current_schema_version(), "")
                self.assertEqual(handler.get_schema_versions(), [])
            finally:
                handler.close()

    def test_readers_log_before_raising_on_a_missing_table(self):
        """Every reader logs the failing query and then re-raises."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                readers = {
                    "get_monitor": lambda: handler.get_monitor(monitor_id=1),
                    "get_monitors": handler.get_monitors,
                    "get_profile": lambda: handler.get_profile(profile_id=1),
                    "get_profiles": handler.get_profiles,
                    "get_profiles_for_monitor": lambda: handler.get_profiles_for_monitor(1),
                    "get_monitors_for_profile": lambda: handler.get_monitors_for_profile(1),
                    "get_current_schema_version": handler.get_current_schema_version,
                    "get_schema_versions": handler.get_schema_versions,
                }
                for name, reader in readers.items():
                    with self.subTest(reader=name):
                        with (
                            self.assertLogs(self.logger, level="ERROR") as captured,
                            self.assertRaises(sqlite3.Error),
                        ):
                            reader()
                        self.assertTrue(
                            captured.output,
                            f"{name} raised without logging",
                        )
            finally:
                handler.close()


class TestSqliteHandlerLifecycle(BaseTestClass):
    """Deterministic connection lifecycle: explicit close plus a GC safety net.

    Covers the behaviour that used to rely on ``__del__``: the connection must
    be released exactly once, whether the caller closes it explicitly, the
    handler is garbage-collected, or ``__init__`` never completed.
    """

    def test_close_is_idempotent_and_invalidates_the_connection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            handler.close()
            handler.close()  # second call must be a harmless no-op
            with self.assertRaises(sqlite3.ProgrammingError):
                handler.cursor.execute("SELECT 1")

    def test_connection_released_when_handler_garbage_collected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            connection = handler.connection
            del handler
            gc.collect()
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_close_safe_when_init_never_finished(self):
        """A partially-constructed handler (no __init__) must close quietly."""
        handler = object.__new__(SQLiteHandler)
        handler.close()

    def test_context_manager_closes_the_handler(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            with handler:
                self.assertIsNotNone(handler.cursor)
            with self.assertRaises(sqlite3.ProgrammingError):
                handler.cursor.execute("SELECT 1")

    def test_construction_is_lazy_and_creates_no_database_file(self):
        """Building a handler must not touch the filesystem.

        ``mhub version`` and ``mhub database info`` wire a handler without
        using the database; they must not silently create ``monitorhub.db``
        before ``database init`` has run.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                self.assertFalse(handler.db_path.exists())
                # is_initialized() on a missing file reports False without
                # opening (and therefore creating) it.
                self.assertFalse(handler.is_initialized())
                self.assertFalse(handler.db_path.exists())
            finally:
                handler.close()
            # Closing an unused handler is a no-op that creates nothing.
            self.assertFalse(handler.db_path.exists())

    def test_connection_opens_the_database_file_on_first_use(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                self.assertFalse(handler.db_path.exists())
                handler.connection.execute("SELECT 1")
                self.assertTrue(handler.db_path.exists())
            finally:
                handler.close()

    def test_closed_unopened_handler_raises_instead_of_reconnecting(self):
        """A closed handler that never opened must not resurrect a connection."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            handler.close()
            with self.assertRaises(sqlite3.ProgrammingError):
                _ = handler.connection
            self.assertFalse(handler.db_path.exists())

    def test_is_closed_reflects_the_lazy_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            # Freshly built but never used: openable, therefore not closed.
            self.assertFalse(handler.is_closed())
            # Opening the connection does not close it.
            handler.connection.execute("SELECT 1")
            self.assertFalse(handler.is_closed())
            handler.close()
            self.assertTrue(handler.is_closed())
            handler.close()  # idempotent
            self.assertTrue(handler.is_closed())

    def test_unique_profile_name_constraint_rejects_duplicates(self):
        """``profiles.name`` is UNIQUE, matching the ``monitors`` table.

        Profile names are used as identifiers (lookup/delete by name), so two
        profiles must not share a name.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = SQLiteHandler(logger=self.logger, db_dir=tmp_dir)
            try:
                handler.create_schema()

                # The constraint is declared inline in the table definition
                # (regression: ``profiles.name`` used to be a plain NOT NULL
                # column with no uniqueness).
                ddl = handler.connection.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='profiles'"
                ).fetchone()["sql"]
                self.assertIn("UNIQUE", ddl.upper())

                self.assertIsNotNone(
                    handler.add_profile(name="dup-profile", profile_type="s3", config={})
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    handler.add_profile(name="dup-profile", profile_type="s3", config={})
            finally:
                handler.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run integration tests for sqlite_handler using unittest."
    )
    parser.add_argument(
        "-d", "--db-dir",
        type=str,
        default="testdb/dev",
        metavar="<PATH>",
        help="Directory of SQlite database"
    )
    parser.add_argument(
        "--test-cases",
        type=str,
        nargs="+",
        help="Space-separated list of test method names (or substrings) to run. Leave empty to run all tests."
    )
    args = parser.parse_args()

    # Setup logger for the __main__ block's local use
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    console_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    logger = logging.getLogger(__name__)
    logger.info("Starting Sqlite Handler Tests")

    # These assignments are necessary for the direct execution via __main__
    # to override the temporary paths set by BaseTestClass.setUpClass.
    TestSqliteHandler.db_dir = args.db_dir
    TestSqliteHandler.logger = logger

    # Also ensure a schema is created for direct runs if it doesn't exist, using the specified db_dir.
    # This part remains similar to allow direct execution to function as before.
    sqlite_handler = SQLiteHandler(logger=logger, db_dir=args.db_dir)
    if not sqlite_handler.is_initialized():
        sqlite_handler.create_schema()
    sqlite_handler.close()

    # Run Tests
    test_loader = unittest.TestLoader()
    full_suite = test_loader.loadTestsFromTestCase(TestSqliteHandler)

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
