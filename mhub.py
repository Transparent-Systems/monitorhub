"""
Script: mhub.py
Version: v1.1.0
Author: John Zoetebier
Description:
    MonitorHub CLI — command-line interface for managing profiles,
    monitors, configuration, and diagnostics. The 'webgui' subcommand
    launches the Streamlit web interface (same feature set, browser UI).
Requirements:
    1) Python (version pinned in .python-version; run 'mhub config python')
    2) Python modules in requirements.txt
Usage:
    Run the following command to get help:
    python mhub.py -h
Notes:
    See: README.md for more details.
"""

import argparse
import importlib
import sqlite3
import sys

from app.cli.commands import build_commands
from app.cli.db_error_messages import integrity_error_message
from app.utils.app_config import AppConfig
from app.utils.logger_setup import setup_logging
from app.utils.project_paths import project_conf

# Data-driven mapping of (command, subcommand) to the command object attribute
# and method to invoke, together with a callable that builds the keyword
# arguments from the parsed argparse namespace. This replaces the previous
# hand-written if/elif dispatch tree.
_SUBCOMMAND_DISPATCH = {
    ("version", None): ("app", "version", lambda _: {}),
    ("config", "test"): ("app", "config_test", lambda _: {}),
    ("config", "python"): ("app", "config_python", lambda _: {}),
    ("profile", "test"): (
        "profile",
        "test",
        lambda args: {
            "profile_id": getattr(args, "profile_id", None),
            "profile_name": getattr(args, "profile_name", None),
            "live": getattr(args, "live", False),
        },
    ),
    ("profile", "show"): (
        "profile",
        "show",
        lambda args: {
            "profile_id": getattr(args, "profile_id", None),
            "profile_name": getattr(args, "profile_name", None),
        },
    ),
    ("profile", "new"): ("profile", "new", lambda _: {}),
    ("profile", "edit"): (
        "profile",
        "edit",
        lambda args: {
            "profile_id": getattr(args, "profile_id", None),
            "profile_name": getattr(args, "profile_name", None),
        },
    ),
    ("profile", "delete"): (
        "profile",
        "delete",
        lambda args: {
            "profile_id": getattr(args, "profile_id", None),
            "profile_name": getattr(args, "profile_name", None),
        },
    ),
    ("profile", "import"): ("profile", "import_profiles", lambda _: {}),
    ("monitor", "delete"): (
        "monitor",
        "delete",
        lambda args: {
            "monitor_id": getattr(args, "monitor_id", None),
            "monitor_name": getattr(args, "monitor_name", None),
        },
    ),
    ("monitor", "clone"): (
        "monitor",
        "clone",
        lambda args: {
            "monitor_id": getattr(args, "monitor_id", None),
            "monitor_name": getattr(args, "monitor_name", None),
        },
    ),
    ("monitor", "edit"): (
        "monitor",
        "edit",
        lambda args: {
            "monitor_id": getattr(args, "monitor_id", None),
            "monitor_name": getattr(args, "monitor_name", None),
        },
    ),
    ("monitor", "new"): ("monitor", "new", lambda _: {}),
    ("monitor", "show"): (
        "monitor",
        "show",
        lambda args: {
            "monitor_id": getattr(args, "monitor_id", None),
            "monitor_name": getattr(args, "monitor_name", None),
        },
    ),
    ("monitor", "start"): (
        "monitor",
        "start",
        lambda args: {
            "monitor_id": getattr(args, "monitor_id", None),
            "monitor_name": getattr(args, "monitor_name", None),
        },
    ),
    ("monitor", "test"): (
        "monitor",
        "test",
        lambda args: {
            "monitor_id": getattr(args, "monitor_id", None),
            "monitor_name": getattr(args, "monitor_name", None),
        },
    ),
    ("monitor", "stop"): (
        "monitor",
        "stop",
        lambda args: {
            "monitor_id": getattr(args, "monitor_id", None),
            "immediate": args.immediate,
            "monitor_name": getattr(args, "monitor_name", None),
        },
    ),
    ("database", "info"): ("database", "info", lambda _: {}),
    ("database", "version"): ("database", "version", lambda _: {}),
    ("database", "init"): ("database", "init", lambda args: {"recreate": args.recreate}),
    ("database", "upgrade"): ("database", "upgrade", lambda _: {}),
    ("database", "sample-data"): ("database", "sample_data", lambda _: {}),
}


