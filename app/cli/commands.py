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

from app.cli.database_commands import DatabaseCommands
from app.cli.diagnostic_util import DiagnosticUtil
from app.cli.monitor_commands import MonitorCommands
from app.cli.profile_commands import ProfileCommands
from app.cli.prompt_service import PromptService
from app.utils.sqlite_handler import SQLiteHandler
from version import VERSION_STRING


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
    dependency_log_level: str | None = None,
    prompt: PromptService | None = None,
    diagnostic_util: DiagnosticUtil | None = None,
    sqlite_handler: SQLiteHandler | None = None,
) -> Commands:
    """Wire together all CLI command handlers into a :class:`Commands` bundle.

    ``prompt``, ``diagnostic_util``, and ``sqlite_handler`` are injectable so
    tests can substitute fakes/mocks without touching the database or the
    filesystem.

    This factory has no log side effects: console-policy (silencing
    ``boto3``/``botocore``/``s3transfer``/``urllib3``) is owned by
    ``app.utils.logger_setup.setup_logging`` and gated by its
    ``quiet_dependencies``/``dependency_log_level`` parameters, so the log
    levels requested on the command line (``--log-level``,
    ``--dependency-log-level``) reach the ``MonitorHub`` logger and are
    forwarded to monitor child processes.
    """
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
        dependency_log_level,
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