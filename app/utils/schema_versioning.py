"""Schema versioning: comparison, compatibility classification, and migrations.

This module is the single place where the database schema's version history is
described. It deliberately keeps the schema version independent of the
application version: the application version changes on every release, but the
database schema version only changes when the schema itself changes.

Everything here is edited *only* when the database schema actually changes, so
there is nothing to maintain on a per-release basis.
"""

from __future__ import annotations

from collections.abc import Callable

# Ordered migration registry. Each entry is ``(db_schema_version, description,
# apply_fn)`` where ``apply_fn`` receives the SQLiteHandler and performs the
# schema change. ``apply_fn`` may be ``None`` when the schema for that version
# is created directly by ``SQLiteHandler.create_schema`` (i.e. the baseline).
# Migrations are applied in ascending version order.
Migration = tuple[str, str, Callable | None]

SCHEMA_MIGRATIONS: list[Migration] = [
    ("1.0.0", "Initial schema", None),
]

# The schema version this application creates and supports. Always the most
# recent entry in ``SCHEMA_MIGRATIONS``, which is the single source of truth
# for the database schema version.
DATABASE_SCHEMA_VERSION: str = SCHEMA_MIGRATIONS[-1][0]


def parse_version(version: str) -> tuple[int, ...]:
    """Parse a dotted version string into a tuple of integers.

    Only the leading numeric run of each segment is used, so values such as
    ``"1.0.0"``, ``"10.2"`` or ``"1"`` parse cleanly. Trailing non-numeric text
    (e.g. ``"rc1"``) ends the version.
    """
    parts: list[int] = []
    for segment in version.strip().split("."):
        digits = ""
        for char in segment:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def compare_versions(a: str, b: str) -> int:
    """Compare two dotted version strings numerically.

    Returns a negative value if ``a`` is older than ``b``, zero if equal, and a
    positive value if ``a`` is newer than ``b``. Shorter versions are padded
    with zeros, so ``"1.0"`` equals ``"1.0.0"``.
    """
    parsed_a = parse_version(a)
    parsed_b = parse_version(b)

    length = max(len(parsed_a), len(parsed_b))
    parsed_a = parsed_a + (0,) * (length - len(parsed_a))
    parsed_b = parsed_b + (0,) * (length - len(parsed_b))

    return (parsed_a > parsed_b) - (parsed_a < parsed_b)


def classify(db_version: str, supported_version: str) -> str:
    """Classify a database schema version against the supported version.

    Returns one of ``"ok"`` (equal), ``"older"`` (can be upgraded in place) or
    ``"newer"`` (created by a newer application and not supported by this one).
    """
    comparison = compare_versions(db_version, supported_version)
    if comparison > 0:
        return "newer"
    if comparison < 0:
        return "older"
    return "ok"