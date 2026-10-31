# Command profiles

A command profile runs a shell command or script in response to events on any
monitor — file system events on instant monitors, or timer events on scheduled
monitors. It is a building block for automation, useful for:

- Triggering an alert (email, SMS, webhook, chat notification)
- Locking down a firewall port or revoking access
- Starting an external program or pipeline
- Intrusion detection and ransomware protection responses

Create a **command profile** (profile category `command`, type `event_command`)
and attach it to a monitor. The profile's command runs when the monitor fires a
matching event:

```bash
mhub profile new
```

A monitor that uses command profiles only needs no remote path: a command
profile runs a command and never copies files to a remote destination, so
MonitorHub does not ask for one. See [Monitors](monitors.md).

## Configuration keys

The command settings are stored in the profile's `config`:

| Key | Purpose |
| --- | --- |
| `command` | The command template to execute |
| `command_events` | Events that trigger the command (for example `created` and `closed`) |
| `command_cooldown` | Interval that suppresses repeat firings (`0s` disables throttling) |
| `command_timeout` | Upper bound on a single run |
| `command_shell` | Run through a shell (opt-in) instead of without one |
| `command_max_workers` | Maximum concurrent command processes |

`command_max_workers` defaults to `100` (minimum `1`, maximum `1000`). When the
limit is reached, further commands are queued FIFO and are never dropped.

`command_events` may include `timer` to fire on scheduled (backup/restore) timer
ticks in addition to file system events. For a timer event the command fires once
per monitor `interval`, with no cooldown by default.

## Placeholders

The command template may contain placeholders that are replaced with event
details before execution. See [Placeholders](../reference/placeholders.md) for the
full list and an example.

## Safety

- By default a command is executed **without a shell** (`shell=False`) to avoid
  shell injection. Enable shell execution (opt-in) to use pipes, redirects or
  environment variable expansion.
- Event filtering restricts the handler to specific events, for example only
  `created` and `closed`.
- Cooldown suppresses repeat firings within a window; the default `0s` disables
  throttling.

## Testing a command profile

```bash
mhub profile test          # dry run: shows the resolved command
mhub profile test --live   # executes the command with sample values
```

Use `--live` deliberately: the command really runs.

Next: [Placeholders](../reference/placeholders.md) lists the available template
variables.
