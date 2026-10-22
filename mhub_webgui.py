"""
Script: mhub_webgui.py
Version: v1.1.0
Author: John Zoetebier
Description:
    PyInstaller entry point for the MonitorHub web GUI binary (``mhub-webgui``).

    The binary serves two roles:

    1. Started with no arguments it launches the Streamlit web GUI.
    2. Started with ``run-monitor`` as its first argument it behaves as a
       monitor child process. ``MonitorProcessManager`` re-executes
       ``sys.executable`` this way when it is frozen, so the GUI can start and
       stop real monitors without a separate Python installation.

    The ``run-monitor`` dispatch happens before Streamlit is imported so a
    monitor child does not pay the (multi-second) GUI import cost.
Requirements:
    1) Python (version pinned in .python-version; run 'mhub config python')
    2) Python modules in requirements.txt
Usage:
    mhub-webgui                 # start the web GUI (http://127.0.0.1:8501)
    mhub-webgui --server.port=8600
Notes:
    See: README.md for more details.
"""

import sys


def main(argv: list[str] | None = None) -> int:
    """Run the web GUI, or a monitor child when invoked with ``run-monitor``."""
    argv = sys.argv[1:] if argv is None else list(argv)

    # Hidden in-process dispatch used by the frozen PyInstaller binary.
    # When the binary re-invokes itself to start a monitor child process it
    # passes `run-monitor` as the first argument (see
    # MonitorProcessManager.launch). Run the monitor logic directly so it works
    # inside the bundled executable, without importing Streamlit first.
    if argv and argv[0] == "run-monitor":
        from app.monitor.run_monitor import run_monitor_main
        return run_monitor_main(argv[1:])

    from app.webgui.launcher import main as launcher_main
    return launcher_main(argv)


if __name__ == "__main__":
    sys.exit(main())
