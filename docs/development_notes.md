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

