"""
This script contains utility static methods and data structures.
"""

import datetime
import os
import re
import sys
from collections import OrderedDict
from typing import Any

from app.utils.constants import TIMESTAMP_FORMAT


class BoundedLRUDict(OrderedDict):
    """
    A dictionary with a maximum size that evicts the least recently used item
    when its capacity is reached. Recency is updated on both access (``[]`` /
    ``get``) and assignment, so a frequently read entry is not evicted while
    colder ones survive.
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

    def __getitem__(self, key: Any) -> Any:
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value for ``key``, refreshing its recency when present."""
        try:
            return self[key]
        except KeyError:
            return default


def is_interval_valid(interval: str | None) -> bool:
    """Check if interval string is a valid non-negative interval (e.g. 0, 10, 10s, 10m, 10h, 10d)."""
    if not isinstance(interval, str):
        return False
    return bool(re.fullmatch(r"\d+[smhd]?", interval.strip().lower()))


def convert_to_seconds(time_str: str | int | float | None) -> int | float:
    """
    Converts a time value to seconds.

    Accepts:
    * a number of seconds (``int`` or ``float``, e.g. ``60`` or ``0.5``);
    * a string with an optional unit suffix (e.g. ``"60"``, ``"0.5s"``,
      ``"5m"``, ``"2h"``, ``"1d"``); strings without a unit are seconds.

    Whole-number results are returned as ``int`` and fractional results as
    ``float``. ``None``, empty/whitespace strings, unparseable text, boolean
    values and negative inputs convert to ``0``. Fractional strings (such as
    ``"0.5s"``) and float inputs (such as ``60.0``) are handled without
    crashing or silently collapsing to ``0``.
    """
    if time_str is None or isinstance(time_str, bool):
        return 0

    if isinstance(time_str, (int, float)):
        seconds = float(time_str)
        if seconds < 0:
            return 0
        return int(seconds) if seconds.is_integer() else seconds

    if not isinstance(time_str, str) or not time_str:
        return 0

    text = time_str.strip().lower()
    if not text:
        return 0

    multiplier = 1
    for unit, factor in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if text.endswith(unit):
            multiplier = factor
            text = text[: -len(unit)] if len(unit) else text
            break

    try:
        seconds = float(text) * multiplier
    except ValueError:
        return 0

    if seconds < 0:
        return 0
    return int(seconds) if seconds.is_integer() else seconds


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
    obviously duplicate monitor process. A terminated but not-yet-reaped child
    (zombie) is reported as **not** alive, so a monitor whose parent is still
    running is not mistaken for a live process while it shuts down.
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

    # The PID exists, but it may be a terminated child still awaiting reaping.
    # os.kill(pid, 0) succeeds for such zombies, which would otherwise make a
    # gracefully shut-down monitor look like it is still running.
    return not _is_zombie_process(pid)


def _is_zombie_process(pid: int) -> bool:
    """Return True when ``pid`` is a terminated but unreaped (zombie) process.

    A zombie keeps occupying its PID until its parent reaps it (``wait`` /
    ``waitpid``), so a plain existence check reports it as alive. Detecting the
    ``Z`` state avoids the false positive that occurs when a monitor child has
    already exited but its parent (e.g. an interactive test harness that
    discarded the ``Popen`` handle) has not collected its exit status yet.
    """
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat", "r") as stat_file:
                # The process name may contain spaces and parentheses, so read
                # the state field (the token after the final ')') instead of
                # splitting the whole line.
                state = stat_file.read().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, IndexError, OSError):
            # /proc entry already gone or unavailable; not detectable as zombie.
            return False
        return state in ("Z", "X")

    # Best-effort fallback for other POSIX platforms (e.g. macOS).
    try:
        import subprocess

        result = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return False
    return result.stdout.strip().upper().startswith("Z")


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
