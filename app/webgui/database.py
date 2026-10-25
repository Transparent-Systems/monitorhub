"""Shared database guard for the web GUI pages.

Every page reads its data straight from the SQLite database, so an
uninitialised database - a fresh ``-d/--db-dir`` target, or a first run - would
otherwise surface as a raw ``sqlite3.OperationalError`` traceback. This turns
that case into the same actionable message the CLI prints.
"""

from __future__ import annotations

import streamlit as st

from app.utils.sqlite_handler import SQLiteHandler


def database_ready(sqlite_handler: SQLiteHandler) -> bool:
    """Return True when the application schema exists.

    When it does not, render an error naming the database directory and how to
    create the schema, and return False so the caller stops before touching any
    table.
    """
    if sqlite_handler.is_initialized():
        return True

    st.error(
        f"The database at `{sqlite_handler.db_path.parent}` is not initialised.\n\n"
        "Create it, then reload this page:\n\n"
        "```\nmhub-gui database init\n```\n"
        "To initialise a database in another directory, pass it to both commands:\n"
        "`mhub-gui -d <DIR> database init` and `mhub-gui -d <DIR>`."
    )
    return False
