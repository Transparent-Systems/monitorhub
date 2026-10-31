"""
Script: run_monitor.py
Version: v1.2.0
Author: John Zoetebier
Date: 2026-08-12
    Entry point for a single monitor process.
    Launched as a child process by mhub.py (monitor start).
    Updates the database with status and PID on start/stop.
Usage:
    python -m app.monitor.run_monitor --monitor-id <ID> --db-dir <PATH> --log <PATH>
"""

import argparse
import logging
import os
import signal
import sqlite3
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

from app.monitor.monitor_handler import MonitorHandler
from app.monitor.monitor_handler_factory import MonitorHandlerFactory
from app.utils.constants import (
    MONITOR_STATUS_RUNNING,
    MONITOR_STATUS_STOP,
    MONITOR_STATUS_STOPPED,
)
from app.utils.generic_util import is_process_alive, utc_timestamp_now
from app.utils.logger_setup import setup_logging
from app.utils.monitor_validator import (
    monitor_path_is_valid,
    remote_path_required_error,
)
from app.utils.project_paths import project_conf
from app.utils.sqlite_handler import SQLiteHandler

# Interval (seconds) between two polls of the database for a 'stop' command.
STATUS_POLL_SECONDS = 10

# Maximum time (seconds) to wait for the status poller thread to finish.
POLLER_JOIN_TIMEOUT_SECONDS = 2.0

# A heartbeat write that hits transient lock contention (another process writing
# to the same database) is retried once after this short pause. The pause is
# interruptible, so a shutdown request cancels the retry.
HEARTBEAT_RETRY_DELAY_SECONDS = 0.5


