"""
Script: run_monitor.py
Version: v1.0.0
Author: John Zoetebier
Date: 2026-08-12
    Entry point for a single monitor process.
    Launched as a child process by mhub.py (monitor start / start-all).
    Updates the database with status and PID on start/stop.
Usage:
    python app/monitor/run_monitor.py --monitor-id <ID> --db-dir <PATH> --log <PATH>
"""

import argparse
import datetime
import os
import signal
import sys
import threading
import time
from pathlib import Path

# Ensure the project root is on sys.path so `app.*` imports resolve
# whether the script is run as `python app/monitor/run_monitor.py` or via
# `python -m app.monitor.run_monitor`.
project_root = Path(__file__).resolve().parents[2]  # Two levels up to reach the project root
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.monitor.monitor_handler import MonitorHandlerFactory
from app.utils.sqlite_handler import SQLiteHandler
from app.utils.logger_setup import setup_logging


def run_monitor_main(argv=None) -> int:
    """
    Run a single monitor as a standalone entry point.

    Accepts an optional argv list (defaulting to sys.argv[1:]) so the same
    logic can be reused both when invoked as ``python app/monitor/run_monitor.py``
    and when dispatched in-process from the frozen PyInstaller binary.
    """
    parser = argparse.ArgumentParser(
        description="Run a single MonitorHub monitor as a standalone process."
    )
    parser.add_argument(
        "-m", "--monitor-id",
        type=int,
        required=True,
        help="ID of the monitor in the database",
    )
    parser.add_argument(
        "-d", "--db-dir",
        type=str,
        default="data",
        metavar="<PATH>",
        help="Directory of SQlite database"
    )
    parser.add_argument(
        "-l", "--log",
        type=str,
        default="conf/log.yaml",
        help="Path to the log configuration file",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override the log level from the configuration file",
    )
    args = parser.parse_args(argv)

    monitor_id = args.monitor_id
    db_dir = args.db_dir

    # Setup logging
    logger, log_config = setup_logging(args.log, log_level=args.log_level)
    logger.info(f"Monitor process started with PID {os.getpid()} for monitor_id={monitor_id}")

    # Initialize database handler
    sqlite_handler = SQLiteHandler(logger=logger, db_dir=db_dir)

    # Load monitor configuration from database
    monitor = sqlite_handler.get_monitor(monitor_id=monitor_id)
    if not monitor:
        logger.error(f"Monitor with id={monitor_id} not found in database. Exiting.")
        sqlite_handler.close()
        sys.exit(1)

    # Load profiles from database for this monitor
    profiles = sqlite_handler.get_profiles_for_monitor(monitor_id=monitor_id)
    # If no profiles are found, log an error and exit.
    if not profiles:
        logger.error(f"No profiles found for monitor '{monitor.get('name')}' (id={monitor_id}). Exiting.")
        sqlite_handler.close()
        sys.exit(1)

    # Update status to "running" and store PID
    pid = os.getpid()
    sqlite_handler.update_monitor_status(monitor_id=monitor_id, status="running")
    sqlite_handler.update_monitor_pid(monitor_id=monitor_id, pid=pid)

    last_run = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    sqlite_handler.update_monitor_last_run(monitor_id=monitor_id, last_run=last_run)

    # Write the initial heartbeat immediately so the monitor is not misdetected
    # as stale during the window before the status poller's first tick (which
    # otherwise would not happen for another 10 seconds).
    last_heartbeat = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    sqlite_handler.update_monitor_last_heartbeat(monitor_id=monitor_id, last_heartbeat=last_heartbeat)

    logger.info(f"Monitor '{monitor.get('name')}' (id={monitor_id}) status set to 'running' with PID {pid}")

    # Create and start the monitor handler based on its monitor_type
    monitor_type = monitor.get("monitor_type", "")
    try:
        monitor_handler = MonitorHandlerFactory.create(
            monitor_type=monitor_type,
            monitor=monitor,
            profiles=profiles,
            log_config=log_config,
        )
    except ValueError as e:
        logger.error(
            f"Failed to start monitor '{monitor.get('name')}' (id={monitor_id}): {e}"
        )
        sqlite_handler.update_monitor_status(monitor_id=monitor_id, status="stopped")
        sqlite_handler.update_monitor_pid(monitor_id=monitor_id, pid=0)
        sqlite_handler.close()
        sys.exit(1)

    if not monitor_handler.start():
        logger.error(f"Failed to start monitor '{monitor.get('name')}' (id={monitor_id}). Exiting.")
        sqlite_handler.update_monitor_status(monitor_id=monitor_id, status="stopped")
        sqlite_handler.update_monitor_pid(monitor_id=monitor_id, pid=0)
        sqlite_handler.close()
        sys.exit(1)

    # Event used to signal the poller thread to stop
    stop_event = threading.Event()

    # Flag to prevent duplicate shutdown
    shutdown_lock = threading.Lock()
    has_shutdown = False

    def do_shutdown(reason: str):
        """Perform graceful shutdown: stop monitor, update DB, exit."""
        nonlocal has_shutdown

        with shutdown_lock:
            if has_shutdown:
                return
            has_shutdown = True

        logger.info(
            f"Shutting down monitor '{monitor.get('name')}' (id={monitor_id}) — reason: {reason}"
        )
        stop_event.set()
        monitor_handler.stop()
        sqlite_handler.update_monitor_status(monitor_id=monitor_id, status="stopped")
        sqlite_handler.update_monitor_pid(monitor_id=monitor_id, pid=0)
        logger.info(
            f"Monitor '{monitor.get('name')}' (id={monitor_id}) status set to 'stopped'"
        )
        sqlite_handler.close()

        # sys.exit() only stops the current thread. When do_shutdown is called
        # from the background status-poller thread, it would leave the main
        # thread blocked in signal.pause(). Use os._exit() to terminate the
        # whole process after cleanup, from any thread.
        os._exit(0)

    def status_poller():
        """Background thread: periodically checks DB for a 'stop' command."""
        poll_interval = 10  # seconds
        while not stop_event.is_set():
            if stop_event.wait(poll_interval):
                break  # stop_event was set, exit cleanly

            try:
                last_heartbeat = datetime.datetime.now(
                    datetime.timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
                sqlite_handler.update_monitor_last_heartbeat(
                    monitor_id=monitor_id, last_heartbeat=last_heartbeat
                )

                current = sqlite_handler.get_monitor(monitor_id=monitor_id)
                if current and current.get("status") == "stop":
                    logger.info(
                        f"Monitor '{monitor.get('name')}' (id={monitor_id}) "
                        f"received 'stop' command via DB status"
                    )
                    do_shutdown("stop command received via DB poll")
                    break
            except Exception as e:
                logger.warning(f"Status poller error for monitor_id={monitor_id}: {e}")

    poller_thread = threading.Thread(target=status_poller, daemon=True, name="status-poller")
    poller_thread.start()

    def shutdown_handler(signum, frame):
        do_shutdown(f"received signal {signal.Signals(signum).name}")

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Block the main thread — the watchdog observer runs in its own threads.
    # The child process stays alive until a signal is received.
    try:
        signal.pause()
    except AttributeError:
        # signal.pause() is not available on Windows; fall back to sleep loop
        while not stop_event.is_set():
            time.sleep(1)

    # If we get here (e.g. signal.pause() interrupted), trigger shutdown
    if not has_shutdown:
        do_shutdown("main loop exited")

    return 0


def main():
    """Backward-compatible CLI entry point."""
    run_monitor_main()


if __name__ == "__main__":
    main()
