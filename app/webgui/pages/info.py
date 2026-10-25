"""Info page for the MonitorHub web GUI.

Renders the project README.md as the application's About/Info page.
"""

from __future__ import annotations

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

from app.utils.project_paths import resource_root


def main() -> None:
    st.set_page_config(page_title="Info", page_icon="ℹ️", layout="centered")

    readme_path = resource_root() / "README.md"
    try:
        readme = readme_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        st.error(f"Could not read README.md at '{readme_path}': {error}")
        return

    st.markdown(readme)


main()
