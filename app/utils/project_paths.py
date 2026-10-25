"""Project-root resolution shared by the CLI and the monitor backend.

Relative paths (database directories, the default log configuration file) are
anchored at the folder that owns the application instead of the process's
current working directory, so the binary and scripts behave the same from any
working directory.

Two roots are distinguished:

- :func:`project_root` -- the *writable* folder that owns ``conf/``, ``data/``
  and ``logs/`` (beside the executable when frozen).
- :func:`resource_root` -- the *read-only* folder holding files bundled into
  the executable (``README.md``, the application icon, the web GUI pages).
"""

import sys
from pathlib import Path


def project_root() -> Path:
    """The folder that contains the application's ``conf/`` directory.

    - PyInstaller one-file binary (``sys.frozen``): the executable's directory.
    - Source runs: the repository root (three levels above this module).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    """The folder holding the application's bundled read-only resources.

    - PyInstaller one-file/one-dir (``sys.frozen``): the extraction root
      (``sys._MEIPASS``), where ``--add-data`` payloads are placed.
    - Source runs: the repository root (same as :func:`project_root`).

    Falls back to the executable's directory for a frozen build that exposes no
    ``_MEIPASS`` (e.g. a custom bootloader).
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def project_conf(name: str) -> Path:
    """Path of a file inside the project ``conf/`` folder."""
    return project_root() / "conf" / name