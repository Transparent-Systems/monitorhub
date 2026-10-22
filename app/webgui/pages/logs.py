"""Monitor logs page for the MonitorHub web GUI.

Shows the per-monitor console log (``logs/monitor_<id>.log``) for the
selected monitor, with manual and automatic refresh.
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from datetime import datetime
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

from app.monitor.monitor_process_manager import monitor_log_path
from app.utils.app_config import AppConfig
from app.utils.sqlite_handler import SQLiteHandler

# (label, run_every) pairs; None disables automatic refresh.
REFRESH_OPTIONS: dict[str, str | None] = {
    "Off": None,
    "2 seconds": "2s",
    "5 seconds": "5s",
    "10 seconds": "10s",
}
DEFAULT_REFRESH_LABEL = "2 seconds"
LINE_OPTIONS = (50, 200, 500, 1000, 5000)
DEFAULT_LINE_INDEX = 0
# Read this many bytes from the end of the log for each tail.
TAIL_CHUNK_BYTES = 1024 * 1024

# st.code takes a pixel height. Approximate 20 code rows: 14 px code font at
# 1.5 line-height plus the pre block's 1 em top/bottom padding.
LOG_VIEW_ROWS = 20
CODE_LINE_HEIGHT_PX = 21
CODE_VERTICAL_PADDING_PX = 28


def _resources() -> SQLiteHandler:
    """Build (once) and return the shared SQLiteHandler."""
    if "sqlite_handler" not in st.session_state:
        db_dir = AppConfig().get_default_db_dir(fallback="data")
        logger = logging.getLogger("app.webgui")
        st.session_state["sqlite_handler"] = SQLiteHandler(logger=logger, db_dir=db_dir)
    return st.session_state["sqlite_handler"]


def _tail(path: Path, max_lines: int) -> str:
    """Return the last ``max_lines`` lines of ``path``.

    At most ``TAIL_CHUNK_BYTES`` are read from the end, so a growing log does
    not have to be scanned in full on every auto-refresh tick.
    """
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        chunk_size = min(size, TAIL_CHUNK_BYTES)
        handle.seek(size - chunk_size)
        data = handle.read()

    if chunk_size < size:
        # The chunk starts mid-line; drop that partial first line when possible.
        newline = data.find(b"\n")
        if newline != -1:
            data = data[newline + 1 :]

    text = data.decode("utf-8", errors="replace")
    return "".join(deque(text.splitlines(keepends=True), maxlen=max_lines))


def _format_size(size: int) -> str:
    """Return a human-readable file size."""
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024**2:.1f} MB"


def _render_log(monitor_id: int, monitor_name: str, max_lines: int) -> None:
    """Render the tail of the selected monitor's log file."""
    path = monitor_log_path(monitor_id)
    refreshed = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not path.is_file():
        st.info(
            f"No log file yet for '{monitor_name}' (id={monitor_id}). "
            "A log is created when the monitor starts."
        )
        st.caption(f"Expected path: `{path}` — checked at {refreshed}")
        return

    try:
        stat = path.stat()
        text = _tail(path, max_lines)
    except OSError as error:
        st.error(f"Could not read the log file '{path}': {error}")
        return

    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    st.caption(
        f"`{path}` — {_format_size(stat.st_size)} — modified {modified} — "
        f"refreshed {refreshed}"
    )

    if not text.strip():
        st.info("The log file is empty.")
        return

    visible_rows = min(max_lines, LOG_VIEW_ROWS)
    height = visible_rows * CODE_LINE_HEIGHT_PX + CODE_VERTICAL_PADDING_PX
    st.code(text, language=None, line_numbers=True, height=height)


def main() -> None:
    st.set_page_config(page_title="Monitor Logs", page_icon="🧾", layout="wide")
    st.title("🧾 Monitor Logs")

    sqlite_handler = _resources()
    monitors = sqlite_handler.get_monitors()
    if not monitors:
        st.info("No monitors yet — create one on the Monitors page.")
        return

    labels = {
        f"{monitor.get('id')}: {monitor.get('name', 'N/A')}": monitor
        for monitor in monitors
    }

    control_col1, control_col2, control_col3 = st.columns([3, 2, 2])
    with control_col1:
        selected_label = st.selectbox("Monitor", list(labels.keys()))
    with control_col2:
        refresh_label = st.selectbox(
            "Auto-refresh",
            list(REFRESH_OPTIONS.keys()),
            index=list(REFRESH_OPTIONS).index(DEFAULT_REFRESH_LABEL),
            help="Automatically reload the log file.",
        )
    with control_col3:
        max_lines = st.selectbox(
            "Show last",
            LINE_OPTIONS,
            index=DEFAULT_LINE_INDEX,
            format_func=lambda lines: f"{lines} lines",
            help="Only the newest lines are read, so large logs stay responsive.",
        )

    # The click itself reruns the page, which re-reads the file.
    st.button("↻ Refresh", help="Reload the log file now.")

    selected = labels[selected_label]
    st.caption(
        f"Status: `{selected.get('status', 'N/A')}` — "
        f"PID: `{selected.get('pid', 0)}`"
    )

    refresh_interval = REFRESH_OPTIONS[refresh_label]

    @st.fragment(run_every=refresh_interval)
    def _log_view() -> None:
        _render_log(
            selected.get("id", 0),
            selected.get("name", "N/A"),
            max_lines,
        )

    _log_view()


main()
