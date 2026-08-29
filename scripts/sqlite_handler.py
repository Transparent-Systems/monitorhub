import datetime
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from scripts.constants import DATABASE_SCHEMA_VERSION, DB_FILENAME


class _LockedConnection:
    """
    Thread-safe wrapper around a sqlite3.Connection.

    check_same_thread=False allows the underlying connection to be shared
    across threads. The shared RLock ensures only one operation runs at a
    time, preventing interleaved cursor/commit/rollback use across threads.
    """

    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock) -> None:
        self._connection = connection
        self._lock = lock

    def commit(self) -> None:
        with self._lock:
            self._connection.commit()

    def rollback(self) -> None:
        with self._lock:
            self._connection.rollback()

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class _LockedCursor:
    """
    Thread-safe wrapper around a sqlite3.Cursor.

    Delegates the operations used by SQLiteHandler to the underlying cursor
    while holding the shared RLock, so existing `self.cursor.execute(...)`
    call sites remain valid and thread-safe.
    """

    def __init__(self, cursor: sqlite3.Cursor, lock: threading.RLock) -> None:
        self._cursor = cursor
        self._lock = lock

    def execute(self, query: str, params: Any = None):
        with self._lock:
            if params is None:
                return self._cursor.execute(query)
            return self._cursor.execute(query, params)

    def executemany(self, query: str, seq_of_params: Any):
        with self._lock:
            return self._cursor.executemany(query, seq_of_params)

    def fetchone(self) -> Any:
        with self._lock:
            return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        with self._lock:
            return self._cursor.fetchall()

    @property
    def lastrowid(self) -> int | None:
        with self._lock:
            return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        with self._lock:
            return self._cursor.rowcount


