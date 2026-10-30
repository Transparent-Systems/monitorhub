"""Monitors page for the MonitorHub web GUI.

Manages the full monitor lifecycle: list, create, edit, delete, start, and
stop.  Talks to the backend (``app.utils`` and ``app.monitor``) directly and
never imports ``app.cli``.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import threading
import time
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

from app.monitor.monitor_process_manager import MonitorProcessManager
from app.utils import monitor_validator, reference_data
from app.utils.app_config import AppConfig
from app.utils.constants import (
    MONITOR_STATUS_RUNNING,
    MONITOR_STATUS_STOP,
    MONITOR_STATUS_STOPPED,
    MONITOR_TYPE_BACKUP,
    MONITOR_TYPE_INSTANT,
    MONITOR_TYPE_RESTORE,
)
from app.utils.generic_util import is_interval_valid
from app.utils.monitor_config import build_monitor_config
from app.utils.project_paths import project_conf
from app.utils.sqlite_handler import SQLiteHandler
from app.webgui.database import database_ready
from app.webgui.messages import start_result_message

# Mirrors MonitorCommands.STOP_GRACE_SECONDS so a web-initiated stop behaves
# identically to the CLI: graceful shutdown first, then SIGTERM/SIGKILL
# escalation once the grace period expires.
STOP_GRACE_SECONDS = 15

# How long to wait (in seconds) for a freshly-launched monitor child process to
# set its status to "running" before re-rendering the page. The child boots
# (imports boto3/watchdog, opens the database) before writing the status, so an
# immediate re-read would show the stale "stopped" state.
#
# The wait ends as soon as the child reports "running" (or dies), so a generous
# ceiling costs nothing on a fast machine - it only bounds how long a *hung*
# child keeps the page waiting. It has to cover a onefile child unpacking the
# whole bundle before it can run: about 10 s on a Windows VM.
START_WAIT_SECONDS = 30

# How long a freshly-launched monitor must stay alive after reporting "running"
# before the start is treated as successful. The child writes "running" before
# its handler starts, so a startup crash (e.g. a missing monitor path) would
# otherwise look like a successful start.
START_SETTLE_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Backend resources
# ---------------------------------------------------------------------------


def _resources() -> tuple[SQLiteHandler, MonitorProcessManager]:
    """Build (once) and return the shared backend resources.

    ``db_dir`` and ``log_config`` resolve exactly as the CLI does, so the web
    GUI operates on the same database and launches monitor children with the
    same logging configuration.
    """
    if "sqlite_handler" not in st.session_state or "process_manager" not in st.session_state:
        db_dir = AppConfig().get_default_db_dir(fallback="data")
        log_config = str(project_conf("log.yaml"))
        logger = logging.getLogger("app.webgui")
        st.session_state["sqlite_handler"] = SQLiteHandler(logger=logger, db_dir=db_dir)
        st.session_state["process_manager"] = MonitorProcessManager(
            logger=logger,
            db_dir=db_dir,
            log_config=log_config,
            log_level=None,
        )
    return st.session_state["sqlite_handler"], st.session_state["process_manager"]


# ---------------------------------------------------------------------------
# Monitor lifecycle operations
# ---------------------------------------------------------------------------


def _start_monitor(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    monitor: dict,
) -> tuple[str, bool]:
    """Start one monitor; return (message, ok)."""
    monitor_id = monitor.get("id", 0)
    monitor_name = monitor.get("name", "N/A")
    current_status = monitor.get("status")
    current_pid = int(monitor.get("pid") or 0)

    pid_alive = current_pid != 0 and process_manager.is_alive(monitor_id, current_pid)
    if pid_alive:
        if current_status == MONITOR_STATUS_RUNNING:
            return (
                f"Monitor '{monitor_name}' (id={monitor_id}) is already running "
                f"(pid={current_pid}).",
                False,
            )
        return (
            f"Monitor '{monitor_name}' (id={monitor_id}) is still shutting down "
            f"(status='{current_status}', pid={current_pid}).",
            False,
        )

    if current_status == MONITOR_STATUS_RUNNING:
        # Stale 'running' with no live process: clear it before starting.
        sqlite_handler.update_monitor_status(monitor_id, MONITOR_STATUS_STOPPED)
        sqlite_handler.update_monitor_pid(monitor_id, 0)

    path_error = monitor_validator.monitor_path_is_valid(
        monitor.get("monitor_path", "")
    )
    if path_error:
        return (
            f"Monitor '{monitor_name}' (id={monitor_id}) cannot start: "
            f"{path_error}",
            False,
        )

    # A monitor with no profiles starts, finds nothing to dispatch to and exits,
    # so refuse to launch it rather than report a start that is guaranteed to
    # fail ("exited during startup").
    profiles_error = monitor_validator.profiles_required_error(
        sqlite_handler.get_profiles_for_monitor(monitor_id=monitor_id)
    )
    if profiles_error:
        return (
            f"Monitor '{monitor_name}' (id={monitor_id}) cannot start: "
            f"{profiles_error}",
            False,
        )

    if process_manager.launch(monitor):
        return f"Monitor '{monitor_name}' (id={monitor_id}) started.", True
    return f"Failed to start monitor '{monitor_name}' (id={monitor_id}).", False


def _stop_monitor(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    monitor: dict,
    immediate: bool = False,
) -> tuple[str, bool]:
    """Stop one monitor; return (message, ok)."""
    monitor_id = monitor.get("id", 0)
    monitor_name = monitor.get("name", "N/A")
    current_status = monitor.get("status", "N/A")
    current_pid = int(monitor.get("pid") or 0)

    if current_status == MONITOR_STATUS_STOPPED:
        return f"Monitor '{monitor_name}' (id={monitor_id}) is already stopped.", False

    if immediate:
        if current_pid and current_pid != 0:
            if not process_manager.force_kill(current_pid, monitor_name):
                return (
                    f"Could not force-kill monitor '{monitor_name}' (pid={current_pid}).",
                    False,
                )
        sqlite_handler.update_monitor_status(monitor_id, MONITOR_STATUS_STOPPED)
        sqlite_handler.update_monitor_pid(monitor_id, 0)
        process_manager.reap(monitor_id)
        return f"Monitor '{monitor_name}' (id={monitor_id}) stopped.", True

    sqlite_handler.update_monitor_status(monitor_id, MONITOR_STATUS_STOP)
    if not current_pid or current_pid == 0:
        return (
            f"Stop signal sent to monitor '{monitor_name}' (id={monitor_id}); "
            "the monitor will set its status to 'stopped' when it exits.",
            True,
        )

    if process_manager.wait_for_exit(current_pid, STOP_GRACE_SECONDS, monitor_id=monitor_id):
        sqlite_handler.update_monitor_status(monitor_id, MONITOR_STATUS_STOPPED)
        sqlite_handler.update_monitor_pid(monitor_id, 0)
        process_manager.reap(monitor_id)
        return f"Monitor '{monitor_name}' (id={monitor_id}) stopped gracefully.", True

    process_manager.escalate_stop(current_pid, monitor_name, monitor_id)
    sqlite_handler.update_monitor_status(monitor_id, MONITOR_STATUS_STOPPED)
    sqlite_handler.update_monitor_pid(monitor_id, 0)
    process_manager.reap(monitor_id)
    return f"Monitor '{monitor_name}' (id={monitor_id}) stopped (escalated).", True


def _clone_monitor(
    sqlite_handler: SQLiteHandler,
    monitor: dict,
) -> tuple[str, str]:
    """Clone a monitor; return (message, kind) where kind is success/warning/error.

    Delegates to :meth:`SQLiteHandler.clone_monitor`, which copies the path,
    remote path, type, config, and profile links and starts the clone as
    ``stopped`` with a fresh auto-incremented name.
    """
    source_id = monitor.get("id", 0)
    source_name = monitor.get("name", "N/A")

    try:
        new_id = sqlite_handler.clone_monitor(source_id)
    except sqlite3.IntegrityError:
        return (
            f"Could not clone monitor '{source_name}': the generated name already exists.",
            "warning",
        )

    if new_id is None:
        return f"Could not clone monitor '{source_name}'.", "error"

    clone = sqlite_handler.get_monitor(monitor_id=new_id)
    new_name = clone.get("name", "N/A") if clone else "N/A"
    return f"Monitor '{new_name}' created as a clone of '{source_name}'.", "success"


def _start_all_monitors(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    monitors: list[dict],
) -> tuple[str, bool]:
    """Start every monitor; return (summary, ok).

    Reuses :func:`_start_monitor` per monitor, then waits (bounded) for the
    launched children to report ``running`` so the page re-renders fresh.
    """
    started = 0
    skipped = 0
    failed = 0
    launched_ids: list[int] = []
    for monitor in monitors:
        message, ok = _start_monitor(sqlite_handler, process_manager, monitor)
        if ok:
            started += 1
            launched_ids.append(monitor.get("id", 0))
        elif "already running" in message or "shutting down" in message:
            skipped += 1
        else:
            failed += 1

    # Wait for the launched children to report 'running' and stay alive. The
    # settle window catches a child that writes 'running' and then crashes.
    deadline = time.monotonic() + START_WAIT_SECONDS
    pending = set(launched_ids)
    running_since: dict[int, float] = {}
    seen_alive: set[int] = set()
    while pending and time.monotonic() < deadline:
        for monitor_id in list(pending):
            monitor = sqlite_handler.get_monitor(monitor_id=monitor_id)
            alive = _is_monitor_process_alive(process_manager, monitor_id, monitor)
            if alive:
                seen_alive.add(monitor_id)
            elif monitor_id in seen_alive or monitor_id in process_manager.tracked_processes:
                # It was alive and has now exited, or it was launched and
                # exited before writing its PID: a startup crash.
                pending.discard(monitor_id)
                continue
            if (
                monitor
                and monitor.get("status") == MONITOR_STATUS_RUNNING
                and alive
            ):
                first_seen = running_since.setdefault(monitor_id, time.monotonic())
                if time.monotonic() - first_seen >= START_SETTLE_SECONDS:
                    pending.discard(monitor_id)
            else:
                running_since.pop(monitor_id, None)
        if pending:
            time.sleep(0.1)

    # A launched child that is no longer alive crashed during startup.
    for monitor_id in launched_ids:
        latest = sqlite_handler.get_monitor(monitor_id=monitor_id)
        if _is_monitor_process_alive(process_manager, monitor_id, latest):
            continue
        _clear_stale_monitor_state(sqlite_handler, process_manager, monitor_id)
        started -= 1
        failed += 1

    parts = []
    if started:
        parts.append(f"{started} started")
    if skipped:
        parts.append(f"{skipped} skipped")
    if failed:
        parts.append(f"{failed} failed")
    summary = "Start all: " + (", ".join(parts) if parts else "nothing to do") + "."
    return summary, failed == 0


def _stop_all_monitors(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    monitors: list[dict],
) -> tuple[str, bool]:
    """Stop every monitor gracefully (batch); return (summary, ok).

    Mirrors the CLI's ``monitor stop`` (no args): request a graceful stop on all
    non-stopped monitors first, then wait once against a shared deadline and
    escalate only the survivors.
    """
    graceful: list[tuple[int, str, int]] = []  # (pid, name, monitor_id)
    already_stopped = 0

    for monitor in monitors:
        monitor_id = monitor.get("id", 0)
        name = monitor.get("name", "N/A")
        status = monitor.get("status", "N/A")
        pid = int(monitor.get("pid") or 0)
        if status == MONITOR_STATUS_STOPPED:
            already_stopped += 1
            continue
        sqlite_handler.update_monitor_status(monitor_id, MONITOR_STATUS_STOP)
        if pid and pid != 0:
            graceful.append((pid, name, monitor_id))

    deadline = time.monotonic() + STOP_GRACE_SECONDS
    for pid, name, monitor_id in graceful:
        remaining = max(0.0, deadline - time.monotonic())
        if not process_manager.wait_for_exit(pid, remaining, monitor_id=monitor_id):
            process_manager.escalate_stop(pid, name, monitor_id)
        sqlite_handler.update_monitor_status(monitor_id, MONITOR_STATUS_STOPPED)
        sqlite_handler.update_monitor_pid(monitor_id, 0)
        process_manager.reap(monitor_id)

    summary = f"Stop all: {len(graceful)} stopped"
    if already_stopped:
        summary += f", {already_stopped} already stopped"
    summary += "."
    return summary, True


def _is_monitor_process_alive(
    process_manager: MonitorProcessManager,
    monitor_id: int,
    monitor: dict | None,
) -> bool:
    """Return whether a launched monitor process is alive.

    Prefers the tracked ``Popen`` handle so a child that has not yet written
    its PID to the database (or has already exited during startup) is
    classified correctly.
    """
    process = process_manager.tracked_processes.get(monitor_id)
    if process is not None:
        return process.poll() is None
    return bool(monitor and process_manager.is_monitor_running(monitor))


def _wait_for_running(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    monitor_id: int,
    timeout: float = START_WAIT_SECONDS,
) -> bool:
    """Wait until the monitor reports 'running' and stays alive.

    Called after ``launch()`` succeeds. The child sets its status to
    ``running`` before its handler starts, so a status-only check can succeed
    even when the child immediately crashes (for example when the monitor path
    does not exist). The process must remain alive for
    ``START_SETTLE_SECONDS`` before the start is treated as successful.
    """
    deadline = time.monotonic() + timeout
    running_since: float | None = None
    seen_alive = False
    while time.monotonic() < deadline:
        monitor = sqlite_handler.get_monitor(monitor_id=monitor_id)
        alive = _is_monitor_process_alive(process_manager, monitor_id, monitor)
        if alive:
            seen_alive = True
        elif seen_alive or monitor_id in process_manager.tracked_processes:
            # It was alive and has now exited, or it was launched and exited
            # before writing its PID: a startup crash, not a slow boot.
            return False
        if monitor and monitor.get("status") == MONITOR_STATUS_RUNNING and alive:
            if running_since is None:
                running_since = time.monotonic()
            elif time.monotonic() - running_since >= START_SETTLE_SECONDS:
                return True
        else:
            running_since = None
        time.sleep(0.1)
    return False


def _clear_stale_monitor_state(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    monitor_id: int,
) -> None:
    """Mark a monitor stopped when its stored PID is no longer alive.

    A child records status='running' and its PID before its handler starts, so
    a startup crash can leave a stale 'running' row behind.
    """
    monitor = sqlite_handler.get_monitor(monitor_id=monitor_id)
    if monitor and process_manager.is_monitor_running(monitor):
        return
    sqlite_handler.update_monitor_status(monitor_id, MONITOR_STATUS_STOPPED)
    sqlite_handler.update_monitor_pid(monitor_id, 0)


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


def _monitor_rows(monitors: list[dict], running_ids: set[int]) -> list[dict]:
    """Return display-ready rows for the monitor table.

    ``running_ids`` identifies monitors with a live process so a stale
    'running' status (dead PID) is not shown as if the monitor were active.
    """
    rows: list[dict] = []
    for monitor in monitors:
        status = monitor.get("status", "N/A")
        if status == MONITOR_STATUS_RUNNING and monitor.get("id") not in running_ids:
            status = f"{status} (stale)"
        rows.append(
            {
                "ID": monitor.get("id"),
                "Name": monitor.get("name", "N/A"),
                "Type": monitor.get("monitor_type", "N/A"),
                "Status": status,
                "Path": monitor.get("monitor_path", "N/A"),
                "PID": monitor.get("pid", 0),
                "Last run": monitor.get("last_run", ""),
            }
        )
    return rows


def _validate_monitor_form(
    sqlite_handler: SQLiteHandler,
    name: str,
    monitor_path: str,
    remote_path: str,
    monitor_type: str,
    interval: str,
    editing: dict | None,
) -> str | None:
    """Return an error message when the form is invalid, otherwise None."""
    if not name.strip():
        return "Monitor name cannot be empty."
    path_error = monitor_validator.monitor_path_is_valid(monitor_path)
    if path_error:
        return path_error
    if not remote_path.strip():
        return "Remote path cannot be empty."

    existing = sqlite_handler.get_monitor(monitor_name=name)
    if existing and (editing is None or existing.get("id") != editing.get("id")):
        return f"Monitor name '{name}' already exists."

    if monitor_type in (MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE) and not is_interval_valid(interval.strip()):
        return (
            f"Invalid interval: '{interval}'. "
            "Interval must be a non-negative number with an optional unit (e.g. 10, 10s, 10m, 2h, 1d)."
        )
    return None


def _render_monitor_form(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    profiles: list[dict],
    editing: dict | None,
    key_prefix: str,
) -> None:
    """Render a create/edit form inside an expander.

    ``key_prefix`` scopes every widget key so the "New monitor" and
    "Edit monitor" forms can both be rendered without a DuplicateWidgetID.
    """
    monitor_types = reference_data.MONITOR_TYPES
    type_names = [name for name, _ in monitor_types]

    current = editing or {}
    config = current.get("config") or {}
    current_type = current.get("monitor_type") or MONITOR_TYPE_INSTANT
    is_edit = editing is not None

    with st.expander("Edit monitor" if is_edit else "New monitor", expanded=True):
        if is_edit and process_manager.is_monitor_running(editing):
            st.warning(
                "This monitor is running. Changes will take effect only after it "
                "is restarted (stop, then start)."
            )
        # The type selector lives outside the form so changing it re-runs the
        # page immediately, which enables/disables the interval field live.
        # (Form widgets batch their input and only re-run on submit.)
        type_index = type_names.index(current_type) if current_type in type_names else 0
        monitor_type = st.selectbox(
            "Monitor type", type_names, index=type_index, key=f"{key_prefix}_type"
        )

        interval_disabled = monitor_type not in (MONITOR_TYPE_BACKUP, MONITOR_TYPE_RESTORE)

        with st.form(key_prefix, clear_on_submit=False):
            name = st.text_input(
                "Name", value=current.get("name", ""), key=f"{key_prefix}_name"
            ).strip()
            monitor_path = st.text_input(
                "Monitor path",
                value=current.get("monitor_path", ""),
                key=f"{key_prefix}_path",
            ).strip()
            remote_path = st.text_input(
                "Remote path",
                value=current.get("remote_path", ""),
                key=f"{key_prefix}_remote",
            ).strip()

            interval = st.text_input(
                "Interval (e.g. 10m, 2h, 1d)",
                value=str(config.get("interval", "")),
                help="Required for backup/restore monitors.",
                disabled=interval_disabled,
                key=f"{key_prefix}_interval",
            )
            exclude_patterns = st.text_input(
                "Exclude patterns (comma-separated)",
                value=", ".join(config.get("exclude_patterns", [])),
                help="File/folder patterns to skip.",
                key=f"{key_prefix}_exclude",
            )

            profile_options = {f"{p.get('id')}: {p.get('name', 'N/A')}": p for p in profiles}
            monitor_id = current.get("id", 0)
            selected_ids = (
                {p.get("id") for p in sqlite_handler.get_profiles_for_monitor(monitor_id)}
                if is_edit
                else set()
            )
            selected_labels = [
                label for label, p in profile_options.items() if p.get("id") in selected_ids
            ]
            if not profile_options:
                # An empty picker would otherwise be a dead end: the monitor
                # needs a profile, but there is none to choose.
                st.warning(
                    "No profiles exist yet. Create one on the Profiles page (or "
                    "with 'mhub profile new') and it becomes selectable here."
                )
            attached = st.multiselect(
                "Attach profiles",
                list(profile_options.keys()),
                default=selected_labels,
                key=f"{key_prefix}_profiles",
            )

            submitted = st.form_submit_button("Save")

        if st.button("Cancel edit" if is_edit else "Cancel", key=f"{key_prefix}_cancel"):
            _close_monitor_blocks()
            st.rerun()

        if submitted:
            error = _validate_monitor_form(
                sqlite_handler, name, monitor_path, remote_path, monitor_type, interval, editing
            )
            # A monitor with no profiles cannot run, so the form refuses to save
            # one. Only enforced when profiles exist to attach: a database with
            # no profiles at all would otherwise make existing monitors
            # impossible to edit.
            if error is None and profile_options:
                error = monitor_validator.profiles_required_error(
                    [profile_options[label] for label in attached]
                )
            if error:
                st.error(error)
                return

            new_config = build_monitor_config(monitor_type, interval, exclude_patterns)

            if editing:
                updated_id = sqlite_handler.update_monitor(
                    monitor_id=monitor_id,
                    name=name,
                    monitor_path=monitor_path,
                    remote_path=remote_path,
                    monitor_type=monitor_type,
                    config=new_config,
                    status=editing.get("status", MONITOR_STATUS_STOPPED),
                    pid=editing.get("pid", 0),
                )
                if updated_id is None:
                    st.error(f"Monitor '{name}' could not be updated.")
                    return
                st.session_state["flash"] = ("success", f"Monitor '{name}' updated.")
            else:
                try:
                    monitor_id = sqlite_handler.add_monitor(
                        name=name,
                        monitor_path=monitor_path,
                        remote_path=remote_path,
                        monitor_type=monitor_type,
                        config=new_config,
                        status=MONITOR_STATUS_STOPPED,
                    )
                except sqlite3.IntegrityError:
                    st.error(f"Monitor name '{name}' already exists.")
                    return
                if monitor_id is None:
                    st.error(f"Monitor '{name}' could not be created.")
                    return
                st.session_state["flash"] = ("success", f"Monitor '{name}' created.")
                st.session_state["creating_monitor"] = False

            # Reconcile profile attachments.
            chosen_ids = {profile_options[label].get("id") for label in attached}
            existing_ids = {
                p.get("id") for p in sqlite_handler.get_profiles_for_monitor(monitor_id)
            }
            for profile_id in chosen_ids - existing_ids:
                sqlite_handler.add_monitor_profile_map(monitor_id, profile_id)
            for profile_id in existing_ids - chosen_ids:
                sqlite_handler.delete_monitor_profile_map(monitor_id, profile_id)

            st.rerun()


def _render_actions(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    monitor: dict,
) -> None:
    """Render the start/stop, edit, delete, new and clone actions."""
    # A monitor is live while its stored PID is alive, so a graceful stop that
    # is still shutting down (status 'stop') keeps showing Stop rather than
    # offering Start before the old process has exited.
    monitor_running = process_manager.is_monitor_running(monitor)
    monitor_stopping = (
        monitor.get("status") == MONITOR_STATUS_STOP and monitor_running
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if monitor_stopping:
            if st.button(
                "■ Stop now",
                width="stretch",
                help="The monitor is taking too long to stop. Terminate it immediately.",
            ):
                _close_monitor_blocks()
                message, ok = _stop_monitor(
                    sqlite_handler, process_manager, monitor, immediate=True
                )
                st.session_state["flash"] = ("success" if ok else "error", message)
                st.rerun()
        elif monitor_running:
            if st.button(
                "■ Stop",
                width="stretch",
                help="Stop this monitor gracefully.",
            ):
                _close_monitor_blocks()
                result: list[tuple[str, bool]] = []
                thread = threading.Thread(
                    target=lambda: result.append(
                        _stop_monitor(sqlite_handler, process_manager, monitor)
                    )
                )
                thread.start()
                with st.spinner("Stopping monitor…"):
                    while thread.is_alive():
                        time.sleep(0.2)
                if result:
                    message, ok = result[0]
                    st.session_state["flash"] = ("success" if ok else "error", message)
                st.rerun()
        else:
            if st.button(
                "▶ Start",
                width="stretch",
                help="Start this monitor.",
            ):
                _close_monitor_blocks()
                monitor_id = monitor.get("id", 0)
                monitor_name = monitor.get("name", "N/A")
                message, ok = _start_monitor(sqlite_handler, process_manager, monitor)
                kind = "success" if ok else "error"
                if ok:
                    # Wait for the child process to report 'running' and stay
                    # alive before reporting a successful start.
                    with st.spinner("Starting monitor…"):
                        settled = _wait_for_running(
                            sqlite_handler, process_manager, monitor_id
                        )
                    latest = sqlite_handler.get_monitor(monitor_id=monitor_id)
                    alive = _is_monitor_process_alive(
                        process_manager, monitor_id, latest
                    )
                    if not alive:
                        _clear_stale_monitor_state(
                            sqlite_handler, process_manager, monitor_id
                        )
                    kind, message = start_result_message(
                        monitor_name, monitor_id, alive=alive, settled=settled
                    )
                    ok = alive
                st.session_state["flash"] = (kind, message)
                st.rerun()
    with col2:
        if st.button(
            "✎ Edit",
            width="stretch",
            help="Opens an edit block below for this monitor.",
        ):
            _close_monitor_blocks()
            st.session_state["editing_monitor_id"] = monitor.get("id")
            st.rerun()
    with col3:
        if st.button(
            "🗑 Delete",
            width="stretch",
            help="Opens a delete confirmation below for this monitor.",
            key="delete_monitor_button",
        ):
            _close_monitor_blocks()
            st.session_state["deleting_monitor_id"] = monitor.get("id")
            st.rerun()
    with col4:
        if st.button(
            "＋ New",
            width="stretch",
            help="Opens a create block below.",
            key="new_monitor_button",
        ):
            _close_monitor_blocks()
            st.session_state["creating_monitor"] = True
            st.rerun()
    with col5:
        if st.button(
            "⧉ Clone",
            width="stretch",
            help="Create a copy of this monitor and link to profiles of original monitor.",
        ):
            _close_monitor_blocks()
            message, kind = _clone_monitor(sqlite_handler, monitor)
            st.session_state["flash"] = (kind, message)
            st.rerun()


def _render_delete(
    sqlite_handler: SQLiteHandler,
    process_manager: MonitorProcessManager,
    monitor: dict,
) -> None:
    """Render the delete confirmation, blocking deletion while the monitor runs."""
    with st.expander("Delete monitor", expanded=True):
        if process_manager.is_monitor_running(monitor):
            st.warning(
                f"Cannot delete monitor '{monitor.get('name', 'N/A')}': it is running. "
                "Stop it first."
            )
            return
        st.warning(f"Delete monitor '{monitor.get('name', 'N/A')}'?")
        if st.button("Confirm Delete", type="secondary", key="confirm_delete_monitor"):
            if sqlite_handler.delete_monitor(monitor_id=monitor.get("id", 0)):
                st.session_state["flash"] = (
                    "success",
                    f"Monitor '{monitor.get('name', 'N/A')}' deleted.",
                )
                st.session_state["deleting_monitor_id"] = None
            else:
                st.session_state["flash"] = (
                    "error",
                    f"Monitor '{monitor.get('name', 'N/A')}' not deleted.",
                )
            st.rerun()


def _close_monitor_blocks() -> None:
    """Close any open monitor new/edit/delete block.

    Used both when the selection changes and when an unrelated action button
    (start/stop/clone) is clicked, so at most one block is ever open.
    """
    st.session_state["creating_monitor"] = False
    st.session_state["editing_monitor_id"] = None
    st.session_state["deleting_monitor_id"] = None


def main() -> None:
    st.set_page_config(page_title="Monitors", page_icon="📡", layout="wide")
    st.title("📡 Monitors")
    _flash()

    sqlite_handler, process_manager = _resources()
    if not database_ready(sqlite_handler):
        return

    monitors = sqlite_handler.get_monitors()
    profiles = sqlite_handler.get_profiles()
    # A monitor is live only while its stored PID is alive; status alone can be
    # stale when a child crashes before it can record 'stopped'.
    running_ids = {
        monitor.get("id")
        for monitor in monitors
        if process_manager.is_monitor_running(monitor)
    }

    # Handle navigation from Profiles page (linked-monitor links) — open the
    # target monitor for editing directly instead of requiring a manual select.
    if "monitor_id" in st.query_params:
        try:
            _close_monitor_blocks()
            st.session_state["editing_monitor_id"] = int(st.query_params["monitor_id"])
        except (ValueError, TypeError):
            pass
        del st.query_params["monitor_id"]

    # Global actions: start/stop all monitors (mirrors the CLI's "monitor start"
    # and "monitor stop" with no id/name, which act on every monitor).
    toolbar_col1, toolbar_col2, toolbar_col3 = st.columns(3)
    with toolbar_col1:
        if st.button("▶ Start All", width="stretch"):
            _close_monitor_blocks()
            with st.spinner("Starting monitors…"):
                summary, ok = _start_all_monitors(sqlite_handler, process_manager, monitors)
            st.session_state["flash"] = ("success" if ok else "warning", summary)
            st.rerun()
    with toolbar_col2:
        if st.button("■ Stop All", width="stretch"):
            _close_monitor_blocks()
            result: list[tuple[str, bool]] = []
            thread = threading.Thread(
                target=lambda: result.append(
                    _stop_all_monitors(sqlite_handler, process_manager, monitors)
                )
            )
            thread.start()
            with st.spinner("Stopping monitors…"):
                while thread.is_alive():
                    time.sleep(0.2)
            if result:
                summary, ok = result[0]
                st.session_state["flash"] = ("success" if ok else "warning", summary)
            st.rerun()
    with toolbar_col3:
        # The click itself reruns the page, re-reading the database. Monitor
        # status also changes on its own (scheduled monitors, a monitor that
        # stops itself, a slow child still booting), so a deliberate refresh is
        # always useful.
        st.button(
            "↻ Refresh",
            width="stretch",
            help="Re-read the monitor list and status from the database.",
        )

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        status_filter = st.selectbox(
            "Status",
            ["All", MONITOR_STATUS_RUNNING, MONITOR_STATUS_STOP, MONITOR_STATUS_STOPPED],
        )
    with filter_col2:
        type_names = [name for name, _ in reference_data.MONITOR_TYPES]
        type_filter = st.selectbox("Type", ["All", *type_names])

    visible = [
        m
        for m in monitors
        if (status_filter == "All" or m.get("status") == status_filter)
        and (type_filter == "All" or m.get("monitor_type") == type_filter)
    ]

    if visible:
        st.dataframe(_monitor_rows(visible, running_ids), width="stretch", hide_index=True)
    else:
        st.info("No monitors match the current filters.")

    if not monitors:
        st.info("No monitors yet — create one with the New button below.")
        if st.button("＋ New", key="new_monitor_empty_button"):
            _close_monitor_blocks()
            st.session_state["creating_monitor"] = True
            st.rerun()
        if st.session_state.get("creating_monitor"):
            _render_monitor_form(
                sqlite_handler,
                process_manager,
                profiles,
                editing=None,
                key_prefix="new_monitor",
            )
        return

    labels = {f"{m.get('id')}: {m.get('name', 'N/A')}": m for m in monitors}
    selected_label = st.selectbox(
        "Select a monitor to manage",
        list(labels.keys()),
        on_change=_close_monitor_blocks,
    )
    selected = labels[selected_label]

    selected_status = selected.get("status", "N/A")
    if selected_status == MONITOR_STATUS_RUNNING and selected.get("id") not in running_ids:
        st.warning(
            f"**Status:** `running` (stale — process not running) — "
            f"**PID:** `{selected.get('pid', 0)}`"
        )
    else:
        st.markdown(
            f"**Status:** `{selected_status}` — **PID:** `{selected.get('pid', 0)}`"
        )

    _render_actions(sqlite_handler, process_manager, selected)

    # "New monitor" form — only while a create is in progress.
    if st.session_state.get("creating_monitor"):
        _render_monitor_form(
            sqlite_handler,
            process_manager,
            profiles,
            editing=None,
            key_prefix="new_monitor",
        )

    # "Edit monitor" form — only while an edit is in progress.
    editing_id = st.session_state.get("editing_monitor_id")
    editing = next((m for m in monitors if m.get("id") == editing_id), None)
    if editing:
        _render_monitor_form(
            sqlite_handler, process_manager, profiles, editing=editing, key_prefix="edit_monitor"
        )

    deleting_id = st.session_state.get("deleting_monitor_id")
    deleting = next((m for m in monitors if m.get("id") == deleting_id), None)
    if deleting:
        _render_delete(sqlite_handler, process_manager, deleting)


main()
