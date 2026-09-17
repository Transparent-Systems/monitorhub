"""Composition root that wires MonitorHub CLI command handlers together.

This module replaces the former ``CommandProcessor``: instead of a single
monolithic class exposing one prefixed method per subcommand, it builds a
:class:`Commands` bundle of the focused command handler objects
(:class:`DatabaseCommands`, :class:`ProfileCommands`, :class:`MonitorCommands`,
and :class:`AppCommands`) together with the shared dependencies they need.

``build_commands`` is the single entry point used by the CLI to construct the
fully-wired object graph. It accepts the shared dependencies (``prompt``,
``diagnostic_util``, ``sqlite_handler``) as injectable parameters so unit tests
can substitute mocks without touching the filesystem or the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from version import VERSION_STRING

from app.cli.database_commands import DatabaseCommands
from app.cli.diagnostic_util import DiagnosticUtil
from app.cli.monitor_commands import MonitorCommands
from app.cli.profile_commands import ProfileCommands
from app.cli.prompt_service import PromptService
from app.utils.sqlite_handler import SQLiteHandler


class AppCommands:
    """Application-level (non-CRUD) commands: version and config diagnostics."""

    def __init__(self, prompt: PromptService, diagnostic_util: DiagnosticUtil) -> None:
        self.prompt = prompt
        self.diagnostic_util = diagnostic_util

    def version(self) -> None:
        """Show application version."""
        self.prompt.print(f"MonitorHub version: ({VERSION_STRING})")

    def config_test(self) -> None:
        """Test configuration."""
        try:
            diagnostic_util = self.diagnostic_util
            if not diagnostic_util.check_app_env():
                return
            diagnostic_util.check_profile_import()
            if not diagnostic_util.check_rclone_dependency():
                return
            if not diagnostic_util.check_monitor_config():
                return
            diagnostic_util.print_overview()
        finally:
            self.prompt.print("Exiting test mode now")


@dataclass
class Commands:
    """Bundle of wired command handlers plus their shared dependencies."""

    database: DatabaseCommands
    profile: ProfileCommands
    monitor: MonitorCommands
    app: AppCommands
    prompt: PromptService
    diagnostic_util: DiagnosticUtil
    sqlite_handler: SQLiteHandler


def build_commands(
    logger: logging.Logger,
    db_dir: str,
    log_config: str = "conf/log.yaml",
    log_level: str | None = None,
    prompt: PromptService | None = None,
    diagnostic_util: DiagnosticUtil | None = None,
    sqlite_handler: SQLiteHandler | None = None,
) -> Commands:
    """Silence noisy logs and wire together all CLI command handlers.

    ``prompt``, ``diagnostic_util``, and ``sqlite_handler`` are injectable so
    tests can substitute fakes/mocks without touching the database or the
    filesystem.
    """
    # Filter logging to avoid noise on the console
    logger.setLevel(logging.WARNING)
    logger.propagate = False

    # Silence boto3 and other libraries
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    prompt = prompt or PromptService()
    sqlite_handler = sqlite_handler or SQLiteHandler(logger=logger, db_dir=db_dir)
    diagnostic_util = diagnostic_util or DiagnosticUtil(
        sqlite_handler=sqlite_handler,
        logger=logger,
        prompt=prompt,
    )

    database = DatabaseCommands(sqlite_handler, prompt)
    profile = ProfileCommands(sqlite_handler, logger, diagnostic_util, prompt)
    monitor = MonitorCommands(
        sqlite_handler,
        logger,
        db_dir,
        log_config,
        log_level,
        prompt,
    )
    app = AppCommands(prompt, diagnostic_util)

    return Commands(
        database=database,
        profile=profile,
        monitor=monitor,
        app=app,
        prompt=prompt,
        diagnostic_util=diagnostic_util,
        sqlite_handler=sqlite_handler,
    )