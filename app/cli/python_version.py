"""Report the Python interpreter in use and the project's declared version pin.

MonitorHub is developed against a specific Python version recorded in the
``.python-version`` file (the ``uv``/``pyenv`` convention). That file is a
tooling hint, not something CPython reads: at runtime the interpreter reports
itself through ``sys.version_info`` regardless of any marker file.

The two values answer different questions and are therefore reported
separately:

* the **runtime** version is authoritative and always available -- including
  inside the PyInstaller executable, which bundles its own interpreter;
* the **declared pin** is only meaningful in a source checkout, because
  ``mhub.spec`` does not bundle data files and the frozen binary has no project
  tree to search.

The helpers here are pure (filesystem + ``sys`` only) so they can be unit
tested without a database or the CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

PIN_FILENAME = ".python-version"
_FROZEN_LABEL = "(bundled executable)"


def runtime_python_version() -> str:
    """Return the running interpreter's ``major.minor.patch`` version."""
    return ".".join(str(part) for part in sys.version_info[:3])


def is_frozen() -> bool:
    """Return True when running from a PyInstaller-style bundled executable."""
    return bool(getattr(sys, "frozen", False))


def runtime_executable() -> str:
    """Return the running executable path, or a label for a frozen binary."""
    if is_frozen():
        return _FROZEN_LABEL
    return sys.executable


def find_pin_file(start: Path | str | None = None) -> Path | None:
    """Locate the nearest ``.python-version`` by walking up from *start*.

    Defaults to the current working directory so the command works from any
    subdirectory of the project. Returns ``None`` when no pin file exists --
    notably inside a frozen binary, where the project tree is absent.
    """
    origin = Path(start).resolve() if start is not None else Path.cwd().resolve()
    for directory in (origin, *origin.parents):
        candidate = directory / PIN_FILENAME
        if candidate.is_file():
            return candidate
    return None


def read_pinned_version(pin_file: Path) -> str | None:
    """Return the version request from *pin_file*, or ``None`` if unavailable.

    Only the first non-empty, non-comment line is used. A missing, unreadable,
    empty or comment-only file yields ``None`` rather than raising, because this
    feeds a diagnostic report.
    """
    try:
        content = pin_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return None


def pin_matches(pin: str, runtime: str) -> bool:
    """Return True when *runtime* (``3.12.14``) satisfies the *pin* request.

    Mirrors how ``uv`` treats a version request: ``3.12`` matches ``3.12.14``
    (dotted component-prefix match), while a fully specified ``3.12.14`` must
    match exactly.
    """
    pin_parts = pin.split(".")
    runtime_parts = runtime.split(".")
    if not pin or len(pin_parts) > len(runtime_parts):
        return False
    return pin_parts == runtime_parts[: len(pin_parts)]
