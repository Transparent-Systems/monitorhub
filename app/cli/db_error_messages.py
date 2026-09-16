"""
Translate database constraint errors into user-facing messages.

``SQLiteHandler`` raises the underlying ``sqlite3.Error`` so that callers can
decide how to report a failure. Constraint violations are the family where the
raw text ("UNIQUE constraint failed: monitors.name") is both unhelpful and easy
to phrase properly, so the CLI translates them here.
"""

import sqlite3

# Constraint fields (or field prefixes) with a message worth spelling out.
# Prefixes are used because a composite primary key reports every column, e.g.
# "UNIQUE constraint failed: monitor_profile_map.monitor_id, ...profile_id".
_FIELD_MESSAGES: tuple[tuple[str, str], ...] = (
    ("monitors.name", "A monitor with that name already exists."),
    ("monitor_profile_map", "That profile is already linked to this monitor."),
)


def integrity_error_message(
    error: sqlite3.IntegrityError,
    *,
    entity: str = "record",
    name: str | None = None,
) -> str:
    """
    Return a user-facing message for a sqlite3.IntegrityError.

    :param entity: Name of the thing being written (e.g. "Monitor"), used to
        build a specific message when ``name`` is given.
    :param name: The value the user supplied, when the caller knows it. This
        yields "Monitor name: X already exists" instead of a generic message.
    """
    message = str(error)

    if "UNIQUE constraint failed" in message:
        if name is not None:
            return f"{entity} name: {name} already exists"
        field = _constraint_field(message)
        for prefix, specific_message in _FIELD_MESSAGES:
            if field.startswith(prefix):
                return specific_message
        return f"A record with that {field or 'value'} already exists."

    if "FOREIGN KEY constraint failed" in message:
        return "The referenced record does not exist (it may have been deleted)."

    if "NOT NULL constraint failed" in message:
        field = _constraint_field(message)
        if field:
            return f"A required value is missing ({field})."
        return "A required value is missing."

    return f"Database constraint error: {message}"


def _constraint_field(message: str) -> str:
    """Extract the 'table.column' part of a SQLite constraint message."""
    return message.partition("failed:")[2].strip()