def _add_selector_args(
    parser: argparse.ArgumentParser,
    target: str,
    verb: str,
    omit_hint: str,
) -> None:
    """Add the shared ``-i/--<target>-id`` and ``-n/--<target>-name`` arguments.

    Every profile/monitor subcommand selects its target the same way; only the
    verb and the parenthetical hint differ. Centralising the definition keeps
    the flag names, types and metavars consistent across all subcommands.
    """
    parser.add_argument(
        "-i", f"--{target}-id",
        type=int,
        metavar="<ID>",
        help=f"ID of the {target} to {verb} ({omit_hint})",
    )
    parser.add_argument(
        "-n", f"--{target}-name",
        type=str,
        metavar="<NAME>",
        help=f"Name of the {target} to {verb} ({omit_hint})",
    )


def build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    """Build the MonitorHub argument parser.

    Returns the parser together with the mapping of top-level command name to
    its subcommand parser, which is used to print the right help text when no
    (or an unknown) subcommand is supplied.

    Kept separate from :func:`main` so other entry points - notably the frozen
    ``mhub-gui`` binary, which runs the CLI in-process - reuse this exact
    command surface instead of duplicating it.
    """
    parser = argparse.ArgumentParser(
        description="MonitorHub CLI for managing profiles, monitors, and configuration."
    )
    # Argument for location of the SQLite database
    parser.add_argument(
        "-d", "--db-dir",
        type=str,
        default=None,
        metavar="<PATH>",
        help=(
            "Directory of SQLite database (defaults to the 'default_database' setting in "
            "conf/config.yaml or 'data'; relative paths in the config resolve against the "
            "application folder)"
        )
    )

    # Argument for location of the log file
    parser.add_argument(
        "-l", "--log",
        type=str,
        default=None,
        metavar="<PATH>",
        help=(
            "Path to the logging configuration YAML (default: conf/log.yaml beside the "
            "application; relative folder/file_name values in the config resolve against "
            "the application folder)"
        )
    )

    # Argument to override the configured log level
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override the log level from the configuration file",
    )

    # Argument to override the log level of third-party libraries
    parser.add_argument(
        "--dependency-log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=(
            "Override the log level of the third-party libraries "
            "(boto3/botocore/s3transfer/urllib3); defaults to WARNING"
        ),
    )

    # Add subcommands
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Version command
    subparsers.add_parser("version", help="Show version")

    # Web GUI command (Streamlit; requires the Streamlit dependency)
    subparsers.add_parser("webgui", help="Launch the Streamlit web GUI")

    # Config command
    config_parser = subparsers.add_parser("config", help="Configuration commands (subcommands: test, python; enter 'config -h' for help)")
    config_subparsers = config_parser.add_subparsers(dest="config_subcommand", help="Config subcommands")
    config_subparsers.add_parser("test", help="Run environment and configuration checks")
    config_subparsers.add_parser(
        "python",
        help="Show the Python version in use and the project's pinned version",
    )

    # Profile command
    profile_parser = subparsers.add_parser("profile", help="Manage profiles (subcommands: show, new, ... ; enter 'profile -h' for help)")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_subcommand", help="Profile subcommands")

    # Profile subcommands
    profile_show_parser = profile_subparsers.add_parser("show", help="Show all profiles")
    _add_selector_args(profile_show_parser, "profile", "show", "omit to show all profiles")
    profile_subparsers.add_parser("import", help="Import profiles from rclone")
    profile_subparsers.add_parser("new", help="Create a new profile (select profile category interactively)")
    profile_edit_parser = profile_subparsers.add_parser("edit", help="Edit a profile")
    _add_selector_args(profile_edit_parser, "profile", "edit", "omit to select interactively")
    profile_delete_parser = profile_subparsers.add_parser("delete", help="Delete a profile")
    _add_selector_args(profile_delete_parser, "profile", "delete", "omit to select interactively")
    profile_test_parser = profile_subparsers.add_parser("test", help="Test a profile")
    _add_selector_args(profile_test_parser, "profile", "test", "omit to select interactively")
    profile_test_parser.add_argument("--live",
        action="store_true",
        default=False,
        help="Execute the command with sample values instead of dry-run only"
        )


    database_parser = subparsers.add_parser("database", help="Database information")
    database_subparsers = database_parser.add_subparsers(dest="database_subcommand", help="Database subcommands")
    database_subparsers.add_parser("info", help="Show database information")
    database_subparsers.add_parser("version", help="Show database version")
    database_init_parser = database_subparsers.add_parser("init", help="Initialise the database schema and load support tables")
    database_init_parser.add_argument("--recreate",
        action="store_true",
        default=False,
        help="Drop the existing schema and recreate it from scratch"
    )
    database_subparsers.add_parser(
        "upgrade",
        help="Apply pending schema migrations to bring the database up to date",
    )
    database_subparsers.add_parser(
        "sample-data",
        help="Load example profile and monitor sample data"
    )

    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Manage monitors (subcommands: show, stop, ... ; enter 'monitor -h' for help)")
    monitor_subparsers = monitor_parser.add_subparsers(dest="monitor_subcommand", help="Monitor subcommands")

    monitor_subparsers.add_parser("new", help="Create a new monitor")
    monitor_edit_parser = monitor_subparsers.add_parser("edit", help="Edit a monitor")
    _add_selector_args(monitor_edit_parser, "monitor", "edit", "omit to select interactively")
    monitor_delete_parser = monitor_subparsers.add_parser("delete", help="Delete a monitor")
    _add_selector_args(monitor_delete_parser, "monitor", "delete", "omit to select interactively")
    monitor_clone_parser = monitor_subparsers.add_parser("clone", help="Clone a monitor")
    _add_selector_args(monitor_clone_parser, "monitor", "clone", "omit to select interactively")
    monitor_show_parser = monitor_subparsers.add_parser("show", help="Show all monitors")
    _add_selector_args(monitor_show_parser, "monitor", "show", "omit to show all monitors")
    monitor_start_parser = monitor_subparsers.add_parser("start", help="Start a monitor")
    _add_selector_args(monitor_start_parser, "monitor", "start", "omit to start all monitors")
    monitor_test_parser = monitor_subparsers.add_parser("test", help="Test a monitor")
    _add_selector_args(monitor_test_parser, "monitor", "test", "omit to select interactively")
    monitor_stop_parser = monitor_subparsers.add_parser("stop", help="Stop a running monitor")
    _add_selector_args(monitor_stop_parser, "monitor", "stop", "omit to stop all monitors")
    monitor_stop_parser.add_argument("--immediate",
        action="store_true",
        default=False,
        help="Force kill the monitor process immediately instead of graceful shutdown"
    )

    # Map top-level command names to their subcommand parser, used to print the
    # correct help text when no (or an unknown) subcommand is supplied.
    command_parsers = {
        "profile": profile_parser,
        "monitor": monitor_parser,
        "database": database_parser,
        "config": config_parser,
    }

    return parser, command_parsers


