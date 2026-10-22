"""Validation helpers for monitor data.

Shared by the CLI (``app.cli.monitor_commands``) and the web GUI, so
both presentation layers apply the same business rules.
"""

from __future__ import annotations

from pathlib import Path

from app.utils.project_paths import project_root
from app.utils.sqlite_handler import SQLiteHandler


def monitor_name_is_unique(handler: SQLiteHandler, name: str) -> str | None:
    """Return an error message if a monitor with *name* already exists, else None."""
    if handler.get_monitor(monitor_name=name):
        return f"Monitor name: {name} already exists. Please try again"
    return None


def validate_monitor_type_number(
    value: str, monitor_types: list[tuple[str, str]]
) -> str | None:
    """Validate a 1-based monitor type selection.

    Returns an error message when ``value`` is not a digit within
    ``1..len(monitor_types)``, otherwise ``None``. Shared by the ``new`` and
    ``edit`` flows so both reject typos and out-of-range numbers consistently.
    """
    if not value.isdigit() or not (0 < int(value) <= len(monitor_types)):
        return f"Invalid monitor type number: {value}. Please try again."
    return None


def monitor_path_is_valid(monitor_path: str) -> str | None:
    """Return an error message when a monitor path is unusable, else None.

    The monitor path is the local directory a monitor watches (instant),
    copies from (backup), or restores into (restore). It must exist and be a
    directory for every monitor type. Relative paths are resolved against the
    project root, matching the working directory of a launched monitor child.
    """
    path_text = (monitor_path or "").strip()
    if not path_text:
        return "Monitor path cannot be empty."

    path = Path(path_text)
    if not path.is_absolute():
        path = project_root() / path

    try:
        exists = path.exists()
        is_directory = path.is_dir()
    except OSError as error:
        return f"Monitor path '{path_text}' cannot be accessed: {error}"

    if not exists:
        return f"Monitor path '{path_text}' does not exist."
    if not is_directory:
        return f"Monitor path '{path_text}' is not a directory."
    return None
