## Monitor gets status "stopped" when debug session ends
When you run a debug session on mhub.py with "-d testdb/dev monitor start -m 1"
then, as soon as the debug session ends the detached monitor get status "stopped".
Log file monitorhub.log shows:

```
2026-09-01 18:25:45,952 - DEBUG - InstantMonitorHandler - MonitorEventHandler initialized
2026-09-01 18:25:45,954 - INFO - InstantMonitorHandler - Observer 'Thread-10' is now listening on 'testdata/source/instant-monitor'
2026-09-01 18:26:00,826 - INFO - MonitorHub - Shutting down monitor 'Instant Monitor 1' (id=1) — reason: received signal SIGTERM
2026-09-01 18:26:00,827 - INFO - InstantMonitorHandler - Monitor stopped.
```

The reason is that the VS Code debuggers stops all processes started during the debug session.
This can be confusing initially, but this is hwo the debugger works.

## Run all non-interactive tests

```bash
pytest -k "not interactive"
```

## Monitor Process Lifecycle and Child Reaping

A monitor runs as a detached child process launched by `MonitorProcessManager.launch()`
(owned by `MonitorCommands` as its `processes` collaborator) via
`subprocess.Popen(..., start_new_session=True)`. `start_new_session` only calls `setsid()`
(new session / controlling terminal); it does **not** change the parent-child relationship, so
the launching process remains responsible for reaping the child.

### Graceful stop, then escalate

`monitor stop` is graceful first and forceful only as a fallback:

1. `_stop_monitor()` writes `status='stop'` to the database (the graceful request). The monitor's
   own status poller (`run_monitor.py`, ~10s interval) observes this and shuts itself down. Each
   poll tick writes a heartbeat first; if that write hits a transient SQLite lock it is retried
   once after a short pause (interruptible, so a pending shutdown is never delayed by it) before
   the poller logs a warning and moves on to the next tick.
2. `stop()` waits up to `STOP_GRACE_SECONDS` (15s) for the process to exit.
3. Only if it has not exited does `MonitorProcessManager.escalate_stop()` send `SIGTERM`, wait
   briefly, then fall back to `SIGKILL` via `MonitorProcessManager.force_kill()`.

`--immediate` (`immediate=True`) is a separate, explicit opt-in that skips the graceful request.

### Why we track and reap the Popen handle

`MonitorProcessManager` keeps every child it spawns in `self.tracked_processes` (keyed by monitor
id) and uses `poll()` / `wait()` to detect the exit and release the PID. This matters because a
terminated child that the parent has not yet reaped stays a **zombie**: it still occupies its PID,
so `os.kill(pid, 0)` succeeds and a naive liveness check reports it as still running. Without
reaping, a monitor that shut down gracefully within the grace window could be misdetected and
force-killed unnecessarily.

Two complementary safeguards are in place:

- **Tracked handle (preferred):** `MonitorProcessManager.is_alive()` uses the tracked `Popen.poll()`
  when this instance launched the monitor, which reaps the child and reports its true state.
  `MonitorProcessManager.reap()` collects exit status after a stop, immediate kill, or stale cleanup.
- **Zombie-aware generic check (fallback):** `is_process_alive()` (in `app/utils/generic_util.py`)
  treats a process in state `Z` as not alive (Linux `/proc/<pid>/stat`; best-effort `ps` on other
  POSIX systems). This covers monitors started by another process that this instance does not own.

### Why not a SIGCHLD handler

A global `SIGCHLD` handler is intentionally avoided. The CLI/test process routinely runs *other*
children concurrently (e.g. `rclone` via `RcloneHandler`, `subprocess.run` in command/diagnostic
helpers). A handler that reaps with `waitpid(-1, ...)` would race with `subprocess`'s own
`waitpid` bookkeeping and can break `Popen.poll()`/`wait()`/`communicate()` and `subprocess.run`.
Setting `SIGCHLD` to `SIG_IGN` to auto-reap is also unsuitable because it prevents `Popen` from
collecting return codes. Because the code that spawns a monitor always owns its `Popen` handle,
handle-based reaping is simpler, scoped, and safer than signal-based supervision.

Note on reparenting: when the launching process exits (e.g. `mhub.py monitor start` returns), the
monitor is reparented to a subreaper (`systemd --user` or init/PID 1), which reaps it promptly on
exit — so no zombie is observed in that case.

