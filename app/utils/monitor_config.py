"""Monitor ``config``-building helpers.

Shared by the CLI wizard and the web GUI so both construct a monitor's
``config`` dict the same way.  Pure functions with no I/O or presentation
dependencies, so they are trivially unit-testable.
"""

from __future__ import annotations

from app.utils.constants import (
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)


def normalize_interval(value: str) -> str:
    """Normalize an interval: a bare number means minutes (``10`` -> ``10m``).

    A value with a unit suffix (``10s``, ``2h``, ``1d``) is kept verbatim.
    """
    value = value.strip()
    return value + "m" if value.isdigit() else value


def parse_exclude_patterns(value: str) -> list[str]:
    """Split a comma-separated exclude-pattern input into a trimmed list."""
    return [part.strip() for part in value.split(",") if part.strip()]


def build_monitor_config(monitor_type: str, interval: str, exclude_patterns: str) -> dict:
    """Build the monitor ``config`` dict for the selected monitor type."""
    patterns = parse_exclude_patterns(exclude_patterns)
    if monitor_type in (MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE):
        return {"interval": normalize_interval(interval), "exclude_patterns": patterns}
    if monitor_type == MONITOR_TYPE_INSTANT:
        return {"exclude_patterns": patterns}
    return {}
