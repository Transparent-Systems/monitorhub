"""
Script: mhub.py
Version: v1.0.0
Author: John Zoetebier
Description:
    MonitorHub CLI — command-line interface for managing profiles,
    monitors, configuration, and diagnostics.
Requirements:
    1) Python 3.13.0 (https://www.python.org/downloads/)
    2) Python modules in requirements.txt
Usage:
    Run the following command to get help:
    python mhub.py -h
Notes:
    See: README.md for more details.
"""

import argparse
import sys

from scripts.commands import build_commands
from scripts.utils.app_config import AppConfig
from scripts.utils.logger_setup import setup_logging

# Data-driven mapping of (command, subcommand) to the command object attribute
# and method to invoke, together with a callable that builds the keyword
# arguments from the parsed argparse namespace. This replaces the previous
# hand-written if/elif dispatch tree.
_SUBCOMMAND_DISPATCH = {
    ("version", None): ("app", "version", lambda _: {}),
    ("config", "test"): ("app", "config_test", lambda _: {}),
    ("profile", "test"): (
        "profile",
        "test",
        lambda args: {"profile_id": args.profile_id, "live": args.live},
    ),
    ("profile", "show"): ("profile", "show", lambda _: {}),
    ("profile", "new"): ("profile", "new", lambda _: {}),
    ("profile", "edit"): ("profile", "edit", lambda _: {}),
    ("profile", "delete"): ("profile", "delete", lambda _: {}),
    ("profile", "import"): ("profile", "import_profiles", lambda _: {}),
    ("monitor", "delete"): ("monitor", "delete", lambda _: {}),
    ("monitor", "edit"): ("monitor", "edit", lambda _: {}),
    ("monitor", "new"): ("monitor", "new", lambda _: {}),
    ("monitor", "show"): ("monitor", "show", lambda _: {}),
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
    ("monitor", "start-all"): ("monitor", "start_all", lambda _: {}),
    ("monitor", "stop"): (
        "monitor",
        "stop",
        lambda args: {
            "monitor_id": getattr(args, "monitor_id", None),
            "immediate": args.immediate,
            "monitor_name": getattr(args, "monitor_name", None),
        },
    ),
    ("monitor", "stop-all"): ("monitor", "stop_all", lambda args: {"immediate": args.immediate}),
    ("database", "info"): ("database", "info", lambda _: {}),
    ("database", "version"): ("database", "version", lambda _: {}),
    ("database", "init"): ("database", "init", lambda args: {"recreate": args.recreate}),
    ("database", "sample-data"): ("database", "sample_data", lambda _: {}),
}

