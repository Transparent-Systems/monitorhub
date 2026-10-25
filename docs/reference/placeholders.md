# Placeholders

A command template in a [command profile](../guides/command-profiles.md) may
contain placeholders that are replaced with event details before the command is
executed.

| Placeholder | Description |
| --- | --- |
| `{monitor_name}` | Name of the monitor |
| `{profile_name}` | Name of the attached profile |
| `{event_name}` | Event type: `created`, `deleted`, `modified`, `moved`, `closed` or `timer` |
| `{src_path}` | Absolute source path |

## Example

```bash
notify-send "Testing command of monitor = {monitor_name}, profile = {profile_name}, event = {event_name}, source path = {src_path}"
```

The placeholders are replaced before execution, so the command above receives the
concrete monitor name, profile name, event type and source path when it fires.

## Event types

| Event | Fires when |
| --- | --- |
| `created` | A file or folder was created |
| `modified` | A file was modified |
| `deleted` | A file or folder was deleted |
| `moved` | A file or folder was moved or renamed |
| `closed` | A file that was being written was closed |
| `timer` | A scheduled monitor reached its interval (backup and restore monitors) |

`timer` is available to command profiles in addition to the file system events.
For a timer event the command fires once per monitor `interval`, with no cooldown
by default.

## Where placeholders are configured

The template and its event filter live in the command profile's `config`, under
the keys `command` and `command_events`. The remaining command settings are
documented in [Command profiles](../guides/command-profiles.md).
