"""
Global constants for the MonitorHub application.
"""

__all__ = [
    "DB_FILENAME",
    "DEFAULT_COMMAND_MAX_WORKERS",
    "MAX_COMMAND_MAX_WORKERS",
    "MIN_COMMAND_MAX_WORKERS",
    "MONITOR_STATUS_ERROR",
    "MONITOR_STATUS_RUNNING",
    "MONITOR_STATUS_STOP",
    "MONITOR_STATUS_STOPPED",
    "MONITOR_TYPE_BACKUP",
    "MONITOR_TYPE_INSTANT",
    "MONITOR_TYPE_RESTORE",
    "TIMESTAMP_FORMAT",
]

MONITOR_STATUS_RUNNING = "running"
MONITOR_STATUS_STOP = "stop"
MONITOR_STATUS_STOPPED = "stopped"
MONITOR_STATUS_ERROR = "error"

MONITOR_TYPE_INSTANT = "instant"
MONITOR_TYPE_BACKUP = "backup"
MONITOR_TYPE_RESTORE = "restore"
DB_FILENAME = "monitorhub.db"

# Bounds for the number of concurrent command processes spawned by a
# CommandActionHandler (an "event_command" profile). The pool bounds concurrency
# — and therefore the number of simultaneous child processes — but never drops
# events: excess commands are queued FIFO and executed as workers free up.
# Shared here so the CLI (display/validation in profile commands) and the action
# handler agree without the CLI importing the monitor stack.
DEFAULT_COMMAND_MAX_WORKERS = 100
MIN_COMMAND_MAX_WORKERS = 1
MAX_COMMAND_MAX_WORKERS = 1000

# Canonical format for timestamps stored as TEXT in the database
# (e.g. monitors.last_run and monitors.last_heartbeat). The writer
# (run_monitor) and any reader (e.g. stale-monitor detection in
# MonitorCommands) must share this format so heartbeats always parse.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
