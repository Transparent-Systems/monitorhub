"""Profiles page for the MonitorHub web GUI.

Manages the full profile lifecycle: list, create, edit, delete, clone, and
test.  Talks to the backend (``app.utils`` and ``app.monitor``) directly and
never imports ``app.cli``.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

# StreamLit runs page scripts with the page's own directory on ``sys.path``,
# which would shadow the top-level ``app`` package. Add the project root (the
# folder containing ``app/`` and ``pyproject.toml``) explicitly so ``app.*``
# imports resolve regardless of how the page is launched.
#
# Skipped when frozen (PyInstaller): ``app.*`` is served from the bundled
# archive, and there is no ``pyproject.toml`` to walk up to.
if not getattr(sys, "frozen", False):
    _root = Path(__file__).resolve().parent
    while not (_root / "pyproject.toml").exists() and _root.parent != _root:
        _root = _root.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import streamlit as st

from app.monitor import rclone_importer
from app.monitor.rclone_handler import RcloneHandler
from app.monitor.s3_factory import S3Factory
from app.utils import profile_display, reference_data
from app.utils.app_config import AppConfig
from app.utils.constants import (
    DEFAULT_COMMAND_MAX_WORKERS,
    MAX_COMMAND_MAX_WORKERS,
    MIN_COMMAND_MAX_WORKERS,
)
from app.utils.generic_util import is_interval_valid
from app.utils.sqlite_handler import SQLiteHandler

# Profile types that the web GUI knows how to render forms for.  The list
# combines all known categories so the type dropdown includes every option.
KNOWN_PROFILE_TYPES: tuple[str, ...] = (
    reference_data.NATIVE_PROFILE_TYPES  # "s3"
    + reference_data.COMMAND_PROFILE_TYPES  # "event_command"
    + tuple(name for name, _ in reference_data.KNOWN_RCLONE_PROFILE_TYPES)
)

# Config keys that can appear in a profile but are metadata, not editable
# backend properties.  Mirrors rclone_env.MONITORHUB_ONLY_KEYS plus comment
# and important (legacy rclone-import display hints).
_META_CONFIG_KEYS = frozenset(
    {
        reference_data.CONFIG_REMOTE_HANDLER,
        "rclone_options",
        "comment",
        "important",
    }
)
# ---------------------------------------------------------------------------
# Backend resources
# ---------------------------------------------------------------------------


def _resources() -> SQLiteHandler:
    """Build (once) and return the shared SQLiteHandler."""
    if "sqlite_handler" not in st.session_state:
        db_dir = AppConfig().get_default_db_dir(fallback="data")
        logger = logging.getLogger("app.webgui")
        st.session_state["sqlite_handler"] = SQLiteHandler(logger=logger, db_dir=db_dir)
    return st.session_state["sqlite_handler"]


# ---------------------------------------------------------------------------
# Profile operations
# ---------------------------------------------------------------------------


def _clone_profile(
    sqlite_handler: SQLiteHandler,
    profile: dict,
    deep: bool = False,
) -> tuple[str, str]:
    """Clone a profile; return (message, kind)."""
    source_id = profile.get("id", 0)
    source_name = profile.get("name", "N/A")

    try:
        new_id = sqlite_handler.clone_profile(source_id, deep=deep)
    except sqlite3.IntegrityError:
        return (
            f"Could not clone profile '{source_name}': name collision.",
            "warning",
        )

    if new_id is None:
        return f"Could not clone profile '{source_name}'.", "error"

    clone = sqlite_handler.get_profile(profile_id=new_id)
    new_name = clone.get("name", "N/A") if clone else "N/A"
    clone_kind = "deep clone" if deep else "shallow clone"
    return f"Profile '{new_name}' created as a {clone_kind} of '{source_name}'.", "success"


class _CapturePrompt:
    """Minimal prompt-like object that captures ``print()`` calls as lines."""

    def __init__(self) -> None:
        self._lines: list[str] = []

    def print(self, text: str = "") -> None:
        self._lines.append(text)

    def get_output(self) -> str:
        return "\n".join(self._lines)


def _test_profile(
    profile: dict,
) -> tuple[str, bool]:
    """Test a profile; return (message, success)."""
    profile_name = profile.get("name", "N/A")
    config = profile.get("config") or {}
    profile_type = profile.get("profile_type", "")

    if not profile_type:
        return f"Profile '{profile_name}' has no type.", False

    category = reference_data.get_profile_category(profile_type)

    if category == reference_data.PROFILE_CATEGORY_COMMAND:
        return _test_command_profile(profile_name, config)

    handler_key = reference_data.remote_handler_key(profile)
    prompt = _CapturePrompt()
    logger = logging.getLogger("app.webgui.profile_test")

    if handler_key == "s3":
        S3Factory.test_connection(
            profile_config=config, logger=logger, prompt=prompt
        )
    elif handler_key == reference_data.RCLONE_REMOTE_HANDLER:
        RcloneHandler.test_connection(
            profile_name=profile_name,
            logger=logger,
            prompt=prompt,
            profile=profile,
        )
    else:
        return (
            f"Unknown remote handler '{handler_key}' for profile '{profile_name}'.",
            False,
        )

    output = prompt.get_output()
    success = "Test successful" in output or "Connection successful" in output
    return output, success


def _test_command_profile(profile_name: str, config: dict) -> tuple[str, bool]:
    """Validate a command-profile config."""
    lines: list[str] = []

    command = (config.get("command") or "").strip()
    if not command:
        lines.append("Error: command is empty.")
        return "\n".join(lines), False
    lines.append(f"Command: {command}")

    command_events = config.get("command_events") or []
    if not command_events:
        lines.append("Error: command_events is empty.")
        return "\n".join(lines), False
    lines.append(f"Events: {', '.join(command_events)}")

    command_cooldown = str(config.get("command_cooldown", "")).strip()
    if command_cooldown and not is_interval_valid(command_cooldown):
        lines.append(f"Error: invalid cooldown '{command_cooldown}'.")
        return "\n".join(lines), False
    lines.append(f"Cooldown: {command_cooldown or 'none'}")

    command_shell = config.get("command_shell") or False
    lines.append(f"Shell: {command_shell}")

    max_workers_raw = config.get("command_max_workers", DEFAULT_COMMAND_MAX_WORKERS)
    try:
        max_workers = int(max_workers_raw)
        if not (MIN_COMMAND_MAX_WORKERS <= max_workers <= MAX_COMMAND_MAX_WORKERS):
            lines.append(
                f"Error: max_workers must be between {MIN_COMMAND_MAX_WORKERS} "
                f"and {MAX_COMMAND_MAX_WORKERS}."
            )
            return "\n".join(lines), False
    except (ValueError, TypeError):
        lines.append(f"Error: invalid max_workers '{max_workers_raw}'.")
        return "\n".join(lines), False
    lines.append(f"Max workers: {max_workers}")

    lines.append("")
    lines.append("All checks passed. Command profile is valid.")
    lines.append("Test succeeded")
    return "\n".join(lines), True
# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _flash() -> None:
    """Show (and clear) a pending one-shot success/warning/error message."""
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        if kind == "success":
            st.success(message)
        elif kind == "warning":
            st.warning(message)
        else:
            st.error(message)


def _profile_rows(profiles: list[dict]) -> list[dict]:
    """Return display-ready rows for the profile table."""
    return [
        {
            "ID": p.get("id"),
            "Name": p.get("name", "N/A"),
            "Type": p.get("profile_type", "N/A"),
            "Category": reference_data.get_profile_category(p.get("profile_type", "")),
            "Handler": _handler_label(p),
            "Config": _config_summary(p),
            "Created": p.get("date_created", ""),
            "Modified": p.get("last_modified", ""),
        }
        for p in profiles
    ]


def _handler_label(profile: dict) -> str:
    """Return a short label describing how this profile is routed."""
    category = reference_data.get_profile_category(profile.get("profile_type", ""))
    if category == reference_data.PROFILE_CATEGORY_COMMAND:
        return "command"
    return reference_data.remote_handler_key(profile)


def _config_summary(profile: dict) -> str:
    """Return a brief masked summary of the profile config for the table."""
    config = profile.get("config") or {}
    if not config:
        return "\u2014"
    items: list[str] = []
    for key in config:
        if key in _META_CONFIG_KEYS:
            continue
        items.append(f"{key}={profile_display.masked_value(key, config[key])}")
    if len(items) > 6:
        return "{" + ", ".join(items[:6]) + ", \u2026}"
    return "{" + ", ".join(items) + "}"
# ---------------------------------------------------------------------------
# Profile form validation
# ---------------------------------------------------------------------------


def _validate_profile_form(
    sqlite_handler: SQLiteHandler,
    name: str,
    profile_type: str,
    editing: dict | None,
) -> str | None:
    """Return an error message when the form is invalid, otherwise None."""
    if not name.strip():
        return "Profile name cannot be empty."
    if not profile_type.strip():
        return "Profile type cannot be empty."

    existing = sqlite_handler.get_profile(profile_name=name.strip())
    if existing and (editing is None or existing.get("id") != editing.get("id")):
        return f"Profile name '{name}' already exists."
    return None


# ---------------------------------------------------------------------------
# Profile form rendering — S3 fields
# ---------------------------------------------------------------------------


def _render_s3_fields(
    config: dict,
    key_prefix: str,
    editing: bool,
) -> dict:
    """Render S3-specific form fields; return the collected config dict."""
    providers = [p.name for p in reference_data.get_providers()]
    current_provider = config.get("provider", "")
    provider_index = (
        providers.index(current_provider) if current_provider in providers else 0
    )
    provider = st.selectbox(
        "Provider",
        providers,
        index=provider_index,
        key=f"{key_prefix}_s3_provider",
    )
    access_key_id = st.text_input(
        "Access Key ID",
        value=config.get("access_key_id", ""),
        key=f"{key_prefix}_s3_access_key",
    )
    secret_access_key = st.text_input(
        "Secret Access Key",
        value="",
        type="password",
        key=f"{key_prefix}_s3_secret_key",
        placeholder="(unchanged)" if editing else "",
    )

    new_config: dict = {
        "provider": provider,
        "access_key_id": access_key_id,
    }
    if secret_access_key.strip():
        new_config["secret_access_key"] = secret_access_key.strip()
    elif editing and config.get("secret_access_key"):
        new_config["secret_access_key"] = config["secret_access_key"]

    if reference_data.is_aws_provider(provider):
        region = st.text_input(
            "Region",
            value=config.get("region", ""),
            key=f"{key_prefix}_s3_region",
        )
        new_config["region"] = region
        new_config.pop("endpoint", None)
    else:
        endpoint = st.text_input(
            "Endpoint",
            value=config.get("endpoint", ""),
            key=f"{key_prefix}_s3_endpoint",
            placeholder="https://\u2026",
        )
        new_config["endpoint"] = endpoint
        new_config.pop("region", None)

    # remote_handler toggle
    current_handler = config.get(reference_data.CONFIG_REMOTE_HANDLER, "s3")
    use_rclone = current_handler == reference_data.RCLONE_REMOTE_HANDLER
    use_rclone = st.checkbox(
        "Use rclone instead of built-in S3 handler",
        value=use_rclone,
        key=f"{key_prefix}_s3_use_rclone",
    )
    new_config[reference_data.CONFIG_REMOTE_HANDLER] = (
        reference_data.RCLONE_REMOTE_HANDLER if use_rclone else "s3"
    )

    return new_config
# ---------------------------------------------------------------------------
# Profile form rendering — rclone / generic remote fields
# ---------------------------------------------------------------------------


def _render_rclone_fields(
    config: dict,
    key_prefix: str,
    editing: bool,
) -> dict:
    """Render generic rclone/remote profile fields as an editable key/value grid.

    The grid supports adding and removing options interactively.  Secret values
    are shown as ``********`` and left untouched unless the user replaces them.
    """
    new_config: dict = {}

    # Build the initial grid rows from the existing config (excluding meta keys).
    rows: list[dict[str, str]] = []
    for key in sorted(k for k in config if k not in _META_CONFIG_KEYS):
        value = config.get(key, "")
        if profile_display.is_secret_key(key):
            display_value = profile_display.MASK
        else:
            display_value = str(value) if value else ""
        rows.append({"Key": key, "Value": display_value})

    if not rows:
        st.info("No config options yet — add rows below.")

    st.caption(
        "Config options (secrets show as '********'; leave them unchanged to "
        "keep the stored value)."
    )

    edited = st.data_editor(
        rows,
        num_rows="dynamic",
        key=f"{key_prefix}_rclone_options",
        column_config={
            "Key": st.column_config.TextColumn("Key", required=True),
            "Value": st.column_config.TextColumn("Value", required=False),
        },
        hide_index=True,
    )

    for record in edited:
        if not isinstance(record, dict):
            continue
        key = str(record.get("Key") or "").strip()
        if not key:
            continue
        value = record.get("Value")
        if value is None or (isinstance(value, float) and value != value):
            value = ""
        if (
            profile_display.is_secret_key(key)
            and str(value) == profile_display.MASK
            and key in config
        ):
            # Unchanged secret — keep the stored value.
            new_config[key] = config[key]
        else:
            new_config[key] = value

    # Always carry over the remote_handler stored in config
    new_config[reference_data.CONFIG_REMOTE_HANDLER] = config.get(
        reference_data.CONFIG_REMOTE_HANDLER,
        reference_data.RCLONE_REMOTE_HANDLER,
    )

    return new_config


# ---------------------------------------------------------------------------
# Profile form rendering — command profile fields
# ---------------------------------------------------------------------------


def _render_command_fields(
    config: dict,
    key_prefix: str,
) -> dict:
    """Render command-profile form fields; return the collected config dict."""
    new_config: dict = {}

    command = st.text_area(
        "Command",
        value=config.get("command", ""),
        key=f"{key_prefix}_cmd_command",
        placeholder="/usr/bin/my-script --flag",
    )
    new_config["command"] = command

    available_events = ["created", "deleted", "modified", "moved", "closed", "timer"]
    current_events = config.get("command_events") or []
    default_events = [e for e in current_events if e in available_events]
    command_events = st.multiselect(
        "Events",
        available_events,
        default=default_events,
        key=f"{key_prefix}_cmd_events",
    )
    new_config["command_events"] = command_events

    command_cooldown = st.text_input(
        "Cooldown",
        value=str(config.get("command_cooldown", "")),
        key=f"{key_prefix}_cmd_cooldown",
        placeholder="e.g. 10s, 5m, 1h",
    )
    new_config["command_cooldown"] = command_cooldown

    command_timeout = st.text_input(
        "Timeout (seconds)",
        value=str(config.get("command_timeout", "")),
        key=f"{key_prefix}_cmd_timeout",
        placeholder="e.g. 30",
    )
    if command_timeout.strip():
        new_config["command_timeout"] = command_timeout.strip()

    command_shell = st.checkbox(
        "Run in shell",
        value=bool(config.get("command_shell")),
        key=f"{key_prefix}_cmd_shell",
    )
    new_config["command_shell"] = command_shell

    current_max = config.get("command_max_workers", DEFAULT_COMMAND_MAX_WORKERS)
    try:
        max_workers_val = int(current_max)
    except (ValueError, TypeError):
        max_workers_val = DEFAULT_COMMAND_MAX_WORKERS
    max_workers = st.number_input(
        "Max workers",
        min_value=MIN_COMMAND_MAX_WORKERS,
        max_value=MAX_COMMAND_MAX_WORKERS,
        value=max_workers_val,
        key=f"{key_prefix}_cmd_max_workers",
    )
    new_config["command_max_workers"] = max_workers

    return new_config
# ---------------------------------------------------------------------------
# Profile form (create / edit)
# ---------------------------------------------------------------------------


def _render_profile_form(
    sqlite_handler: SQLiteHandler,
    editing: dict | None,
    key_prefix: str,
) -> None:
    """Render a create/edit form inside an expander.

    ``key_prefix`` scopes every widget key so the "New profile" and
    "Edit profile" forms can both be rendered without a DuplicateWidgetID.
    """
    current = editing or {}
    config = current.get("config") or {}
    current_type = current.get("profile_type") or "s3"
    is_edit = editing is not None

    # Compile the type list from known types plus any type already in the DB.
    db_types = {
        p.get("profile_type", "")
        for p in sqlite_handler.get_profiles()
        if p.get("profile_type")
    }
    all_types = sorted(set(KNOWN_PROFILE_TYPES) | db_types)

    with st.expander("Edit profile" if is_edit else "New profile", expanded=True):
        # Type selector lives outside the form so changing it triggers a re-run
        # and the form conditionally shows the right field set.
        type_index = all_types.index(current_type) if current_type in all_types else 0
        profile_type = st.selectbox(
            "Profile type",
            all_types,
            index=type_index,
            key=f"{key_prefix}_type",
        )

        with st.form(key_prefix, clear_on_submit=False):
            name = st.text_input(
                "Name", value=current.get("name", ""), key=f"{key_prefix}_name"
            )

            st.divider()
            category = reference_data.get_profile_category(profile_type)

            if profile_type == "s3":
                new_config = _render_s3_fields(config, key_prefix, is_edit)
            elif category == reference_data.PROFILE_CATEGORY_COMMAND:
                new_config = _render_command_fields(config, key_prefix)
            else:
                new_config = _render_rclone_fields(config, key_prefix, is_edit)

            submitted = st.form_submit_button(
                "Save changes" if is_edit else "Create profile",
                type="primary",
            )
            cancelled = st.form_submit_button("Cancel")

            if cancelled:
                _close_profile_blocks()
                st.rerun()

            if not submitted:
                return

            error = _validate_profile_form(sqlite_handler, name, profile_type, editing)
            if error:
                st.error(error)
                return

            if not new_config.get(reference_data.CONFIG_REMOTE_HANDLER):
                default_handler = reference_data.default_remote_handler_key(
                    profile_type
                )
                if default_handler:
                    new_config[reference_data.CONFIG_REMOTE_HANDLER] = default_handler

            if is_edit:
                result = sqlite_handler.update_profile(
                    editing.get("id", 0), name, profile_type, new_config
                )
                if result is not None:
                    st.session_state["flash"] = (
                        "success",
                        f"Profile '{name}' updated.",
                    )
                    st.session_state["editing_profile_id"] = None
                else:
                    st.session_state["flash"] = (
                        "error",
                        f"Profile '{name}' not updated.",
                    )
            else:
                new_id = sqlite_handler.add_profile(name, profile_type, new_config)
                if new_id is not None:
                    st.session_state["flash"] = (
                        "success",
                        f"Profile '{name}' created.",
                    )
                    st.session_state["creating_profile"] = False
                else:
                    st.session_state["flash"] = (
                        "error",
                        f"Profile '{name}' not created.",
                    )
            st.rerun()
# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _render_actions(
    sqlite_handler: SQLiteHandler,
    profile: dict,
) -> None:
    """Render the edit/delete/new/clone/test actions for a selected profile."""
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        if st.button(
            "\u270e Edit",
            width="stretch",
            help="Opens an edit block below for this profile.",
        ):
            _close_profile_blocks()
            st.session_state["editing_profile_id"] = profile.get("id")
            st.rerun()
    with col2:
        if st.button(
            "\U0001f5d1 Delete",
            width="stretch",
            help="Opens a delete confirmation below for this profile.",
            key="delete_profile_button",
        ):
            _close_profile_blocks()
            st.session_state["deleting_profile_id"] = profile.get("id")
            st.rerun()
    with col3:
        if st.button(
            "\uff0b New",
            width="stretch",
            help="Opens a create block below.",
            key="new_profile_button",
        ):
            _close_profile_blocks()
            st.session_state["creating_profile"] = True
            st.rerun()
    with col4:
        if st.button(
            "\u29c9 Shallow Clone",
            width="stretch",
            help=(
                "Copy only this profile's type and configuration. "
                "The clone is not linked to any monitors."
            ),
        ):
            _close_profile_blocks()
            message, kind = _clone_profile(sqlite_handler, profile, deep=False)
            st.session_state["flash"] = (kind, message)
            st.rerun()
    with col5:
        if st.button(
            "\u29c9 Deep Clone",
            width="stretch",
            help=(
                "Copy this profile's type and configuration and link the "
                "clone to the same monitors as the original."
            ),
        ):
            _close_profile_blocks()
            message, kind = _clone_profile(sqlite_handler, profile, deep=True)
            st.session_state["flash"] = (kind, message)
            st.rerun()
    with col6:
        if st.button(
            "\U0001f9ea Test",
            width="stretch",
            help="Test results are shown in the message box at the top.",
        ):
            _close_profile_blocks()
            profile_name = profile.get("name", "N/A")
            with st.spinner(f"Testing profile '{profile_name}'\u2026"):
                output, ok = _test_profile(profile)
            st.session_state["flash"] = ("success" if ok else "error", output)
            st.rerun()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def _render_delete(
    sqlite_handler: SQLiteHandler,
    profile: dict,
) -> None:
    """Render the delete control with a confirmation step."""
    profile_name = profile.get("name", "N/A")
    profile_id = profile.get("id", 0)

    with st.expander("Delete profile", expanded=True):
        monitors = sqlite_handler.get_monitors_for_profile(profile_id)
        if monitors:
            linked_names = ", ".join(m.get("name", "N/A") for m in monitors)
            st.warning(
                f"Profile '{profile_name}' is linked to monitors: {linked_names}. "
                "Deleting it will unlink those monitors."
            )

        st.warning(f"Delete profile '{profile_name}'? This cannot be undone.")
        if st.button("Confirm Delete", type="secondary", key="confirm_delete_profile"):
            if sqlite_handler.delete_profile(profile_id=profile_id):
                st.session_state["flash"] = (
                    "success",
                    f"Profile '{profile_name}' deleted.",
                )
                st.session_state["deleting_profile_id"] = None
            else:
                st.session_state["flash"] = (
                    "error",
                    f"Profile '{profile_name}' not deleted.",
                )
            st.rerun()


# ---------------------------------------------------------------------------
# Import rclone profiles
# ---------------------------------------------------------------------------


def _import_config_summary(section: dict) -> str:
    """Return a brief masked summary of an rclone section for the import list."""
    items: list[str] = []
    for key in section:
        if key == "type" or key in _META_CONFIG_KEYS:
            continue
        items.append(f"{key}={profile_display.masked_value(key, section[key])}")
    if not items:
        return "—"
    if len(items) > 6:
        return "{" + ", ".join(items[:6]) + ", …}"
    return "{" + ", ".join(items) + "}"


def _run_import(
    sqlite_handler: SQLiteHandler,
    config: rclone_importer.RcloneConfig,
    names: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Import ``names`` from the rclone config; return imported, failed, skips."""
    imported: list[str] = []
    failed: list[str] = []
    skipped_keys: list[str] = []
    for name in names:
        profile_type, profile_config, skipped = rclone_importer.build_profile(
            name, config.sections.get(name, {})
        )
        for key in skipped:
            skipped_keys.append(f"{name}: {key}")
        try:
            new_id = sqlite_handler.add_profile(
                name=name,
                profile_type=profile_type,
                config=profile_config,
            )
        except sqlite3.IntegrityError:
            new_id = None
        if new_id is not None:
            imported.append(name)
        else:
            failed.append(name)
    return imported, failed, skipped_keys