if __name__ == "__main__":
    # Hidden in-process dispatch used by the frozen PyInstaller binary.
    # When the binary re-invokes itself to start a monitor child process it
    # passes `run-monitor` as the first argument. Run the monitor logic
    # directly (rather than invoking `python scripts/run_monitor.py`) so it
    # works inside the bundled executable.
    if len(sys.argv) > 1 and sys.argv[1] == "run-monitor":
        sys.argv.pop(1)
        from scripts.run_monitor import run_monitor_main
        run_monitor_main()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="MonitorHub CLI for managing profiles, monitors, and configuration."
    )
    # Argument for location of the SQLite database
    parser.add_argument(
        "-d", "--db-dir",
        type=str,
        default=None,
        metavar="<PATH>",
        help="Directory of SQLite database (defaults to ~/.config/monitorhub/config.yaml setting or 'data')"
    )

    # Argument for location of the log file
    parser.add_argument(
        "-l", "--log",
        type=str,
        default="conf/log.yaml",
        metavar="<PATH>",
        help="Path to the log file"
    )

    # Argument to override the configured log level
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override the log level from the configuration file",
    )

    # Add subcommands
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Version command
    subparsers.add_parser("version", help="Show version")

    # Config command
    config_parser = subparsers.add_parser("config", help="Configuration commands (subcommands: test; enter 'config -h' for help)")
    config_subparsers = config_parser.add_subparsers(dest="config_subcommand", help="Config subcommands")
    config_test_parser = config_subparsers.add_parser("test", help="Run environment and configuration checks")

    # Profile command
    profile_parser = subparsers.add_parser("profile", help="Manage profiles (subcommands: show, new, ... ; enter 'profile -h' for help)")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_subcommand", help="Profile subcommands")

    # Profile subcommands
    profile_subparsers.add_parser("show", help="Show all profiles")
    profile_subparsers.add_parser("file", help="Show the file location of monitorhub.conf")
    profile_subparsers.add_parser("import", help="Import profiles from rclone")
    profile_new_parser = profile_subparsers.add_parser("new", help="Create a new profile (select profile category interactively)")
    profile_subparsers.add_parser("edit", help="Edit a profile")
    profile_subparsers.add_parser("delete", help="Delete a profile")
    profile_test_parser = profile_subparsers.add_parser("test", help="Test a profile")
    profile_test_parser.add_argument("-p", "--profile-id",
        type=str,
        metavar="<ID>",
        help="Profile ID of remote profile to test"
        )
    profile_test_parser.add_argument("--live",
        action="store_true",
        default=False,
        help="Execute the command with sample values instead of dry-run only"
        )


    database_parser = subparsers.add_parser("database", help="Database information")
    database_subparsers = database_parser.add_subparsers(dest="database_subcommand", help="Database subcommands")
    database_info_parser = database_subparsers.add_parser("info", help="Show database information")
    database_version_parser = database_subparsers.add_parser("version", help="Show database version")
    database_init_parser = database_subparsers.add_parser("init", help="Initialise the database schema and load support tables")
    database_init_parser.add_argument("--recreate",
        action="store_true",
        default=False,
        help="Drop the existing schema and recreate it from scratch"
    )
    database_sample_data_parser = database_subparsers.add_parser(
        "sample-data",
        help="Load example profile and monitor sample data"
    )

    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Manage monitors (subcommands: show, stop, ... ; enter 'monitor -h' for help)")
    monitor_subparsers = monitor_parser.add_subparsers(dest="monitor_subcommand", help="Monitor subcommands")

    monitor_new_parser = monitor_subparsers.add_parser("new", help="Create a new monitor")
    monitor_edit_parser = monitor_subparsers.add_parser("edit", help="Edit a monitor")
    monitor_delete_parser = monitor_subparsers.add_parser("delete", help="Delete a monitor")
    monitor_show_parser = monitor_subparsers.add_parser("show", help="Show all monitors")
    monitor_start_parser = monitor_subparsers.add_parser("start", help="Start a monitor")
    monitor_start_parser.add_argument("-m", "--monitor-id",
        type=int,
        metavar="<ID>",
        help="ID of the monitor to start (omit to select interactively)"
    )
    monitor_start_parser.add_argument("-n", "--monitor-name",
        type=str,
        metavar="<NAME>",
        help="Name of the monitor to start (omit to select interactively)"
    )
    monitor_test_parser = monitor_subparsers.add_parser("test", help="Test a monitor")
    monitor_test_parser.add_argument("-m", "--monitor-id",
        type=int,
        metavar="<ID>",
        help="ID of the monitor to test (omit to select interactively)"
    )
    monitor_test_parser.add_argument("-n", "--monitor-name",
        type=str,
        metavar="<NAME>",
        help="Name of the monitor to test (omit to select interactively)"
    )
    monitor_stop_parser = monitor_subparsers.add_parser("stop", help="Stop a running monitor")
    monitor_stop_parser.add_argument("-m", "--monitor-id",
        type=int,
        metavar="<ID>",
        help="ID of the monitor to stop (omit to select interactively)"
    )
    monitor_stop_parser.add_argument("-n", "--monitor-name",
        type=str,
        metavar="<NAME>",
        help="Name of the monitor to stop (omit to select interactively)"
    )
    monitor_stop_parser.add_argument("-i", "--immediate",
        action="store_true",
        default=False,
        help="Force kill the monitor process immediately instead of graceful shutdown"
    )

    monitor_start_all_parser = monitor_subparsers.add_parser("start-all", help="Clean up stale monitors and start all monitors that are not running")

    monitor_stop_all_parser = monitor_subparsers.add_parser("stop-all", help="Stop all running monitors")
    monitor_stop_all_parser.add_argument("-i", "--immediate",
        action="store_true",
        default=False,
        help="Force kill all monitor processes immediately instead of graceful shutdown"
    )

    args = parser.parse_args()

    # Configure logging (reads YAML config, sets up root logger handlers)
    logger, log_config = setup_logging(args.log, log_level=args.log_level)

    # Resolve db_dir from argument or config file fallback
    if args.db_dir is None:
        app_config = AppConfig(logger=logger)
        db_dir = app_config.get_default_db_dir(fallback="data")
    else:
        db_dir = args.db_dir

    # Map top-level command names to their subcommand parser, used to print the
    # correct help text when no (or an unknown) subcommand is supplied.
    command_parsers = {
        "profile": profile_parser,
        "monitor": monitor_parser,
        "database": database_parser,
        "config": config_parser,
    }

    # Handle command line arguments via a data-driven dispatch table.
    if args.command is not None:
        commands = build_commands(
            logger=logger,
            db_dir=db_dir,
            log_config=args.log,
            log_level=args.log_level,
        )
        subcommand = getattr(args, f"{args.command}_subcommand", None)
        entry = _SUBCOMMAND_DISPATCH.get((args.command, subcommand))
        if entry is None:
            command_parsers.get(args.command, parser).print_help()
            sys.exit(1)
        owner_attr, method_name, kwargs_builder = entry
        command_obj = getattr(commands, owner_attr)
        kwargs = kwargs_builder(args)
        getattr(command_obj, method_name)(**kwargs)
    else:
        parser.print_help()
        sys.exit(1)