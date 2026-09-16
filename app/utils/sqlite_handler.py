import json
import logging
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self

from app.cli.schema_versioning import SCHEMA_MIGRATIONS, compare_versions, parse_version
from app.utils.constants import DB_FILENAME


class SQLiteHandler:
    def __init__(self, logger: logging.Logger, db_dir: str) -> None:
        self.logger = logger
        self.db_path = Path(db_dir) / DB_FILENAME
        self._lock = threading.RLock()

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open standard connection with busy timeout for multi-process safety
        self.connection: sqlite3.Connection = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        # Enable Foreign Key support in SQLite
        self.connection.execute("PRAGMA foreign_keys = ON;")
        # Enable Write-Ahead Logging (WAL) for concurrent read/write across processes
        self.connection.execute("PRAGMA journal_mode = WAL;")
        self.connection.execute("PRAGMA busy_timeout = 30000;")

    @property
    def cursor(self) -> sqlite3.Cursor:
        """
        Return a standard sqlite3.Cursor on the connection.

        Provided for backward compatibility with direct cursor usages
        (e.g., test setup/teardown).
        """
        return self.connection.cursor()

    @contextmanager
    def transaction(
        self, error_message: str | None = None
    ) -> Generator[sqlite3.Cursor, None, None]:
        """
        Context manager for thread-safe atomic transactions.

        :param error_message: When given, a sqlite3.Error is logged with this
            message before being re-raised. Other exceptions are re-raised
            without logging.

        Acquires the handler's RLock, yields a standard cursor, commits on
        successful completion, or rolls back if an unhandled exception is raised.
        The decision to use `with self.transaction()` is based on whether the operation mutates state 
        and requires a commit/rollback, not on the count of statements.
        Read-only queries use :meth:`read_cursor` instead, which never commits.
        """
        with self._lock:
            cur = self.connection.cursor()
            try:
                yield cur
                self.connection.commit()
            except Exception as exception:
                self.connection.rollback()
                if error_message and isinstance(exception, sqlite3.Error):
                    self.logger.error(f"{error_message}: {exception}")
                raise
            finally:
                cur.close()

    @contextmanager
    def read_cursor(
        self, error_message: str | None = None
    ) -> Generator[sqlite3.Cursor, None, None]:
        """
        Context manager for a thread-safe read-only cursor.

        Does not commit or roll back: reads never modify the database. Use it
        for queries; use :meth:`transaction` when state is mutated.

        :param error_message: When given, a sqlite3.Error is logged with this
            message before being re-raised. Other exceptions are re-raised
            without logging.
        """
        with self._lock:
            cur = self.connection.cursor()
            try:
                yield cur
            except sqlite3.Error as exception:
                if error_message:
                    self.logger.error(f"{error_message}: {exception}")
                raise
            finally:
                cur.close()

    def _execute_statement(
        self, sql: str, params: dict[str, Any], error_message: str
    ) -> bool:
        """
        Execute a single mutating statement.

        :return: True when a row was affected, False when the statement matched
            no rows. A no-match is an expected outcome (e.g. an unknown id),
            while a database error is logged and re-raised so the caller can
            decide how to report it.
        """
        with self.transaction(error_message) as cur:
            cur.execute(sql, params)
            return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            if self.connection:
                self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def is_initialized(self) -> bool:
        """
        Return True once the application schema has been created.

        The database is considered initialised when the 'monitors' table
        exists in sqlite_master.
        """
        with self.read_cursor(
            "Error checking whether the database is initialised"
        ) as cur:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='monitors'"
            )
            return cur.fetchone() is not None

    def drop_schema(self) -> None:
        """
        Drop all application tables.

        Used by `mhub.py database init --recreate` to rebuild the schema from
        scratch. Table names are hard-coded, so no untrusted input reaches the
        SQL statements.
        """
        with self.transaction() as cur:
            for table in (
                "monitor_profile_map",
                "monitors",
                "profiles",
                "schema_version",
            ):
                cur.execute(f"DROP TABLE IF EXISTS {table}")

    def create_schema(self) -> None:
        """
        Create the database schema if it doesn't exist
        """
        with self.transaction() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    description TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS monitors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    monitor_path TEXT NOT NULL,
                    remote_path TEXT,
                    monitor_type TEXT NOT NULL,
                    config JSON,
                    status TEXT,
                    pid INTEGER DEFAULT 0,
                    last_run DATETIME,
                    last_heartbeat DATETIME,
                    last_modified DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    profile_type TEXT NOT NULL,
                    config JSON,
                    date_created DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_modified DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS monitor_profile_map (
                    monitor_id INTEGER NOT NULL,
                    profile_id INTEGER NOT NULL,
                    PRIMARY KEY (monitor_id, profile_id),
                    FOREIGN KEY (monitor_id) REFERENCES monitors (id) ON DELETE CASCADE,
                    FOREIGN KEY (profile_id) REFERENCES profiles (id) ON DELETE CASCADE
                )
            """)

        self.apply_pending_migrations()

    def _record_schema_version(self, version: str, description: str | None) -> None:
        """
        Append a row to the ``schema_version`` history table (idempotent).

        Rows are never overwritten, so the table remains an audit trail of every
        schema version that has been applied to this database.
        """
        # Write without committing: the caller (create_schema or
        # apply_pending_migrations) owns the transaction and commits it.
        with self._lock:
            cur = self.connection.cursor()
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO schema_version (version, description)
                    VALUES (:version, :description)
                    """,
                    {"version": version, "description": description},
                )
            finally:
                cur.close()

    def apply_pending_migrations(self) -> list[str]:
        """
        Apply schema migrations newer than the current database schema version.

        Each pending migration in :data:`SCHEMA_MIGRATIONS` is applied in
        ascending version order and recorded in the ``schema_version`` table.
        Returns the list of schema versions that were applied (possibly empty).
        """
        # Deliberately not using the context managers: this loop holds the lock
        # across several migrations and commits each one as it is applied.
        with self._lock:
            current = self.get_current_schema_version()
            applied: list[str] = []

            # Apply migrations in ascending version order regardless of how
            # ``SCHEMA_MIGRATIONS`` is ordered, so a mis-ordered registry entry can
            # never cause a migration to be skipped or applied out of sequence.
            ordered = sorted(SCHEMA_MIGRATIONS, key=lambda entry: parse_version(entry[0]))
            for version, description, apply_fn in ordered:
                if current and compare_versions(version, current) <= 0:
                    continue

                try:
                    if apply_fn is not None:
                        apply_fn(self)
                    self._record_schema_version(version, description)
                    self.connection.commit()
                    applied.append(version)
                    self.logger.info(f"Applied schema migration {version}: {description}")
                except Exception as exc:
                    self.connection.rollback()
                    self.logger.error(f"Schema migration {version} failed: {exc}")
                    raise

            return applied

    def update_schema_version(self, version: str, description: str | None = None) -> None:
        """
        Append a schema version to the database's version history (idempotent).

        Kept as a thin wrapper for callers that want to record a version
        directly; prefer :meth:`apply_pending_migrations` for normal upgrades.
        """
        with self.transaction() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO schema_version (version, description)
                VALUES (:version, :description)
                """,
                {"version": version, "description": description},
            )

    def get_current_schema_version(self) -> str:
        """
        Get the highest schema version recorded in the database.

        Versions are compared numerically (``"9.0.0"`` is older than
        ``"10.0.0"``), not lexicographically. Returns ``""`` when the table
        exists but no version has been recorded yet. Raises ``sqlite3.Error``
        when the database has no ``schema_version`` table; callers that must
        tolerate an uninitialised database check :meth:`is_initialized` first.
        """
        with self.read_cursor("Error reading the current schema version") as cur:
            cur.execute("SELECT version FROM schema_version")
            rows = cur.fetchall()

        if not rows:
            return ""
        return max((row["version"] for row in rows), key=parse_version)

    def get_schema_versions(self) -> list[dict[str, Any]]:
        """
        Return all schema versions in ascending numeric order of version.

        Each entry is a dictionary with keys 'version', 'description' and
        'updated_at'. Returns an empty list when the table exists but no version has
        been recorded yet. Raises ``sqlite3.Error`` when the database has no
        ``schema_version`` table; callers that must tolerate an uninitialised
        database check :meth:`is_initialized` first.
        """
        with self.read_cursor("Error reading schema versions") as cur:
            cur.execute(
                """
                SELECT version, description, updated_at
                FROM schema_version
                """
            )
            rows = cur.fetchall()

        entries = [
            {
                "version": row["version"],
                "description": row["description"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        entries.sort(key=lambda entry: parse_version(entry["version"]))
        return entries

    def _row_to_monitor(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a monitors table sqlite3.Row to a monitor dictionary."""
        config_val = row["config"]
        return {
            "id": row["id"],
            "name": row["name"],
            "monitor_path": row["monitor_path"],
            "remote_path": row["remote_path"],
            "monitor_type": row["monitor_type"],
            "config": json.loads(config_val) if config_val else None,
            "status": row["status"],
            "pid": row["pid"] if row["pid"] is not None else 0,
            "last_run": row["last_run"],
            "last_heartbeat": row["last_heartbeat"],
        }

    def _row_to_profile(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a profiles table sqlite3.Row to a profile dictionary."""
        config_val = row["config"]
        return {
            "id": row["id"],
            "name": row["name"],
            "profile_type": row["profile_type"],
            "config": json.loads(config_val) if config_val else None,
            "date_created": row["date_created"],
            "last_modified": row["last_modified"],
        }

    def add_monitor(
        self,
        name: str,
        monitor_path: str,
        remote_path: str,
        monitor_type: str,
        config: dict[str, Any],
        status: str,
        pid: int = 0,
    ) -> int | None:
        """
        Add a monitor to the database
        """
        config_str = json.dumps(config)
        try:
            with self.transaction() as cur:
                cur.execute("""
                    INSERT INTO monitors (name, monitor_path, remote_path, monitor_type, config, status, pid)
                    VALUES (:name, :monitor_path, :remote_path, :monitor_type, :config, :status, :pid)
                """, {
                    "name": name,
                    "monitor_path": monitor_path,
                    "remote_path": remote_path,
                    "monitor_type": monitor_type,
                    "config": config_str,
                    "status": status,
                    "pid": pid,
                })
                return cur.lastrowid
        except Exception as e:
            self.logger.error(f"Error adding monitor '{name}': {e}")
            raise

    def update_monitor(
        self,
        monitor_id: int,
        name: str,
        monitor_path: str,
        remote_path: str,
        monitor_type: str,
        config: dict[str, Any],
        status: str,
        pid: int = 0,
    ) -> int | None:
        """
        Update a monitor in the database

        :return: The monitor id, or None when no monitor with that id exists.
        """
        config_str = json.dumps(config)
        try:
            with self.transaction() as cur:
                cur.execute("""
                    UPDATE monitors
                    SET name = :name, 
                        monitor_path = :monitor_path, 
                        remote_path = :remote_path, 
                        monitor_type = :monitor_type, 
                        config = :config, 
                        status = :status,
                        pid = :pid,
                        last_modified = CURRENT_TIMESTAMP
                    WHERE id = :id
                """, {
                    "name": name,
                    "monitor_path": monitor_path,
                    "remote_path": remote_path,
                    "monitor_type": monitor_type,
                    "config": config_str,
                    "status": status,
                    "pid": pid,
                    "id": monitor_id,
                })
                if cur.rowcount == 0:
                    return None
                return monitor_id
        except Exception as e:
            self.logger.error(f"Error updating monitor id={monitor_id}: {e}")
            raise

    def get_monitor(
        self, monitor_id: int | None = None, monitor_name: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get a monitor from the database by id or name

        :return: The monitor, or None when no monitor matched.
        """
        if monitor_id is None and monitor_name is None:
            raise ValueError("Either monitor_id or monitor_name must be provided")

        selector = f"id={monitor_id}" if monitor_id is not None else f"name={monitor_name!r}"
        with self.read_cursor(f"Error fetching monitor {selector}") as cur:
            if monitor_id is not None:
                cur.execute("SELECT * FROM monitors WHERE id = :id", {"id": monitor_id})
            else:
                cur.execute("SELECT * FROM monitors WHERE name = :name", {"name": monitor_name})

            row = cur.fetchone()

        if row:
            return self._row_to_monitor(row)
        return None

    def get_monitors(self) -> list[dict[str, Any]]:
        """
        Get all monitors from the database
        """
        with self.read_cursor("Error fetching monitors") as cur:
            cur.execute("SELECT * FROM monitors")
            rows = cur.fetchall()

        return [self._row_to_monitor(row) for row in rows]

    def update_monitor_status(self, monitor_id: int, status: str) -> bool:
        """
        Update the status of a monitor in the database

        :return: False when no monitor with that id exists.
        """
        return self._execute_statement(
            "UPDATE monitors SET status = :status, last_modified = CURRENT_TIMESTAMP WHERE id = :id",
            {"status": status, "id": monitor_id},
            f"Error updating status for monitor id={monitor_id}",
        )

    def update_monitor_pid(self, monitor_id: int, pid: int) -> bool:
        """
        Update the pid of a monitor in the database

        :return: False when no monitor with that id exists.
        """
        return self._execute_statement(
            "UPDATE monitors SET pid = :pid, last_modified = CURRENT_TIMESTAMP WHERE id = :id",
            {"pid": pid, "id": monitor_id},
            f"Error updating pid for monitor id={monitor_id}",
        )

    def update_monitor_last_run(self, monitor_id: int, last_run: str) -> bool:
        """
        Update the last run time of a monitor in the database

        :return: False when no monitor with that id exists.
        """
        return self._execute_statement(
            "UPDATE monitors SET last_run = :last_run WHERE id = :id",
            {"last_run": last_run, "id": monitor_id},
            f"Error updating last_run for monitor id={monitor_id}",
        )

    def update_monitor_last_heartbeat(self, monitor_id: int, last_heartbeat: str) -> bool:
        """
        Update the last heartbeat time of a monitor in the database

        :return: False when no monitor with that id exists.
        """
        return self._execute_statement(
            "UPDATE monitors SET last_heartbeat = :last_heartbeat WHERE id = :id",
            {"last_heartbeat": last_heartbeat, "id": monitor_id},
            f"Error updating last_heartbeat for monitor id={monitor_id}",
        )

    def update_monitor_config(self, monitor_id: int, config: dict[str, Any]) -> bool:
        """
        Update the config of a monitor in the database

        :return: False when no monitor with that id exists.
        """
        return self._execute_statement(
            "UPDATE monitors SET config = :config, last_modified = CURRENT_TIMESTAMP WHERE id = :id",
            {"config": json.dumps(config), "id": monitor_id},
            f"Error updating config for monitor id={monitor_id}",
        )

    def delete_monitor(self, monitor_id: int) -> bool:
        """
        Delete a monitor from the database.
        Foreign key CASCADE automatically cleans up monitor_profile_map entries.

        :return: False when no monitor with that id exists.
        """
        return self._execute_statement(
            "DELETE FROM monitors WHERE id = :id",
            {"id": monitor_id},
            f"Error deleting monitor id={monitor_id}",
        )

    def add_profile(self, name: str, profile_type: str, config: dict[str, Any]) -> int | None:
        """
        Add a profile to the database
        """
        try:
            with self.transaction() as cur:
                cur.execute("""
                    INSERT INTO profiles (
                        name, 
                        profile_type,
                        config, 
                        date_created, last_modified
                    )
                    VALUES (
                        :name, :profile_type, :config, 
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                """, {
                    "name": name,
                    "profile_type": profile_type,
                    "config": json.dumps(config),
                })
                return cur.lastrowid
        except Exception as e:
            self.logger.error(f"Error adding profile '{name}': {e}")
            raise

    def get_profile(
        self, profile_id: int | None = None, profile_name: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get a profile from the database by id or name

        :return: The profile, or None when no profile matched.
        """
        if profile_id is None and profile_name is None:
            raise ValueError("Either profile_id or profile_name must be provided")

        selector = f"id={profile_id}" if profile_id is not None else f"name={profile_name!r}"
        with self.read_cursor(f"Error fetching profile {selector}") as cur:
            if profile_id is not None:
                cur.execute("SELECT * FROM profiles WHERE id = :id", {"id": profile_id})
            else:
                cur.execute("SELECT * FROM profiles WHERE name = :name", {"name": profile_name})

            row = cur.fetchone()

        if row:
            return self._row_to_profile(row)
        return None

    def update_profile(self, profile_id: int, name: str, profile_type: str, config: dict[str, Any]) -> int | None:
        """
        Update a profile in the database

        :return: The profile id, or None when no profile with that id exists.
        """
        try:
            with self.transaction() as cur:
                cur.execute("""
                    UPDATE profiles
                    SET name = :name, 
                        profile_type = :profile_type, 
                        config = :config, 
                        last_modified = CURRENT_TIMESTAMP
                    WHERE id = :id
                """, {
                    "name": name,
                    "profile_type": profile_type,
                    "config": json.dumps(config),
                    "id": profile_id,
                })
                if cur.rowcount == 0:
                    return None
                return profile_id
        except Exception as e:
            self.logger.error(f"Error updating profile id={profile_id}: {e}")
            raise

    def delete_profile(self, profile_id: int | None = None, profile_name: str | None = None) -> bool:
        """
        Delete a profile from the database.
        Foreign key CASCADE automatically cleans up monitor_profile_map entries.

        :return: False when no profile matched.
        """
        if profile_id is None and profile_name is None:
            raise ValueError("Either profile_id or profile_name must be provided")

        if profile_id is not None:
            sql = "DELETE FROM profiles WHERE id = :id"
            params = {"id": profile_id}
            description = f"id={profile_id}"
        else:
            sql = "DELETE FROM profiles WHERE name = :name"
            params = {"name": profile_name}
            description = f"name={profile_name!r}"

        return self._execute_statement(sql, params, f"Error deleting profile {description}")

    def get_profiles(self) -> list[dict[str, Any]]:
        """
        Get all profiles from the database
        """
        with self.read_cursor("Error fetching profiles") as cur:
            cur.execute("SELECT * FROM profiles")
            rows = cur.fetchall()

        return [self._row_to_profile(row) for row in rows]

    def add_monitor_profile_map(self, monitor_id: int, profile_id: int) -> bool:
        """
        Add a mapping between a monitor and a profile in the database.

        :return: False when the mapping already exists (INSERT OR IGNORE).
            A foreign key violation (unknown monitor or profile id) raises
            sqlite3.IntegrityError: INSERT OR IGNORE does not suppress it.
        """
        return self._execute_statement(
            """
                INSERT OR IGNORE INTO monitor_profile_map (monitor_id, profile_id)
                VALUES (:monitor_id, :profile_id)
            """,
            {"monitor_id": monitor_id, "profile_id": profile_id},
            f"Error mapping monitor {monitor_id} to profile {profile_id}",
        )

    def delete_monitor_profile_map(self, monitor_id: int, profile_id: int) -> bool:
        """
        Delete a mapping between a monitor and a profile from the database

        :return: False when the mapping did not exist.
        """
        return self._execute_statement(
            """
                DELETE FROM monitor_profile_map
                WHERE monitor_id = :monitor_id AND profile_id = :profile_id
            """,
            {"monitor_id": monitor_id, "profile_id": profile_id},
            f"Error unmapping monitor {monitor_id} from profile {profile_id}",
        )

    def get_profiles_for_monitor(self, monitor_id: int) -> list[dict[str, Any]]:
        """
        Get all profiles linked to a specific monitor from the database
        """
        with self.read_cursor(
            f"Error fetching profiles for monitor id={monitor_id}"
        ) as cur:
            cur.execute(
                """
                SELECT p.*
                FROM profiles p
                JOIN monitor_profile_map mpm ON p.id = mpm.profile_id
                WHERE mpm.monitor_id = :monitor_id
                """,
                {"monitor_id": monitor_id},
            )
            rows = cur.fetchall()

        return [self._row_to_profile(row) for row in rows]

    def get_monitors_for_profile(self, profile_id: int) -> list[dict[str, Any]]:
        """
        Get all monitors linked to a profile from the database
        """
        with self.read_cursor(
            f"Error fetching monitors for profile id={profile_id}"
        ) as cur:
            cur.execute(
                """
                SELECT m.*
                FROM monitors m
                JOIN monitor_profile_map mpm ON m.id = mpm.monitor_id
                WHERE mpm.profile_id = :profile_id
                """,
                {"profile_id": profile_id},
            )
            rows = cur.fetchall()

        return [self._row_to_monitor(row) for row in rows]

    def __del__(self) -> None:
        self.close()