def _run_webgui(db_dir: str | None) -> int:
    """Launch the Streamlit web GUI for the ``webgui`` subcommand.

    The import is dynamic on purpose. A static ``from app.webgui.launcher
    import main`` makes PyInstaller bundle the whole Streamlit stack (its 23 MB
    frontend bundle, pandas, pyarrow, altair, ...) into the CLI binary, which
    has no use for it: the CLI artifact would grow from ~30 MB to ~120 MB.

    The GUI binary (``mhub-gui``) bundles the launcher, so the command works
    there. The small CLI build reports that the GUI is unavailable instead.
    """
    try:
        launcher = importlib.import_module("app.webgui.launcher")
    except ImportError:
        print(
            "ERROR: the web GUI is not included in this build.\n"
            "Use the 'mhub-gui' executable, or run the web GUI from a source\n"
            "checkout with: python mhub.py webgui",
            file=sys.stderr,
        )
        return 1
    return launcher.main(db_dir=db_dir)


def main(argv: list[str] | None = None) -> int:
    """Run the MonitorHub CLI and return the process exit code."""
    argv = sys.argv[1:] if argv is None else list(argv)

    # Hidden in-process dispatch used by the frozen PyInstaller binary.
    # When the binary re-invokes itself to start a monitor child process it
    # passes `run-monitor` as the first argument. Run the monitor logic
    # directly (rather than invoking `python app/monitor/run_monitor.py`) so it
    # works inside the bundled executable.
    if argv and argv[0] == "run-monitor":
        from app.monitor.run_monitor import run_monitor_main
        return run_monitor_main(argv[1:])

    parser, command_parsers = build_parser()
    args = parser.parse_args(argv)

    # `webgui` boots the Streamlit server, which resolves its own configuration,
    # database and logging. Dispatch it before the logging/database wiring below
    # so it also works on a machine where the database has not been initialised
    # yet (the GUI pages report an empty/uninitialised database themselves).
    # An explicit -d/--db-dir is forwarded so `mhub -d <path> webgui` opens that
    # database in the GUI.
    if args.command == "webgui":
        return _run_webgui(args.db_dir)

    # Default the log configuration to the project's conf/ folder so it works
    # from any working directory; an explicit -l/--log value is kept verbatim.
    if args.log is None:
        args.log = str(project_conf("log.yaml"))

    # Configure logging (reads YAML config, sets up root logger handlers)
    logger, log_config = setup_logging(
        args.log,
        log_level=args.log_level,
        dependency_log_level=args.dependency_log_level,
    )

    # Resolve db_dir from argument or config file fallback
    if args.db_dir is None:
        app_config = AppConfig(logger=logger)
        db_dir = app_config.get_default_db_dir(fallback="data")
    else:
        db_dir = args.db_dir

    # Handle command line arguments via a data-driven dispatch table.
    if args.command is not None:
        commands = None
        try:
            commands = build_commands(
                logger=logger,
                db_dir=db_dir,
                log_config=args.log,
                log_level=args.log_level,
                dependency_log_level=args.dependency_log_level,
            )
            subcommand = getattr(args, f"{args.command}_subcommand", None)
            entry = _SUBCOMMAND_DISPATCH.get((args.command, subcommand))
            if entry is None:
                command_parsers.get(args.command, parser).print_help()
                return 1
            owner_attr, method_name, kwargs_builder = entry
            command_obj = getattr(commands, owner_attr)
            kwargs = kwargs_builder(args)
            getattr(command_obj, method_name)(**kwargs)
        except sqlite3.IntegrityError as error:
            # A constraint violation is a data problem, not a broken database:
            # report it without the "is the database initialised?" hint.
            logger.error(f"Database constraint error: {error}")
            print(integrity_error_message(error), file=sys.stderr)
            return 1
        except sqlite3.Error as error:
            logger.error(f"Database error: {error}")
            print(
                f"Database error: {error}\n"
                f"Is the database at '{db_dir}' initialised? "
                "Create it with: python mhub.py database init",
                file=sys.stderr,
            )
            return 1
        finally:
            # Deterministically return the database connection before the
            # process exits (sys.exit in the except branches still passes
            # through this block). SQLiteHandler's weakref.finalize remains a
            # safety net for paths that never reach here (e.g. a hard crash).
            if commands is not None:
                commands.sqlite_handler.close()
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())