@dataclass
class MonitorRunContext:
    """
    Runtime state shared by the monitor lifecycle phases.

    Built by ``get_monitor_context`` and driven by ``run`` (which combines
    ``run_until_shutdown`` and ``teardown``). Keeping the state in one object
    lets every phase be tested in isolation while sharing the same logger,
    database handler and monitor handler.
    """
    monitor_id: int
    db_dir: str
    logger: logging.Logger
    log_config: dict[str, Any]
    sqlite_handler: SQLiteHandler
    monitor: dict[str, Any]
    profiles: list[dict[str, Any]]
    monitor_handler: MonitorHandler
    stop_event: threading.Event = field(default_factory=threading.Event)
    poller_thread: threading.Thread | None = None

    @classmethod
    def get_monitor_context(cls, args: argparse.Namespace) -> "MonitorRunContext | None":
        """
        Prepare a monitor run: logging, database, configuration and handler.

        Loads the monitor and its profiles, enforces the single-instance guard,
        marks the monitor as 'running' and creates the handler for its
        monitor_type.

        :return: A populated MonitorRunContext, or None when a precondition
            fails. On failure the reason is logged, the status is left
            consistent and the database connection is closed.
        """
        monitor_id = args.monitor_id
        db_dir = args.db_dir

        # Setup logging
        logger, log_config = setup_logging(
            args.log,
            log_level=args.log_level,
            dependency_log_level=args.dependency_log_level,
        )
        logger.info(f"Monitor process started with PID {os.getpid()} for monitor_id={monitor_id}")

        # Initialize database handler
        sqlite_handler = SQLiteHandler(logger=logger, db_dir=db_dir)

        # Load monitor configuration from database
        monitor = sqlite_handler.get_monitor(monitor_id=monitor_id)
        if not monitor:
            logger.error(f"Monitor with id={monitor_id} not found in database. Exiting.")
            sqlite_handler.close()
            return None

        # Load profiles from database for this monitor
        profiles = sqlite_handler.get_profiles_for_monitor(monitor_id=monitor_id)
        # If no profiles are found, log an error and exit.
        if not profiles:
            logger.error(f"No profiles found for monitor '{monitor.get('name')}' (id={monitor_id}). Exiting.")
            sqlite_handler.close()
            return None

        # A remote profile needs a remote path. Without one the remote handler
        # would be built with an empty base path, so fail here rather than let
        # it surface as an unexplained error later.
        remote_path_error = remote_path_required_error(
            monitor.get("remote_path"), profiles
        )
        if remote_path_error:
            logger.error(
                f"Monitor '{monitor.get('name')}' (id={monitor_id}) cannot start: "
                f"{remote_path_error} Exiting."
            )
            sqlite_handler.close()
            return None

        # Single-instance guard: refuse to start if another live process still owns
        # this monitor. This closes the stop -> start race where a graceful stop was
        # requested (status 'stop') but the previous process had not yet exited, and
        # prevents two observers from running on the same monitor path.
        existing_pid = int(monitor.get("pid") or 0)
        if existing_pid and existing_pid != os.getpid() and is_process_alive(existing_pid):
            logger.error(
                f"Monitor '{monitor.get('name')}' (id={monitor_id}) is already running as "
                f"pid={existing_pid}. Exiting to avoid a duplicate monitor process."
            )
            sqlite_handler.close()
            return None

        path_error = monitor_path_is_valid(monitor.get("monitor_path", ""))
        if path_error:
            logger.error(
                f"Monitor '{monitor.get('name')}' (id={monitor_id}) cannot start: "
                f"{path_error} Exiting."
            )
            sqlite_handler.close()
            return None

        # Update status to "running" and store PID
        pid = os.getpid()
        sqlite_handler.update_monitor_status(monitor_id=monitor_id, status=MONITOR_STATUS_RUNNING)
        sqlite_handler.update_monitor_pid(monitor_id=monitor_id, pid=pid)

        last_run = utc_timestamp_now()
        sqlite_handler.update_monitor_last_run(monitor_id=monitor_id, last_run=last_run)

        # Write the initial heartbeat immediately so the monitor is not misdetected
        # as stale during the window before the status poller's first tick (which
        # otherwise would not happen for another 10 seconds).
        last_heartbeat = utc_timestamp_now()
        sqlite_handler.update_monitor_last_heartbeat(monitor_id=monitor_id, last_heartbeat=last_heartbeat)

        logger.info(f"Monitor '{monitor.get('name')}' (id={monitor_id}) status set to 'running' with PID {pid}")

        # Create the monitor handler based on its monitor_type
        monitor_type = monitor.get("monitor_type", "")
        try:
            monitor_handler: MonitorHandler = MonitorHandlerFactory.create(
                monitor_type=monitor_type,
                monitor=monitor,
                profiles=profiles,
                log_config=log_config,
            )
        except ValueError as e:
            logger.error(
                f"Failed to start monitor '{monitor.get('name')}' (id={monitor_id}): {e}"
            )
            sqlite_handler.update_monitor_status(monitor_id=monitor_id, status=MONITOR_STATUS_STOPPED)
            sqlite_handler.update_monitor_pid(monitor_id=monitor_id, pid=0)
            sqlite_handler.close()
            return None

        return cls(
            monitor_id=monitor_id,
            db_dir=db_dir,
            logger=logger,
            log_config=log_config,
            sqlite_handler=sqlite_handler,
            monitor=monitor,
            profiles=profiles,
            monitor_handler=monitor_handler,
        )

    def _write_heartbeat(self) -> bool:
        """
        Write a heartbeat, retrying once after a transient database error.

        The heartbeat is best-effort: a missed one makes the monitor look stale
        to the CLI's stale-monitor detection, so a transient lock ('database is
        locked') gets one retry before the failure is reported. Only
        sqlite3.OperationalError is retried; other database errors fail fast.

        :return: False when no heartbeat was written (unknown monitor id, or a
            shutdown request arrived during the retry pause). A failed retry is
            raised for the caller to report.
        """
        try:
            self.sqlite_handler.update_monitor_last_heartbeat(
                monitor_id=self.monitor_id, last_heartbeat=utc_timestamp_now()
            )
            return True
        except sqlite3.OperationalError as error:
            self.logger.info(
                f"Heartbeat write for monitor_id={self.monitor_id} hit a transient "
                f"database error ({error}); retrying once in "
                f"{HEARTBEAT_RETRY_DELAY_SECONDS}s"
            )

        if self.stop_event.wait(HEARTBEAT_RETRY_DELAY_SECONDS):
            # Shutting down: no point retrying a heartbeat nobody will read.
            return False

        # A fresh timestamp: the first attempt may have waited on the lock.
        return self.sqlite_handler.update_monitor_last_heartbeat(
            monitor_id=self.monitor_id, last_heartbeat=utc_timestamp_now()
        )

    def _poll_status_once(self) -> bool:
        """
        Write a heartbeat and check the database for a 'stop' command.

        :return: True when the monitor was asked to stop via its DB status.
        """
        try:
            self._write_heartbeat()

            current = self.sqlite_handler.get_monitor(monitor_id=self.monitor_id)
            if current and current.get("status") == MONITOR_STATUS_STOP:
                self.logger.info(
                    f"Monitor '{self.monitor.get('name')}' (id={self.monitor_id}) "
                    f"received 'stop' command via DB status"
                )
                return True
        except Exception as e:  # noqa: BLE001 - a poller error must not stop the monitor loop
            self.logger.warning(f"Status poller error for monitor_id={self.monitor_id}: {e}")
        return False

    def run_until_shutdown(self) -> str | None:
        """
        Start the monitor handler and status poller, then block until shutdown.

        :return: The shutdown reason, or None when the handler failed to start.
            On start failure the monitor is marked 'stopped' and the database
            closed, matching the behaviour before this class was introduced.
        """
        monitor_id = self.monitor_id
        logger = self.logger
        monitor = self.monitor
        sqlite_handler = self.sqlite_handler
        stop_event = self.stop_event

        # Reason for shutdown
        shutdown_reason = "normal exit"
        shutdown_lock = threading.Lock()

        def request_shutdown(reason: str):
            """Signal shutdown to be handled cleanly by the main thread."""
            nonlocal shutdown_reason
            with shutdown_lock:
                if not stop_event.is_set():
                    shutdown_reason = reason
                stop_event.set()

        try:
            started = self.monitor_handler.start(on_complete=request_shutdown)
        except Exception:  # noqa: BLE001 - a failed start must not leave a stale 'running' row
            logger.exception(
                f"Failed to start monitor '{monitor.get('name')}' (id={monitor_id}). Exiting."
            )
            started = False
        else:
            if not started:
                logger.error(
                    f"Failed to start monitor '{monitor.get('name')}' (id={monitor_id}). Exiting."
                )

        if not started:
            sqlite_handler.update_monitor_status(monitor_id=monitor_id, status=MONITOR_STATUS_STOPPED)
            sqlite_handler.update_monitor_pid(monitor_id=monitor_id, pid=0)
            sqlite_handler.close()
            return None

        def status_poller():
            """Background thread: periodically checks DB for a 'stop' command."""
            while not stop_event.is_set():
                if stop_event.wait(STATUS_POLL_SECONDS):
                    break  # stop_event was set, exit cleanly

                if self._poll_status_once():
                    request_shutdown("stop command received via DB poll")
                    break

        self.poller_thread = threading.Thread(target=status_poller, daemon=True, name="status-poller")
        self.poller_thread.start()

        def shutdown_handler(signum, frame):
            request_shutdown(f"received signal {signal.Signals(signum).name}")

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

        # Block the main thread cleanly until shutdown is requested.
        # Using a timed wait on stop_event allows signals (SIGINT/SIGTERM) to be
        # processed promptly by the main thread without blocking indefinitely.
        try:
            while not stop_event.is_set():
                stop_event.wait(timeout=1.0)
        except (KeyboardInterrupt, SystemExit):
            request_shutdown("interrupted")

        return shutdown_reason

    def teardown(self, reason: str) -> None:
        """
        Stop the handler and poller, then record the stopped state in the DB.
        """
        monitor_id = self.monitor_id
        logger = self.logger
        monitor = self.monitor

        # Main thread performs full teardown and cleanup
        logger.info(
            f"Shutting down monitor '{monitor.get('name')}' (id={monitor_id}) — reason: {reason}"
        )
        self.stop_event.set()
        self.monitor_handler.stop()
        poller_thread = self.poller_thread
        if poller_thread is not None and poller_thread.is_alive():
            poller_thread.join(timeout=POLLER_JOIN_TIMEOUT_SECONDS)

        try:
            self.sqlite_handler.update_monitor_status(monitor_id=monitor_id, status=MONITOR_STATUS_STOPPED)
            self.sqlite_handler.update_monitor_pid(monitor_id=monitor_id, pid=0)
            logger.info(
                f"Monitor '{monitor.get('name')}' (id={monitor_id}) status set to 'stopped'"
            )
        finally:
            # Always release the connection, even when the status update failed.
            self.sqlite_handler.close()

    def run(self) -> int:
        """
        Run the monitor to completion and return its exit code.

        Combines run_until_shutdown() with teardown(). Returns 1 when the
        handler failed to start; in that case the stopped state has already
        been persisted and no teardown is performed.
        """
        reason = self.run_until_shutdown()
        if reason is None:
            return 1

        self.teardown(reason)
        return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse the command-line arguments for a standalone monitor process.

    :param argv: Argument list, defaulting to ``sys.argv[1:]`` when omitted.
    """
    parser = argparse.ArgumentParser(
        description="Run a single MonitorHub monitor as a standalone process."
    )
    parser.add_argument(
        "-i", "--monitor-id",
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
        default=None,
        help="Path to the log configuration file (default: conf/log.yaml beside the application)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override the log level from the configuration file",
    )
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
    args = parser.parse_args(argv)
    if args.log is None:
        args.log = str(project_conf("log.yaml"))
    return args


def run_monitor_main(argv=None) -> int:
    """
    Run a single monitor as a standalone entry point.

    Accepts an optional argv list (defaulting to sys.argv[1:]) so the same
    logic can be reused both when invoked as ``python -m app.monitor.run_monitor``
    (or launched by ``MonitorProcessManager`` as a module with the project
    root as its working directory) and when dispatched in-process from the
    frozen PyInstaller binary.
    """
    args = parse_args(argv)

    try:
        context = MonitorRunContext.get_monitor_context(args)
        if context is None:
            sys.exit(1)

        exit_code = context.run()
    except sqlite3.Error as error:
        # This process runs detached with its stderr redirected to
        # logs/monitor_<id>.log, so report the failure rather than traceback.
        logging.getLogger("MonitorHub").error(
            f"Database error for monitor id={args.monitor_id}: {error}"
        )
        print(
            f"Database error: {error}\n"
            "Is the database initialised? Create it with: python mhub.py database init",
            file=sys.stderr,
        )
        return 1

    if exit_code != 0:
        sys.exit(exit_code)

    return 0


def main():
    """Backward-compatible CLI entry point."""
    sys.exit(run_monitor_main())


if __name__ == "__main__":
    main()
