"""Test-data helper: seeds and cleans the SQLite database used by tests and dev.

Import it from other tests, or run it directly from the project root with:
    python -m tests.database_test_data --help
"""

import argparse
import logging
import os

from dotenv import load_dotenv

from app.utils.constants import (
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)
from app.utils.sqlite_handler import SQLiteHandler


class DatabaseTestData:
    """
    Class to manage test data in the SQLite database for testing purposes.
    """

    def __init__(self, logger: logging.Logger, db_dir: str | None, dotenv_path: str | None):
        self.dotenv_path = dotenv_path
        self.logger = logger
        if db_dir is None:
            db_dir = "testdb/unittest"
        self.sqlite_handler: SQLiteHandler = SQLiteHandler(
            logger=logger,
            db_dir=db_dir
        )

        self.sqlite_handler.create_schema()


    def load_test_data(self):
        """
        Add test data to SQLite database
        """

        self.logger.info("Loading test data")
        self.logger.info(f"dotenv_path: {self.dotenv_path}")

        load_dotenv(self.dotenv_path)

        S3_TEST_ACCESS_KEY_ID = os.environ.get("S3_TEST_ACCESS_KEY_ID")
        S3_TEST_ACCESS_KEY_SECRET = os.environ.get("S3_TEST_ACCESS_KEY_SECRET")
        S3_TEST_ENDPOINT = os.environ.get("S3_TEST_ENDPOINT")
        RCLONE_TEST_FTP_PASS = os.environ.get("RCLONE_TEST_FTP_PASS")

        # Add profiles to database
        test_profiles = [
            {
                "category": "remote",
                "name": "s3-test",
                "type": "s3",
                "config": {
                    "provider_name" : "IDrive",
                    "access_key_id" : f"{S3_TEST_ACCESS_KEY_ID}",
                    "access_key_secret" : f"{S3_TEST_ACCESS_KEY_SECRET}",
                    "endpoint" : f"{S3_TEST_ENDPOINT}",
                    "comment": "Credentials stored here are for informational purposes only."
                    }
            },
            {
                "category": "remote",
                "name": "ftp-test",
                "type": "ftp",
                "config": {
                    "host": "192.168.1.51",
                    "user": "ftpuser",
                    "pass": f"{RCLONE_TEST_FTP_PASS}",
                    "comment": "Credentials stored here are for informational purposes only.",
                    "important": "Profile must be in rclone config in order to work ! "
                }
            },
            {
                "category": "command",
                "name": "command-test",
                "type": "event_command",
                "config": {
                    "command": "notify-send \"Testing command from monitor = {monitor_name}, profile = {profile_name}, event = {event_name}, source path = {src_path}\"", 
                    "command_events": ["created", "deleted", "modified", "timer"], 
                    "command_cooldown": "0s", 
                    "command_shell": "false",
                    "command_timeout": "10s"
                }
            }
        ]

        # Add profiles to database
        for profile in test_profiles:
            self.logger.debug(f"Adding profile: {profile['name']}")
            # Add profile to database
            self.sqlite_handler.add_profile(
                name=profile["name"],
                profile_type=profile["type"],
                config=profile["config"]
            )

        # Create monitors
        test_monitors = [
            {
                "name": "Instant Monitor 1",
                "monitor_path": "testdata/source/instant-monitor",
                "remote_path": "test-monitorhub/instant-monitor",
                "monitor_type": f"{MONITOR_TYPE_INSTANT}",
                "config": {},
                "status": "stopped",
                "pid": 0
            },
            {
                "name": "Backup Monitor 1",
                "monitor_path": "testdata/source/backup-monitor",
                "remote_path": "test-monitorhub/backup-monitor",
                "monitor_type": f"{MONITOR_TYPE_BACKUP}",
                "config": {"interval": "1m"},
                "status": "stopped",
                "pid": 0
            },
            {
                "name": "Restore Monitor 1",
                "monitor_path": "testdata/source/restore-monitor",
                "remote_path": "test-monitorhub/restore-monitor",
                "monitor_type": f"{MONITOR_TYPE_RESTORE}",
                "config": {"interval": "1m"},
                "status": "stopped",
                "pid": 0
            }
        ]

        for monitor in test_monitors:
            self.logger.debug(f"Adding monitor: {monitor['name']}")
            # Add monitor to database
            self.sqlite_handler.add_monitor(
                name=monitor["name"],
                monitor_path=monitor["monitor_path"],
                remote_path=monitor["remote_path"],
                monitor_type=monitor["monitor_type"],
                config=monitor["config"],
                status=monitor["status"],
                pid=monitor["pid"]
            )

        monitors = self.sqlite_handler.get_monitors()
        profiles = self.sqlite_handler.get_profiles()

        # Link monitors to all profiles
        for monitor in monitors:
            for profile in profiles:
                self.sqlite_handler.add_monitor_profile_map(monitor_id=monitor["id"], profile_id=profile["id"])
        
        self.logger.info("Loading test data completed")



    def remove_test_data(self):
        """
        Remove test data from SQLite database
        Do not wipe out support tables like provider and (virtual) lookup_tables
        """

        self.logger.info("Removing test data")
        # Check if database connection is open before attempting to clean up
        try:
            if self.sqlite_handler.connection is None:
                self.logger.warning("SQLite connection is already closed. Skipping cleanup.")
                return
            
            monitors = self.sqlite_handler.get_monitors()
            for monitor in monitors:
                monitor_id = monitor["id"]
                # Now delete this monitor
                self.sqlite_handler.delete_monitor(monitor_id=monitor_id)

            # Delete all profiles
            profiles = self.sqlite_handler.get_profiles()
            for profile in profiles:
                self.sqlite_handler.delete_profile(profile["id"])

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error during teardown: {e}")
        finally:    
            self.logger.info("Cleanup database completed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test data into the SQLite database.")
    parser.add_argument(
        "-d",
        "--db-dir",
        default="testdb/dev",
        help="Directory containing the database file (default: testdb/dev).",
    )
    parser.add_argument(
        "--dotenv-path",
        default=None,
        help="Path to the .env file (default: <db-dir>/.env).",
    )
    args = parser.parse_args()

    logger = logging.getLogger()
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    db_dir = args.db_dir
    dotenv_path = args.dotenv_path or f"{db_dir}/.env"
    database_test_data = DatabaseTestData(
        logger=logger,
        db_dir=db_dir,
        dotenv_path=dotenv_path,
    )

    database_test_data.load_test_data()
