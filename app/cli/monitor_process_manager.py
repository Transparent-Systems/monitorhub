"""OS process lifecycle management for monitor child processes.

Extracted from :class:`~app.cli.monitor_commands.MonitorCommands` so the
command handler can focus on database state and user interaction while this
collaborator owns the low-level process mechanics: launching detached
children, tracking their ``Popen`` handles, checking liveness, waiting for
exit, and escalating a stop from SIGTERM to SIGKILL.

The process-lifecycle invariants described in ``docs/development_notes.md``
are preserved here: finished children are reaped through their tracked
``Popen`` handle (avoiding zombies that ``os.kill(pid, 0)`` would report as
alive), and a global ``SIGCHLD`` handler is deliberately not used.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.cli.prompt_service import PromptService
from app.utils.generic_util import is_process_alive


class MonitorProcessManager:
    """Launch, track, and stop detached monitor child processes."""

    def __init__(
        self,
        logger: logging.Logger,
        db_dir: str,
        log_config: str,
        log_level: str | None,
        prompt: PromptService,
    ) -> None:
        self.logger = logger
        self.db_dir = db_dir
        self.log_config = log_config
        self.log_level = log_level
        self.prompt = prompt
        # Child monitor processes launched by this instance, keyed by monitor id.
        # Holding the Popen handles lets us reap finished children with ``poll``
        # (avoiding zombies) and detect their exit reliably, since os.kill(pid, 0)
        # reports a terminated-but-unreaped child as alive.
        self.tracked_processes: dict[int, subprocess.Popen] = {}

    @staticmethod
    def resolve_python_interpreter(script_dir: Path) -> str:
        """Return the Python interpreter used to launch monitor child processes.

        Prefer the project's virtual environment (.venv) so child processes run
        with the same interpreter and installed dependencies. Falls back to the
        currently running interpreter when the venv is not found.
        """
        if sys.platform == "win32":
            venv_python = script_dir / ".venv" / "Scripts" / "python.exe"
        else:
            venv_python = script_dir / ".venv" / "bin" / "python3"

        return str(venv_python) if venv_python.exists() else sys.executable

    def force_kill(self, pid: int, name: str) -> bool:
        """Send SIGKILL to a process and return whether it is now dead.

        Returns True if the process was killed or was already gone.
        Returns False on PermissionError (process still alive).
        """
        try:
            os.kill(pid, signal.SIGKILL)
            self.prompt.print(f"Sent SIGKILL to monitor '{name}' (pid={pid}).")
            return True
        except ProcessLookupError:
            self.prompt.print(f"Monitor '{name}' process (pid={pid}) not found — may have already exited.")
            return True
        except PermissionError:
            self.prompt.print(f"Permission denied when sending SIGKILL to monitor '{name}' (pid={pid}).")
            return False

    def reap(self, monitor_id: int | None) -> None:
        """Reap a monitor child launched by this instance, if one is tracked.

        A finished child stays a zombie until its parent collects its exit
        status, so ``wait`` is called here to release the PID. Monitors started
        by a different process are not tracked and are left to their owner.
        """
        if monitor_id is None:
            return
        process = self.tracked_processes.get(monitor_id)
        if process is None:
            return
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            # Still running after the short wait; it will be reaped on exit.
            self.logger.debug(f"Monitor process (id={monitor_id}) not reaped within 1s.")
        except Exception as e:  # noqa: BLE001 - never fail a stop on bookkeeping.
            self.logger.debug(f"Could not reap monitor process (id={monitor_id}): {e}")

    def is_alive(self, monitor_id: int | None, pid: int) -> bool:
        """Return whether a monitor process is still running.

        Prefers the ``Popen`` handle for a monitor launched by this instance so
        that ``poll`` reaps a finished child and an unreaped zombie is not
        mistaken for a live process. Falls back to the generic PID check for
        monitors started by another process (e.g. a previous CLI invocation),
        because that process is responsible for reaping its own child.
        """
        if monitor_id is not None and pid and pid > 0:
            process = self.tracked_processes.get(monitor_id)
            if process is not None and process.pid == pid:
                return process.poll() is None
        return is_process_alive(pid)

    def wait_for_exit(
        self, pid: int, timeout: float, interval: float = 0.5, monitor_id: int | None = None
    ) -> bool:
        """Wait up to ``timeout`` seconds for ``pid`` to exit.

        Returns True if the process is no longer alive (or there is no pid).
        ``monitor_id`` lets the check reap and recognise a child launched by
        this instance instead of relying solely on the plain PID check.
        """
        if not pid:
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_alive(monitor_id, pid):
                return True
            time.sleep(interval)
        return not self.is_alive(monitor_id, pid)

    def escalate_stop(self, pid: int, name: str, monitor_id: int | None = None) -> None:
        """Escalate a graceful stop that has not taken effect.

        Sends SIGTERM (which triggers the monitor's own graceful shutdown
        handler on POSIX), waits briefly, then falls back to SIGKILL.
        """
        if not pid:
            return
        try:
            os.kill(pid, signal.SIGTERM)
            self.prompt.print(f"Escalating: sent SIGTERM to monitor '{name}' (pid={pid}).")
        except ProcessLookupError:
            return
        except PermissionError:
            self.prompt.print(
                f"Permission denied sending SIGTERM to monitor '{name}' (pid={pid})."
            )
            return

        if self.wait_for_exit(pid, timeout=5.0, monitor_id=monitor_id):
            return
        self.force_kill(pid, name)

    def launch(self, monitor: dict) -> bool:
        """Launch run_monitor.py for a single monitor as a detached child process.

        Returns True on success, False on failure.
        """
        monitor_id_val: int = monitor.get("id", 0)
        monitor_name = monitor.get("name", "N/A")

        project_root = Path(os.path.join(os.path.dirname(__file__), "../")).resolve()
        run_monitor_script = project_root / "monitor" / "run_monitor.py"
        python = self.resolve_python_interpreter(project_root)

        child_env = None
        if getattr(sys, "frozen", False):
            cmd = [
                sys.executable,
                "run-monitor",
                "--monitor-id", str(monitor_id_val),
                "--db-dir", str(self.db_dir),
                "--log", self.log_config,
            ]
            if self.log_level:
                cmd += ["--log-level", self.log_level]
            child_env = os.environ.copy()
            for key in list(child_env.keys()):
                if key.startswith("_PYI_") or key in (
                    "LD_LIBRARY_PATH",
                    "DYLD_LIBRARY_PATH",
                ):
                    child_env.pop(key, None)
        else:
            cmd = [
                python,
                str(run_monitor_script),
                "--monitor-id", str(monitor_id_val),
                "--db-dir", str(self.db_dir),
                "--log", self.log_config,
            ]
            if self.log_level:
                cmd += ["--log-level", self.log_level]

        try:
            logs_dir = Path.cwd() / "logs"
            logs_dir.mkdir(exist_ok=True)
            error_log = logs_dir / f"monitor_{monitor_id_val}.log"
            with open(error_log, "a") as error_log_fh:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=error_log_fh,
                    start_new_session=True,
                    env=child_env,
                )
            # Track the child so we can reap it and detect its exit reliably.
            self.tracked_processes[monitor_id_val] = process
        except Exception as e:  # noqa: BLE001
            self.prompt.print(f"Failed to start monitor '{monitor_name}' (id={monitor_id_val}): {e}")
            return False

        return True