def _flash_import_result(
    imported: list[str],
    failed: list[str],
    skipped_keys: list[str],
) -> None:
    """Flash the outcome of an import and rerun the page."""
    parts: list[str] = []
    kind = "success"
    if imported:
        parts.append(f"Imported: {', '.join(imported)}.")
    if failed:
        parts.append(f"Failed: {', '.join(failed)}.")
        kind = "error"
    if skipped_keys:
        parts.append("Skipped unexpected keys: " + ", ".join(skipped_keys) + ".")
    if not parts:
        parts.append("No profiles imported.")
    st.session_state["flash"] = (kind, " ".join(parts))
    st.rerun()


def _render_import(sqlite_handler: SQLiteHandler) -> None:
    """Render the rclone profile import block as a selectable list."""
    with st.expander("Import rclone profiles"):
        st.caption(
            "Imports profiles from an rclone.conf file that are not yet in "
            "MonitorHub.  Imported profiles are rclone-managed."
        )
        default_path = rclone_importer.default_rclone_config_path()
        path_text = st.text_input(
            "rclone.conf path",
            value=str(default_path),
            key="import_rclone_config_path",
        )

        config = rclone_importer.read_rclone_config(
            Path(path_text.strip() or str(default_path))
        )
        if not config.is_usable:
            for message in config.errors:
                if message.startswith("Corrupt rclone config"):
                    st.error(message)
                else:
                    st.warning(message)
            return

        existing_names = {
            p.get("name", "") for p in sqlite_handler.get_profiles()
        }
        importable = rclone_importer.importable_profile_names(
            config.sections, existing_names
        )
        if not importable:
            st.info("No profiles to import.")
            return

        selection = st.session_state.get("import_selection")
        selection_reset = selection is None or set(selection) != set(importable)
        if selection_reset:
            selection = {name: True for name in importable}

        set_all = st.session_state.pop("import_set_all", None)
        if set_all is not None:
            selection = {name: set_all for name in importable}

        st.session_state["import_selection"] = selection

        rows = [
            {
                "Import": selection[name],
                "Name": name,
                "Type": config.sections[name].get("type", ""),
                "Config": _import_config_summary(config.sections[name]),
            }
            for name in importable
        ]

        # Reset the editor's persisted per-row edits whenever the selection was
        # replaced (initial load, the importable set changed, or a
        # select/deselect-all click) so stale edits don't override the new base.
        if selection_reset or set_all is not None:
            st.session_state.pop("import_rclone_profiles", None)

        edited = st.data_editor(
            rows,
            num_rows="fixed",
            hide_index=True,
            key="import_rclone_profiles",
            column_config={
                "Import": st.column_config.CheckboxColumn("Import", default=False),
                "Name": st.column_config.TextColumn("Name"),
                "Type": st.column_config.TextColumn("Type"),
                "Config": st.column_config.TextColumn("Config"),
            },
            disabled=["Name", "Type", "Config"],
        )

        st.session_state["import_selection"] = {
            row["Name"]: bool(row.get("Import")) for row in edited
        }
        selected = [
            name
            for name in importable
            if st.session_state["import_selection"].get(name)
        ]

        col1, col2, _spacer = st.columns([1, 1, 2], gap="small")
        with col1:
            if st.button(
                "Select all profiles",
                disabled=len(selected) == len(importable),
                width="stretch",
            ):
                st.session_state["import_set_all"] = True
                st.rerun()
        with col2:
            if st.button(
                "Deselect all profiles",
                disabled=not selected,
                width="stretch",
            ):
                st.session_state["import_set_all"] = False
                st.rerun()

        import_col, _import_spacer = st.columns([1, 3], gap="small")
        with import_col:
            if st.button(
                "Import selected profiles",
                type="primary",
                disabled=not selected,
                width="stretch",
            ):
                imported, failed, skipped = _run_import(
                    sqlite_handler, config, selected
                )
                _flash_import_result(imported, failed, skipped)


