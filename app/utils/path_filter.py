"""
Shared path-filtering utilities for exclude patterns.

Provides a single, transport-agnostic matcher used to decide whether a path
(local filesystem path or remote storage key/object) matches any of a set of
exclude patterns. Used by the instant monitor (event-level filtering) and the
scheduled backup/restore handlers (file/object filtering), as well as any
future native Python storage backends.
"""

import fnmatch


def _match_segments(path_parts: list[str], pattern_parts: list[str]) -> bool:
    """
    Recursively matches path segments against pattern segments.

    Supports the `**` wildcard, which matches zero or more consecutive
    path segments. All other segments are matched with fnmatch, so the
    usual `*`, `?` and `[seq]` wildcards work within a segment.
    """
    if not pattern_parts:
        return not path_parts

    head, tail = pattern_parts[0], pattern_parts[1:]

    if head == "**":
        # `**` matches zero or more consecutive segments
        return any(_match_segments(path_parts[i:], tail) for i in range(len(path_parts) + 1))

    if not path_parts:
        return False

    return fnmatch.fnmatch(path_parts[0], head) and _match_segments(path_parts[1:], tail)


def is_excluded(path_str: str, exclude_patterns: list[str]) -> bool:
    """
    Checks if a path matches any of the exclude patterns.

    Both Windows-style (`C:\\folder\\file.txt`) and Unix-style
    (`/folder/file.txt`) paths are handled regardless of the platform the
    code runs on. A pattern either matches a single path segment
    (e.g. `*.tmp`, `Thumbs.db`, `.git`) or, when it contains path
    separators, multiple segments (e.g. `**/build/app1/*`).
    """
    # Normalize backslashes so Windows paths split correctly on any platform
    normalized_path = path_str.replace("\\", "/")
    path_parts = [part for part in normalized_path.split("/") if part]

    for pattern in exclude_patterns:
        pattern_parts = [part for part in pattern.replace("\\", "/").split("/") if part]

        if not pattern_parts:
            continue

        if len(pattern_parts) > 1:
            # Multi-segment pattern (e.g. "**/build/app1/*"): match the sequence
            if _match_segments(path_parts, pattern_parts):
                return True
        else:
            # Single-segment pattern (e.g. "Thumbs.db", "*.tmp"): match any segment
            if any(fnmatch.fnmatch(part, pattern_parts[0]) for part in path_parts):
                return True

    return False
