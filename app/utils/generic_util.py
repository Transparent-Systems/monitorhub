"""
This script contains utility static methods and data structures.
"""

import datetime
import os
import re
from collections import OrderedDict
from typing import Any

from app.utils.constants import TIMESTAMP_FORMAT


class BoundedLRUDict(OrderedDict):
    """
    A dictionary with a maximum size that evicts the least recently accessed
    item when its capacity is reached.
    """
    def __init__(self, maxsize: int = 1000, *args: Any, **kwargs: Any) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self.move_to_end(key)
        if len(self) > self.maxsize:
            self.popitem(last=False)


def is_interval_valid(interval: str | None) -> bool:
    """Check if interval string is a valid non-negative interval (e.g. 0, 10, 10s, 10m, 10h, 10d)."""
    if not isinstance(interval, str):
        return False
    return bool(re.fullmatch(r"\d+[smhd]?", interval.strip().lower()))


def convert_to_seconds(time_str: str | int | None) -> int:
    """
    Converts a time string (e.g., "1m", "5s", "1h", "2d") or an integer / integer
    string (e.g., 60, "60") to seconds.

    Args:
        time_str (str | int | None): The time value or string to convert.

    Returns:
        int: The time in seconds.
    """
    if time_str is None:
        return 0

    if isinstance(time_str, int):
        return time_str

    if not isinstance(time_str, str) or not time_str:
        return 0

    # Convert to lowercase
    time_str = time_str.strip().lower()

    # If time_str is an integer string, return that value
    if time_str.isdigit():
        return int(time_str)

    if time_str.endswith("s"):
        return int(time_str[:-1])
    if time_str.endswith("m"):
        return int(time_str[:-1]) * 60
    if time_str.endswith("h"):
        return int(time_str[:-1]) * 3600
    if time_str.endswith("d"):
        return int(time_str[:-1]) * 86400

    return 0


def find_by_id(items: list[dict], item_id: int) -> dict | None:
    """Return the first item whose ``id`` matches ``item_id``, or None.

    Used by the CLI selection prompts so users can pick database entities by
    their stable id instead of a transient 1..n list index.
    """
    for item in items:
        if item.get("id") == item_id:
            return item
    return None


def utc_timestamp_now() -> str:
    """Return the current UTC time formatted with the shared ``TIMESTAMP_FORMAT``.

    Used whenever a timestamp is written to the database (e.g. a monitor's
    ``last_run`` or ``last_heartbeat``) so that writers and readers agree on a
    single canonical, timezone-free UTC representation.
    """
    return datetime.datetime.now(datetime.UTC).strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str | None) -> datetime.datetime | None:
    """Parse a ``TIMESTAMP_FORMAT`` string into a timezone-aware (UTC) datetime.

    Returns ``None`` when ``value`` is empty or does not match the shared
    format. This is the counterpart of :func:`utc_timestamp_now`; keeping the
    two together prevents the writer/reader format drift that previously made
    every monitor heartbeat unparseable.
    """
    if not value:
        return None
    try:
        parsed = datetime.datetime.strptime(value, TIMESTAMP_FORMAT).replace(
            tzinfo=datetime.UTC
        )
    except (ValueError, TypeError):
        return None
    return parsed


def is_process_alive(pid: int | None) -> bool:
    """Return True if a process with the given ``pid`` currently exists.

    Cross-platform best-effort liveness check used to detect a monitor process
    that is still running (including during the intermediate ``stop`` state)
    before starting a second instance for the same monitor.

    Note: the OS may reuse PIDs, so a ``True`` result cannot prove the process
    is the *same* one we recorded; it is only used to avoid creating an
    obviously duplicate monitor process.
    """
    if not pid or pid <= 0:
        return False

    if os.name == "nt":
        return _is_process_alive_windows(pid)

    try:
        # Signal 0 performs error checking without sending a signal.
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists but is owned by another user.
        return True
    except OSError:
        return False
    return True


def _is_process_alive_windows(pid: int) -> bool:
    """Windows-specific liveness check via OpenProcess/GetExitCodeProcess."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
