"""Monitor clone-naming helpers.

Pure functions for deriving a unique clone name from a monitor name, shared
between presentation layers so clone naming stays consistent.  Cloning a clone
increments the copy counter instead of stacking ``(copy)`` suffixes.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# Matches a trailing " (copy)" or " (copy 7)" suffix.
_COPY_SUFFIX_RE = re.compile(r"\s+\(copy(?: \d+)?\)$")


def clone_base_name(name: str) -> str:
    """Return ``name`` with a trailing ``(copy)`` / ``(copy N)`` suffix removed.

    ``"photos"`` -> ``"photos"``; ``"photos (copy 2)"`` -> ``"photos"``.
    """
    return _COPY_SUFFIX_RE.sub("", name).strip()


def next_clone_name(name: str, name_exists: Callable[[str], bool]) -> str:
    """Return the first available clone name for ``name``.

    Produces ``<base> (copy)``, then ``<base> (copy 2)``, ``<base> (copy 3)``,
    ... skipping any name for which ``name_exists`` returns True.  ``base`` is
    ``name`` with an existing copy suffix stripped, so cloning a clone
    increments the counter rather than stacking suffixes.
    """
    base = clone_base_name(name)
    candidate = f"{base} (copy)"
    counter = 2
    while name_exists(candidate):
        candidate = f"{base} (copy {counter})"
        counter += 1
    return candidate
