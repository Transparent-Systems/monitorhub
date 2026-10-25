"""Launch the MonitorHub Streamlit web GUI.

One place knows how to boot the Streamlit server, shared by the ``mhub webgui``
CLI subcommand and the frozen ``mhub-gui`` PyInstaller entry point.  Keeping it
here means the frozen binary and a source checkout start the GUI with exactly
the same script, port and flags.

Usage::

    .venv/bin/python mhub.py webgui            # source
    .venv/bin/python mhub.py -d data webgui    # source, explicit database
    ./dist/mhub-gui                            # frozen (PyInstaller)
    ./dist/mhub-gui -d /path/to/db             # frozen, explicit database
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.utils.app_config import DB_DIR_ENV_VAR
from app.utils.project_paths import resource_root

# The Streamlit main script, relative to the resource root. Streamlit discovers
# the sidebar pages from the ``pages/`` folder next to it.
WEBGUI_SCRIPT = Path("app") / "webgui" / "home.py"

# Flags applied to every launch, before any user-supplied arguments:
# - developmentMode off: Streamlit defaults it to True whenever its own
#   ``config.py`` is not inside a ``site-packages`` folder, which is exactly the
#   case inside a PyInstaller bundle. Dev mode refuses an explicit
#   ``server.port`` ("server.port does not work when global.developmentMode is
#   true") and enables frontend-development behaviour we never want.
# - loopback only, fixed port (the health endpoint is /_stcore/health);
# - headless: no first-run "enter your email" prompt, no browser auto-open;
# - file watcher off: there is nothing to hot-reload in a frozen bundle;
# - no usage telemetry.
DEFAULT_FLAGS = (
    "--global.developmentMode=false",
    "--server.address=127.0.0.1",
    "--server.port=8501",
    "--server.headless=true",
    "--server.fileWatcherType=none",
    "--browser.gatherUsageStats=false",
)


def script_path() -> Path:
    """Absolute path of the Streamlit main script for this deployment."""
    return resource_root() / WEBGUI_SCRIPT


def main(argv: list[str] | None = None, db_dir: str | None = None) -> int:
    """Start the web GUI; return a process exit code on failure.

    ``argv`` (default ``sys.argv[1:]``) is appended after the default flags, so
    callers can still override e.g. the port.  ``db_dir`` selects the database
    the pages open; when omitted they resolve it from ``conf/config.yaml``
    beside the executable, falling back to ``data``.
    """
    if db_dir:
        # The Streamlit pages run in this process, but they resolve their
        # database through AppConfig. Exporting the value is how -d/--db-dir
        # reaches them without threading it through every page.
        os.environ[DB_DIR_ENV_VAR] = db_dir

    script = script_path()
    if not script.is_file():
        print(
            f"ERROR: web GUI entry point not found at '{script}'.",
            file=sys.stderr,
        )
        return 1

    try:
        # Imported lazily: the small `mhub` CLI build does not bundle Streamlit,
        # and `mhub --help` must not pay (or fail on) the import.
        from streamlit.web import cli as streamlit_cli
    except ImportError:
        print(
            "ERROR: the Streamlit web GUI is not available in this build.\n"
            "Use the 'mhub-gui' executable, or run the web GUI from a source\n"
            "checkout with: python mhub.py webgui",
            file=sys.stderr,
        )
        return 1

    # Streamlit's CLI is a click group that reads sys.argv and derives its
    # program name from sys.argv[0], so build a clean argument vector. Passing
    # the group (rather than the `run` command) keeps its built-in argument
    # checks working.
    sys.argv = ["streamlit", "run", str(script), *DEFAULT_FLAGS, *(argv or [])]
    streamlit_cli.main()  # raises SystemExit via click's standalone mode
    return 0


if __name__ == "__main__":
    sys.exit(main())
