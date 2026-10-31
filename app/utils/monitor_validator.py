"""Validation helpers for monitor data.

Shared by the CLI (``app.cli.monitor_commands``) and the web GUI, so
both presentation layers apply the same business rules.
"""

from __future__ import annotations

from pathlib import Path

from app.utils import reference_data
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


def profiles_required_error(profiles: list[dict] | None) -> str | None:
    """Return an error message when a monitor has no profiles, else None.

    A monitor consumes events and dispatches them to the profiles attached to
    it through ``monitor_profile_map``. The relationship is optional in the
    database — ``profiles`` is not a column on ``monitors`` — but a monitor with
    no profiles has nothing to dispatch to: it starts, finds no profiles and
    exits with a bare "No profiles found" in ``logs/monitor_<id>.log``, which
    the user sees as an unexplained startup failure.

    Shared by the CLI and the web GUI so a monitor cannot be created, edited or
    started without at least one profile.
    """
    if not profiles:
        return "Attach at least one profile: a monitor needs a profile to run."
    return None


def has_remote_profile(profiles: list[dict] | None) -> bool:
    """Return whether any profile in *profiles* is a remote profile.

    A remote profile copies files between the monitor path and the remote path;
    a command profile runs a command and never touches the remote path. The
    category is derived from ``profile_type`` (see
    :func:`app.utils.reference_data.get_profile_category`), so this is the same
    test the monitor runtime applies.
    """
    return any(
        reference_data.get_profile_category(profile.get("profile_type", ""))
        == reference_data.PROFILE_CATEGORY_REMOTE
        for profile in profiles or []
    )


def remote_path_required_error(
    remote_path: str | None, profiles: list[dict] | None
) -> str | None:
    """Return an error when a remote profile has no remote path, else None.

    The remote path is required as soon as a remote profile is attached, and is
    not needed at all by a monitor whose profiles are all command profiles.
    Enforced so a monitor cannot be saved (or started) with a remote profile
    and no destination, which would reach the remote handler as an empty path.
    """
    if (remote_path or "").strip():
        return None

    for profile in profiles or []:
        if (
            reference_data.get_profile_category(profile.get("profile_type", ""))
            == reference_data.PROFILE_CATEGORY_REMOTE
        ):
            return (
                "Remote path is required because profile "
                f"'{profile.get('name', 'N/A')}' is a remote profile."
            )
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
