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

from app.cli import python_version
from app.cli.database_commands import DatabaseCommands
from app.cli.diagnostic_util import DiagnosticUtil
from app.cli.monitor_commands import MonitorCommands
from app.cli.profile_commands import ProfileCommands
from app.cli.profile_importer import ProfileImporter
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

    def config_python(self) -> None:
        """Report the running Python version and the project's declared pin.

        The runtime version comes from the interpreter actually executing (which
        works inside the frozen executable too). The declared pin is read from
        ``.python-version`` when a source checkout provides it, and is reported
        as unavailable otherwise. This is an advisory report, not a gate: it
        always completes without signalling failure.
        """
        runtime = python_version.runtime_python_version()
        self.prompt.print(f"Python (runtime) : {runtime}")
        self.prompt.print(f"Executable       : {python_version.runtime_executable()}")

        pin_file = python_version.find_pin_file()
        if pin_file is None:
            self.prompt.print(
                f"Declared pin     : not available "
                f"(no {python_version.PIN_FILENAME} found)"
            )
            self.prompt.print("Status           : n/a")
            return

        pin = python_version.read_pinned_version(pin_file)
        if pin is None:
            self.prompt.print(f"Declared pin     : unreadable ({pin_file})")
            self.prompt.print("Status           : n/a")
            return

        self.prompt.print(f"Declared pin     : {pin}  (from {pin_file})")
        if python_version.pin_matches(pin, runtime):
            self.prompt.print("Status           : OK - runtime matches the declared pin")
        else:
            self.prompt.print(
                f"Status           : MISMATCH - runtime {runtime} "
                f"does not match pin {pin}"
            )


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
    profile_importer: ProfileImporter


def build_commands(
    logger: logging.Logger,
    db_dir: str,
    log_config: str = "conf/log.yaml",
    log_level: str | None = None,
    dependency_log_level: str | None = None,
    prompt: PromptService | None = None,
    diagnostic_util: DiagnosticUtil | None = None,
    sqlite_handler: SQLiteHandler | None = None,
    profile_importer: ProfileImporter | None = None,
) -> Commands:
    """Wire together all CLI command handlers into a :class:`Commands` bundle.

    ``prompt``, ``diagnostic_util``, ``sqlite_handler``, and
    ``profile_importer`` are injectable so tests can substitute fakes/mocks
    without touching the database or the filesystem.

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
    # One importer instance is shared by the diagnostic check and the CLI import
    # action, so both see the same rclone.conf reading/folding rules.
    profile_importer = profile_importer or ProfileImporter(
        sqlite_handler=sqlite_handler,
        logger=logger,
        prompt=prompt,
    )
    diagnostic_util = diagnostic_util or DiagnosticUtil(
        sqlite_handler=sqlite_handler,
        profile_importer=profile_importer,
        logger=logger,
        prompt=prompt,
    )

    database = DatabaseCommands(sqlite_handler, prompt)
    profile = ProfileCommands(sqlite_handler, logger, profile_importer, prompt)
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
        profile_importer=profile_importer,
    )