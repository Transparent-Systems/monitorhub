"""Database subcommands for MonitorHub."""

import os

from scripts.constants import MONITOR_STATUS_STOPPED, MONITOR_TYPE_INSTANT
from scripts.prompt_service import PromptService
from scripts.sqlite_handler import SQLiteHandler


class DatabaseCommands:
    """Database initialisation, info, and sample-data commands."""

    def __init__(self, sqlite_handler: SQLiteHandler, prompt: PromptService) -> None:
        self.sqlite_handler = sqlite_handler
        self.prompt = prompt

    def info(self):
        """
        Print information about the SQLite database
        """
        db_path = self.sqlite_handler.db_path
        # Resolve the absolute path of the database file
        db_path = os.path.abspath(db_path) if db_path else None
        if not db_path:
            self.prompt.print("SQLite database path is not set.")
            return
        self.prompt.print(f"Location of SQLite database: {db_path}")

    def version(self):
        """
        Print the version of the SQLite database
        """
        db_version = self.sqlite_handler.get_current_schema_version()
        if not db_version:
            self.prompt.print("SQLite database version is not set.")
            return
        self.prompt.print(f"Version of SQLite database: {db_version}")

    def init(self, recreate: bool = False):
        """
        Initialise the SQLite database by creating the schema and loading the
        support tables.

        When ``recreate`` is True, the existing schema is dropped first so the
        database is rebuilt from scratch.
        """
        if recreate:
            self.prompt.print("")
            self.prompt.print("!!! WARNING: --recreate is DESTRUCTIVE !!!")
            self.prompt.print("This will DELETE the entire database and ALL its data.")
            self.prompt.print(f"Database location: {self.sqlite_handler.db_path}")
            self.prompt.print("")
            self.prompt.print("Please make a backup before proceeding.")
            answer = self.prompt.input("Do you want to delete the current database and create a new one? (N/y): ")
            if answer.strip().lower() != "y":
                self.prompt.print("Operation cancelled.")
                return
            if self.sqlite_handler.is_initialized():
                self.sqlite_handler.drop_schema()
                self.prompt.print("Existing schema dropped.")
            self.sqlite_handler.create_schema()
            self.prompt.print(f"Database initialised (schema recreated) at {self.sqlite_handler.db_path}")
            return

        if self.sqlite_handler.is_initialized():
            self.prompt.print(f"Database already initialised at {self.sqlite_handler.db_path}")
            return

        self.sqlite_handler.create_schema()
        self.prompt.print(f"Database initialised at {self.sqlite_handler.db_path}")

    def sample_data(self):
        """
        Load example profile and monitor sample data into the database.

        This is an opt-in convenience for end users who want to see how
        profiles, monitors, and their mapping look without reading the manual.
        The data uses clearly fake credentials and paths and is added with
        status 'stopped' so it is never accidentally started.
        """
        # Ensure schema exists before adding sample data.
        if not self.sqlite_handler.is_initialized():
            self.sqlite_handler.create_schema()

        profile_name = "Example S3 profile"
        if self.sqlite_handler.get_profile(profile_name=profile_name):
            self.prompt.print(f"Sample profile '{profile_name}' already exists. Sample data not loaded.")
            return

        profile_config = {
            "provider_name": "Other",
            "access_key_id": "FAKE_ACCESS_KEY_ID",
            "access_key_secret": "FAKE_ACCESS_KEY_SECRET",
            "endpoint": "https://example.invalid",
        }

        profile_id = self.sqlite_handler.add_profile(
            name=profile_name,
            profile_type="s3",
            config=profile_config,
        )

        monitor_name = "Example monitor"
        monitor_id = self.sqlite_handler.add_monitor(
            name=monitor_name,
            monitor_path="/path/to/your/folder",
            remote_path="example-remote-folder",
            monitor_type=MONITOR_TYPE_INSTANT,
            config={},
            status=MONITOR_STATUS_STOPPED,
            pid=0,
        )

        if profile_id is not None and monitor_id is not None:
            self.sqlite_handler.add_monitor_profile_map(
                monitor_id=monitor_id,
                profile_id=profile_id,
            )

        self.prompt.print("Sample data loaded:")
        self.prompt.print(f"  Profile: {profile_name} (id: {profile_id})")
        self.prompt.print(f"  Monitor: {monitor_name} (id: {monitor_id})")
        self.prompt.print("These are examples with fake credentials and paths.")
        self.prompt.print("Delete them with 'profile delete' and 'monitor delete'.")