class SQLiteHandler:
    def __init__(self, logger: logging.Logger, db_dir: str) -> None:
        self.logger = logger
        self.db_path = Path(db_dir) / DB_FILENAME
        self._lock = threading.RLock()
        
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        raw_connection = sqlite3.connect(self.db_path, check_same_thread=False)
        raw_connection.row_factory = sqlite3.Row
        # Enable Foreign Key support in SQLite
        raw_connection.execute("PRAGMA foreign_keys = ON;")

        self.connection = _LockedConnection(raw_connection, self._lock)
        self.cursor = _LockedCursor(raw_connection.cursor(), self._lock)

    def close(self) -> None:
        if self.connection:
            self.connection.close()

    def __enter__(self) -> "SQLiteHandler":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def is_initialized(self) -> bool:
        """
        Return True once the application schema has been created.

        The database is considered initialised when the 'monitors' table
        exists in sqlite_master.
        """
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='monitors'"
        )
        return self.cursor.fetchone() is not None

    def drop_schema(self) -> None:
        """
        Drop all application tables.

        Used by `mhub.py database init --recreate` to rebuild the schema from
        scratch. Table names are hard-coded, so no untrusted input reaches the
        SQL statements.
        """
        for table in (
            "monitor_profile_map",
            "monitors",
            "profiles",
            "schema_version",
        ):
            self.cursor.execute(f"DROP TABLE IF EXISTS {table}")
        self.connection.commit()

    def create_schema(self) -> None:
        """
        Create the database schema if it doesn't exist
        """
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.cursor.execute("""
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

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                profile_type TEXT NOT NULL,
                config JSON,
                date_created DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_modified DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitor_profile_map (
                monitor_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                PRIMARY KEY (monitor_id, profile_id),
                FOREIGN KEY (monitor_id) REFERENCES monitors (id) ON DELETE CASCADE,
                FOREIGN KEY (profile_id) REFERENCES profiles (id) ON DELETE CASCADE
            )
        """)

        self.connection.commit()
        self.init_database_version()

    def init_database_version(self) -> None:
        """
        Initialise the database version if it does not exist.
        """
        database_version = DATABASE_SCHEMA_VERSION
        self.cursor.execute(
            "SELECT version FROM schema_version WHERE version = :version",
            {"version": database_version},
        )
        if not self.cursor.fetchone():
            self.cursor.execute(
                "INSERT INTO schema_version (version) VALUES (:version)",
                {"version": database_version},
            )
            self.connection.commit()
            self.logger.info(f"Database version initialised to {database_version}")
        else:
            self.logger.info(f"Database version already initialised to {database_version}")

    def update_schema_version(self, version: str) -> None:
        """
        Update the schema version in the database
        """
        self.cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (:version)",
            {"version": version},
        )
        self.connection.commit()

    def get_current_schema_version(self) -> str:
        """
        Get the current schema version from the database
        """
        self.cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        result = self.cursor.fetchone()
        return result["version"] if result else ""

    def get_schema_versions(self) -> list[dict[str, Any]]:
        """
        Return all schema versions in ascending order of version.
        Each entry is a dictionary with keys 'version' and 'updated_at'.
        """
        self.cursor.execute("""
            SELECT version, updated_at
            FROM schema_version
            ORDER BY version ASC
        """)
        rows = self.cursor.fetchall()
        return [
            {"version": row["version"], "updated_at": row["updated_at"]}
            for row in rows
        ]

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
            self.cursor.execute("""
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
            self.connection.commit()
            return self.cursor.lastrowid
        except Exception as e:
            self.connection.rollback()
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
        """
        config_str = json.dumps(config)
        try:
            self.cursor.execute("""
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
            self.connection.commit()
            return monitor_id
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error updating monitor id={monitor_id}: {e}")
            raise

    def get_monitor(self, monitor_id: int | None = None, monitor_name: str | None = None) -> dict[str, Any]:
        """
        Get a monitor from the database by id or name
        """
        try:
            if monitor_id is not None:
                self.cursor.execute("SELECT * FROM monitors WHERE id = :id", {"id": monitor_id})
            elif monitor_name is not None:
                self.cursor.execute("SELECT * FROM monitors WHERE name = :name", {"name": monitor_name})
            else:
                raise ValueError("Either monitor_id or monitor_name must be provided")

            row = self.cursor.fetchone()
            if row:
                return self._row_to_monitor(row)
        except Exception as e:
            self.logger.error(f"Error fetching monitor: {e}")
        return {}

    def get_monitors(self) -> list[dict[str, Any]]:
        """
        Get all monitors from the database
        """
        self.cursor.execute("SELECT * FROM monitors")
        rows = self.cursor.fetchall()
        return [self._row_to_monitor(row) for row in rows]

    def update_monitor_status(self, monitor_id: int, status: str) -> bool:
        """
        Update the status of a monitor in the database
        """
        try:
            self.cursor.execute(
                "UPDATE monitors SET status = :status, last_modified = CURRENT_TIMESTAMP WHERE id = :id",
                {"status": status, "id": monitor_id},
            )
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error updating monitor status: {e}")
            return False

    def update_monitor_pid(self, monitor_id: int, pid: int) -> bool:
        """
        Update the pid of a monitor in the database
        """
        try:
            self.cursor.execute(
                "UPDATE monitors SET pid = :pid, last_modified = CURRENT_TIMESTAMP WHERE id = :id",
                {"pid": pid, "id": monitor_id},
            )
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error updating monitor pid: {e}")
            return False

    def update_monitor_last_run(self, monitor_id: int, last_run: str) -> bool:
        """
        Update the last run time of a monitor in the database
        """
        try:
            self.cursor.execute(
                "UPDATE monitors SET last_run = :last_run WHERE id = :id",
                {"last_run": last_run, "id": monitor_id},
            )
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error updating monitor last_run: {e}")
            return False

    def update_monitor_last_heartbeat(self, monitor_id: int, last_heartbeat: str) -> bool:
        """
        Update the last heartbeat time of a monitor in the database
        """
        try:
            self.cursor.execute(
                "UPDATE monitors SET last_heartbeat = :last_heartbeat WHERE id = :id",
                {"last_heartbeat": last_heartbeat, "id": monitor_id},
            )
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error updating monitor last_heartbeat: {e}")
            return False

    def update_monitor_config(self, monitor_id: int, config: dict[str, Any]) -> bool:
        """
        Update the config of a monitor in the database
        """
        config_str = json.dumps(config)
        try:
            self.cursor.execute(
                "UPDATE monitors SET config = :config, last_modified = CURRENT_TIMESTAMP WHERE id = :id",
                {"config": config_str, "id": monitor_id},
            )
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error updating monitor config: {e}")
            return False

    def delete_monitor(self, monitor_id: int) -> bool:
        """
        Delete a monitor from the database.
        Foreign key CASCADE automatically cleans up monitor_profile_map entries.
        """
        try:
            self.cursor.execute("DELETE FROM monitors WHERE id = :id", {"id": monitor_id})
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error occurred while deleting monitor: {e}")
            return False

    def add_profile(self, name: str, profile_type: str, config: dict[str, Any]) -> int | None:
        """
        Add a profile to the database
        """
        try:
            self.cursor.execute("""
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
            self.connection.commit()
            return self.cursor.lastrowid
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error adding profile '{name}': {e}")
            raise

    def get_profile(self, profile_id: int | None = None, profile_name: str | None = None) -> dict[str, Any]:
        """Get a profile from the database by id or name"""
        try:
            if profile_id is not None:
                self.cursor.execute("SELECT * FROM profiles WHERE id = :id", {"id": profile_id})
            elif profile_name is not None:
                self.cursor.execute("SELECT * FROM profiles WHERE name = :name", {"name": profile_name})
            else:
                raise ValueError("Either profile_id or profile_name must be provided")

            row = self.cursor.fetchone()
            if row:
                return self._row_to_profile(row)
        except Exception as e:
            self.logger.error(f"Error occurred while fetching profile: {e}")
        return {}

    def update_profile(self, profile_id: int, name: str, profile_type: str, config: dict[str, Any]) -> int | None:
        """
        Update a profile in the database
        """
        try:
            self.cursor.execute("""
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
            self.connection.commit()
            return profile_id
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error updating profile id={profile_id}: {e}")
            raise

    def delete_profile(self, profile_id: int | None = None, profile_name: str | None = None) -> bool:
        """
        Delete a profile from the database.
        Foreign key CASCADE automatically cleans up monitor_profile_map entries.
        """
        try:
            if profile_id is not None:
                self.cursor.execute("DELETE FROM profiles WHERE id = :id", {"id": profile_id})
            elif profile_name is not None:
                self.cursor.execute("DELETE FROM profiles WHERE name = :name", {"name": profile_name})
            else:
                raise ValueError("Either profile_id or profile_name must be provided")
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error deleting profile: {e}")
            return False

    def get_profiles(self) -> list[dict[str, Any]]:
        """
        Get all profiles from the database
        """
        self.cursor.execute("SELECT * FROM profiles")
        rows = self.cursor.fetchall()
        return [self._row_to_profile(row) for row in rows]

    def add_monitor_profile_map(self, monitor_id: int, profile_id: int) -> bool:
        """
        Add a mapping between a monitor and a profile in the database.
        """
        try:
            self.cursor.execute("""
                INSERT OR IGNORE INTO monitor_profile_map (monitor_id, profile_id)
                VALUES (:monitor_id, :profile_id)
            """, {"monitor_id": monitor_id, "profile_id": profile_id})
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error mapping monitor {monitor_id} to profile {profile_id}: {e}")
            return False

    def delete_monitor_profile_map(self, monitor_id: int, profile_id: int) -> bool:
        """
        Delete a mapping between a monitor and a profile from the database
        """
        try:
            self.cursor.execute("""
                DELETE FROM monitor_profile_map
                WHERE monitor_id = :monitor_id AND profile_id = :profile_id
            """, {"monitor_id": monitor_id, "profile_id": profile_id})
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Error unmapping monitor {monitor_id} from profile {profile_id}: {e}")
            return False

    def get_profiles_for_monitor(self, monitor_id: int) -> list[dict[str, Any]]:
        """
        Get all profiles linked to a specific monitor from the database
        """
        self.cursor.execute("""
            SELECT p.*
            FROM profiles p
            JOIN monitor_profile_map mpm ON p.id = mpm.profile_id
            WHERE mpm.monitor_id = :monitor_id
        """, {"monitor_id": monitor_id})
        rows = self.cursor.fetchall()
        return [self._row_to_profile(row) for row in rows]

    def get_monitors_for_profile(self, profile_id: int) -> list[dict[str, Any]]:
        """
        Get all monitors linked to a profile from the database
        """
        self.cursor.execute("""
            SELECT m.*
            FROM monitors m
            JOIN monitor_profile_map mpm ON m.id = mpm.monitor_id
            WHERE mpm.profile_id = :profile_id
        """, {"profile_id": profile_id})
        rows = self.cursor.fetchall()
        return [self._row_to_monitor(row) for row in rows]

    def __del__(self) -> None:
        self.close()
