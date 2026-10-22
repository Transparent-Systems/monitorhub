"""MonitorHub — StreamLit web GUI entry point.

Usage::

    .venv/bin/streamlit run app/webgui/home.py
"""

import sys
from pathlib import Path

# StreamLit adds this script's own directory to ``sys.path``, which would
# shadow the top-level ``app`` package for the page scripts. Add the project
# root (the folder containing ``app/`` and ``pyproject.toml``) explicitly so
# ``app.*`` imports resolve for this page and every page in ``pages/``.
_root = Path(__file__).resolve().parent
while not (_root / "pyproject.toml").exists() and _root.parent != _root:
    _root = _root.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st

_app_icon_path = _root / "app_icon_512.png"
_has_app_icon = _app_icon_path.is_file()

st.set_page_config(
    page_title="MonitorHub",
    page_icon=str(_app_icon_path) if _has_app_icon else "📡",
    layout="wide",
)

if _has_app_icon:
    icon_col, title_col = st.columns([1, 12], vertical_alignment="center")
    with icon_col:
        st.image(
            str(_app_icon_path),
            width=64,
            alt="MonitorHub application icon",
        )
    with title_col:
        st.title("MonitorHub", anchor=False)
else:
    st.title("📡 MonitorHub", anchor=False)

st.markdown("Welcome to the MonitorHub web interface.")
st.markdown(
    "You can find more information at: "
    "[GitHub repository]"
    "(https://github.com/Transparent-Systems/monitorhub)"
)

# Quick stats — display counts once pages provide data.
col1, col2 = st.columns(2)
with col1:
    st.metric(label="Monitors", value="—")
with col2:
    st.metric(label="Profiles", value="—")

st.divider()
st.markdown("Use the sidebar to navigate between pages.")