"""
Diagnostics runner for MonitorHub.

Runs DiagnosticUtil checks against the project database. This is a manual
script, not a unittest module: DiagnosticUtil is only constructed when the
file is executed directly, so test discovery stays side-effect-free.
"""

import argparse
import logging
import sys

# Add project root to sys.path for imports when running this file directly
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.cli.diagnostic_util import DiagnosticUtil
from app.utils.sqlite_handler import SQLiteHandler

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MonitorHub diagnostics runner")
    parser.add_argument(
        "-t",
        "--test-cases",
        nargs="*",
        default=["check_monitor_config"],
        help=(
            "Diagnostics to run: check_app_env, check_profile_import, "
            "check_rclone_dependency, check_app_config"
        ),
    )
    parser.add_argument(
        "-d",
        "--db-dir",
        default="db",
        help="Directory containing monitorhub.db (default: db)",
    )
    args = parser.parse_args()

    sqlite_handler = SQLiteHandler(
        logger=logging.getLogger(__name__),
        db_dir=args.db_dir,
    )
    diagnostic_util = DiagnosticUtil(
        sqlite_handler=sqlite_handler,
        logger=None,
    )

    if ("check_app_env" in args.test_cases):
        if (diagnostic_util.check_app_env()):
            print("Env check passed")
        else:
            print("Env check failed")

    elif ("check_profile_import" in args.test_cases):
        if diagnostic_util.check_profile_import():
            print("Profile import passed")
        else:
            print("Profile import failed")

    elif ("check_rclone_dependency" in args.test_cases):
        if diagnostic_util.check_rclone_dependency():
            print("Check for Rclone dependency passed")
        else:
            print("Check for Rclone dependency failed")

    elif ("check_monitor_config" in args.test_cases):
        if (diagnostic_util.check_monitor_config()):
            print("Monitor config check passed")
        else:
            print("Monitor config check failed")
    else:
        print("No test cases selected")

    # diagnostic_util.print_overview()

    sys.exit(0)