def _close_profile_blocks() -> None:
    """Close any open profile new/edit/delete block.

    Used both when the selection changes and when an unrelated action button
    (clone/test) is clicked, so at most one block is ever open.
    """
    st.session_state["creating_profile"] = False
    st.session_state["editing_profile_id"] = None
    st.session_state["deleting_profile_id"] = None


def main() -> None:
    st.set_page_config(page_title="Profiles", page_icon="\U0001f4cb", layout="wide")
    st.title("\U0001f4cb Profiles")
    _flash()

    sqlite_handler = _resources()
    profiles = sqlite_handler.get_profiles()

    # -------------------------------------------------------------------
    # Filters
    # -------------------------------------------------------------------
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        category_filter = st.selectbox(
            "Category",
            [
                "All",
                reference_data.PROFILE_CATEGORY_REMOTE,
                reference_data.PROFILE_CATEGORY_COMMAND,
            ],
        )
    with filter_col2:
        db_types = sorted(
            {p.get("profile_type", "") for p in profiles if p.get("profile_type")}
        )
        type_filter = st.selectbox("Type", ["All", *db_types])

    visible = [
        p
        for p in profiles
        if (
            category_filter == "All"
            or reference_data.get_profile_category(p.get("profile_type", ""))
            == category_filter
        )
        and (type_filter == "All" or p.get("profile_type") == type_filter)
    ]

    if visible:
        st.dataframe(_profile_rows(visible), width="stretch", hide_index=True)
    else:
        st.info("No profiles match the current filters.")

    # -------------------------------------------------------------------
    # Import rclone profiles — always available.
    # -------------------------------------------------------------------
    _render_import(sqlite_handler)

    if not profiles:
        st.info("No profiles yet \u2014 create one with the New button below.")
        if st.button("\uff0b New", key="new_profile_empty_button"):
            _close_profile_blocks()
            st.session_state["creating_profile"] = True
            st.rerun()
        if st.session_state.get("creating_profile"):
            _render_profile_form(
                sqlite_handler, editing=None, key_prefix="new_profile"
            )
        return

    # -------------------------------------------------------------------
    # Profile selector and management
    # -------------------------------------------------------------------
    labels = {f"{p.get('id')}: {p.get('name', 'N/A')}": p for p in profiles}
    selected_label = st.selectbox(
        "Select a profile to manage",
        list(labels.keys()),
        on_change=_close_profile_blocks,
    )
    selected = labels[selected_label]

    linked_monitors = sqlite_handler.get_monitors_for_profile(selected.get("id", 0))
    if linked_monitors:
        st.caption("Linked monitors (click to open in the Monitors page):")
        for monitor in linked_monitors:
            monitor_id = monitor.get("id")
            st.page_link(
                "pages/monitors.py",
                label=f"{monitor.get('name', 'N/A')} (ID {monitor_id})",
                icon="📡",
                query_params={"monitor_id": str(monitor_id)},
            )
    else:
        st.caption("No monitors linked to this profile.")

    _render_actions(sqlite_handler, selected)

    # -------------------------------------------------------------------
    # New profile form \u2014 only while a create is in progress.
    # -------------------------------------------------------------------
    if st.session_state.get("creating_profile"):
        _render_profile_form(sqlite_handler, editing=None, key_prefix="new_profile")

    # -------------------------------------------------------------------
    # Edit profile form \u2014 only while an edit is in progress.
    # -------------------------------------------------------------------
    editing_id = st.session_state.get("editing_profile_id")
    editing = next((p for p in profiles if p.get("id") == editing_id), None)
    if editing:
        _render_profile_form(
            sqlite_handler, editing=editing, key_prefix="edit_profile"
        )

    # -------------------------------------------------------------------
    # Delete profile confirmation \u2014 only while a delete is in progress.
    # -------------------------------------------------------------------
    deleting_id = st.session_state.get("deleting_profile_id")
    deleting = next((p for p in profiles if p.get("id") == deleting_id), None)
    if deleting:
        _render_delete(sqlite_handler, deleting)


main()