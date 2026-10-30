# Monitors

A monitor consumes events and triggers one or more handlers.

The properties of a monitor are:

| Property Name | Property Description | Required |
| --- | --- | --- |
| `name` | Unique name identifying the monitor | Yes |
| `monitor_path` | Local folder the monitor watches for file system events, or copies to/from the remote for backup and restore monitors | Yes |
| `remote_path` | Remote path the monitor's profiles upload to or download from | Yes |
| `monitor_type` | The kind of monitor: `instant`, `backup` or `restore` | Yes |
| `config` | Type-specific settings: `interval` (backup and restore only) and `exclude_patterns` | No — defaults to `{}` |
| `profiles` | Profiles attached to the monitor through `monitor_profile_map` | Yes — at least one to run |
| `status` | Lifecycle state: `stopped`, `running` or `stop` | Set by MonitorHub |
| `pid` | Process id of the running monitor process (`0` when stopped) | Set by MonitorHub |
| `last_run` | Timestamp the monitor last started | Set by MonitorHub |
| `last_heartbeat` | Timestamp the monitor process last checked in | Set by MonitorHub |

The `name`, `monitor_path`, `remote_path`, `monitor_type`, `config` and
`profiles` properties are the ones you set when creating a monitor
(`mhub monitor new` or the web GUI). The remaining properties are written by
MonitorHub while the monitor runs and are shown by `mhub monitor show`.

!!! note "A monitor needs at least one profile"
    `profiles` is not a column on the `monitors` table — it is the
    `monitor_profile_map` join table — so the database itself allows a monitor
    with no profiles. MonitorHub does not: a monitor with nothing to dispatch
    events to would start, find no profiles and exit, which is why the CLI and
    the web GUI both require at least one profile when a monitor is created or
    edited, and refuse to start a monitor that has none.

## Monitor Types

A monitor consumes events and triggers one or more handlers.
At present there are several monitor types dependent on what triggers the event.
- instant monitor
    Monitor is triggered by a file or folder event
- scheduled monitor with sub types
    Monitor is triggered by a timer event
    - backup monitor
    - restore monitor


## Instant Monitor




