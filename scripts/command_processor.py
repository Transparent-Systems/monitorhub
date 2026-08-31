import logging
import os

from scripts.database_commands import DatabaseCommands
from scripts.monitor_commands import MonitorCommands
from scripts.profile_commands import ProfileCommands
from scripts.prompt_service import PromptService
from scripts.sqlite_handler import SQLiteHandler
from scripts.utils.diagnostic_util import DiagnosticUtil
from version import VERSION_STRING

class CommandProcessor:
    """
    Processes command line commands for the MonitorHub application.
    """

    def __init__(
        self,
        logger: logging.Logger,
        db_dir: str,
        log_config: str = "conf/log.yaml",
        log_level: str | None = None,
        prompt: PromptService | None = None,
    ):
        self.logger = logger
        # Filter logging to avoid noise on the console
        self.logger.setLevel(logging.WARNING)
        self.logger.propagate = False
        self.db_dir = db_dir
        self.log_config = log_config
        self.log_level = log_level

        # Silence boto3 and other libraries
        logging.getLogger("boto3").setLevel(logging.WARNING)
        logging.getLogger("botocore").setLevel(logging.WARNING)
        logging.getLogger("s3transfer").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

        self.diagnostic_util = DiagnosticUtil(
            db_dir=db_dir,
            logger=self.logger
            )
        self.sqlite_handler = SQLiteHandler(
            logger=self.logger,
            db_dir=db_dir
        )

        self.prompt = prompt or PromptService()

        self.database = DatabaseCommands(self.sqlite_handler, self.prompt)
        self.profile = ProfileCommands(self.sqlite_handler, self.logger, self.diagnostic_util, self.prompt)
        self.monitor = MonitorCommands(
            self.sqlite_handler,
            self.logger,
            self.db_dir,
            self.log_config,
            self.log_level,
            self.prompt,
        )

    def version(self):
        """
        Show application version
        """
        self.prompt.print(f"MonitorHub version: ({VERSION_STRING})")

    def config_test(self):
        """
        Test configuration
        """
        try:
            diagnostic_util = DiagnosticUtil(
                db_dir=self.db_dir,
                logger=self.logger)
            if (not diagnostic_util.check_app_env()):
                return

            diagnostic_util.check_profile_import()
            if not diagnostic_util.check_rclone_dependency():
                return

            if not diagnostic_util.check_monitor_config():
                return
            
            if not diagnostic_util.check_rclone_dependency():
                return
            
            diagnostic_util.print_overview()
            return
        finally:
            self.prompt.print("Exiting test mode now")

    # --- DatabaseCommands delegation ---

    def database_info(self):
        """Print information about the SQLite database."""
        self.database.database_info()

    def database_init(self, recreate: bool = False):
        """Initialise the SQLite database schema."""
        self.database.database_init(recreate=recreate)

    def database_sample_data(self):
        """Load example profile and monitor sample data."""
        self.database.database_sample_data()

    # --- MonitorCommands delegation ---

    def monitor_delete(self):
        """Delete a monitor."""
        self.monitor.monitor_delete()

    def monitor_edit(self):
        """Edit a monitor."""
        self.monitor.monitor_edit()

    def monitor_new(self):
        """Create a new monitor."""
        self.monitor.monitor_new()

    def monitor_show(self):
        """Show all monitors."""
        self.monitor.monitor_show()

    def monitor_test(self, monitor_id: int | None = None, monitor_name: str | None = None):
        """Test monitor configuration."""
        self.monitor.monitor_test(monitor_id=monitor_id, monitor_name=monitor_name)

    def monitor_start(self, monitor_id: int | None = None, monitor_name: str | None = None):
        """Start a single monitor."""
        self.monitor.monitor_start(monitor_id=monitor_id, monitor_name=monitor_name)

    def monitor_start_all(self):
        """Start all monitors that are not running."""
        self.monitor.monitor_start_all()

    def monitor_stop(self, monitor_id: int | None = None, immediate: bool = False, monitor_name: str | None = None):
        """Stop a running monitor."""
        self.monitor.monitor_stop(monitor_id=monitor_id, immediate=immediate, monitor_name=monitor_name)

    def monitor_stop_all(self, immediate: bool = False):
        """Stop all running monitors."""
        self.monitor.monitor_stop_all(immediate=immediate)

    # --- ProfileCommands delegation ---

    def profile_test(self, profile_id: int | None = None, live: bool = False):
        """Test selected profile for connectivity."""
        self.profile.profile_test(profile_id=profile_id, live=live)

    def profile_delete(self):
        """Show all profiles and let user choose one to delete."""
        self.profile.profile_delete()

    def profile_edit(self):
        """Show all profiles and let user choose one to edit."""
        self.profile.profile_edit()

    def profile_new(self):
        """Create a new profile (interactively select the category)."""
        self.profile.profile_new()

    def profile_show(self):
        """Show all profiles."""
        self.profile.profile_show()

    def profile_import(self):
        """Import profiles from rclone."""
        self.profile.profile_import()
