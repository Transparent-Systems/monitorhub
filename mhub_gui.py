"""
Script: mhub_gui.py
Version: v1.3.0
Author: John Zoetebier
Description:
    Entry point for the MonitorHub GUI binary (``mhub-gui``).

    The binary is self-contained and serves three roles:

    1. No arguments: launch the Streamlit web GUI on http://127.0.0.1:8501.
       ``-d/--db-dir`` selects the database the GUI opens.
    2. A CLI command (version, config, profile, monitor, database): run the
       MonitorHub CLI in-process, so the GUI download can also initialise and
       manage the database. Every CLI option works here, including -l/--log.
    3. ``run-monitor``: behave as a monitor child process. The GUI's
       MonitorProcessManager re-executes ``sys.executable`` this way when it is
       frozen, so running monitors needs no separate Python installation.
Requirements:
    1) Python (version pinned in .python-version; run 'mhub config python')
    2) Python modules in requirements.txt
Usage:
    mhub-gui                      # start the web GUI
    mhub-gui -d /path/to/data     # start the web GUI on a specific database
    mhub-gui database init        # CLI: initialise the database
    mhub-gui monitor start        # CLI: start every monitor
    mhub-gui --help               # CLI help
Notes:
    See: README.md for more details.
"""

from __future__ import annotations

import sys

# Top-level CLI commands of the shared parser (mhub.build_parser). A first
# positional in this set means "run the CLI"; anything else means "start the
# GUI" (and is forwarded to Streamlit, so --server.port=8600 still works).
CLI_COMMANDS = frozenset(
    {"version", "webgui", "config", "profile", "monitor", "database"}
)

# Global CLI options that take a value. The scanner below must skip their value
# so that, for example, `mhub-gui -d /tmp/db monitor show` still finds the
# `monitor` command. tests/test_mhub_gui.py keeps this set in sync with the
# parser.
VALUE_OPTIONS = frozenset(
    {"-d", "--db-dir", "-l", "--log", "--log-level", "--dependency-log-level"}
)

# CLI-only options: the GUI takes just -d/--db-dir and reads its logging
# configuration from conf/log.yaml beside the executable.
CLI_ONLY_OPTIONS = ("-l", "--log", "--log-level", "--dependency-log-level")


def _first_command(argv: list[str]) -> str | None:
    """Return the first positional argument, skipping options and their values."""
    skip_value = False
    for token in argv:
        if skip_value:
            skip_value = False
            continue
        if token in VALUE_OPTIONS:
            skip_value = True
            continue
        if token.startswith("-"):
            continue
        return token
    return None


def _print_help() -> int:
    """Print the CLI help plus a note about the GUI's default behaviour."""
    import mhub

    parser, _ = mhub.build_parser()
    parser.print_help()
    print(
        "\nRunning mhub-gui without arguments starts the Streamlit web GUI on\n"
        "http://127.0.0.1:8501. Use -d/--db-dir to select the database:\n"
        "  mhub-gui -d /path/to/data\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the web GUI, a CLI command, or a monitor child."""
    argv = sys.argv[1:] if argv is None else list(argv)

    # Hidden in-process dispatch used by the frozen PyInstaller binary. When the
    # binary re-invokes itself to start a monitor child it passes `run-monitor`
    # as the first argument (see MonitorProcessManager.launch). Handled before
    # anything else so a monitor child never pays the GUI/CLI import cost.
    if argv and argv[0] == "run-monitor":
        from app.monitor.run_monitor import run_monitor_main
        return run_monitor_main(argv[1:])

    if argv and argv[0] in ("-h", "--help"):
        return _print_help()

    command = _first_command(argv)
    if command is not None and command in CLI_COMMANDS:
        # Full CLI: it validates and reports its own argument errors.
        import mhub

        return mhub.main(argv)

    # Everything else starts the GUI. Only -d/--db-dir is interpreted; the rest
    # of the command line is handed to Streamlit untouched.
    unsupported = sorted(
        {token.split("=", 1)[0] for token in argv} & set(CLI_ONLY_OPTIONS)
    )
    if unsupported:
        print(
            "ERROR: only CLI commands accept "
            f"{', '.join(unsupported)}.\n"
            "The web GUI reads its logging configuration from conf/log.yaml "
            "beside the executable.\n"
            "Use a CLI command instead, e.g. 'mhub-gui monitor start'.",
            file=sys.stderr,
        )
        return 2

    import argparse

    from app.webgui.launcher import main as launcher_main

    gui_parser = argparse.ArgumentParser(add_help=False)
    gui_parser.add_argument("-d", "--db-dir")
    gui_args, streamlit_args = gui_parser.parse_known_args(argv)
    return launcher_main(streamlit_args, db_dir=gui_args.db_dir)


if __name__ == "__main__":
    sys.exit(main())
