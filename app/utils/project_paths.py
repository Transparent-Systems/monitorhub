"""Project-root resolution shared by the CLI and the monitor backend.

Relative paths (database directories, the default log configuration file) are
anchored at the folder that owns the application instead of the process's
current working directory, so the binary and scripts behave the same from any
working directory.
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


def project_conf(name: str) -> Path:
    """Path of a file inside the project ``conf/`` folder."""
    return project_root() / "conf" / name