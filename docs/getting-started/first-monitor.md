# Your first monitor

This walkthrough takes you from an empty installation to a running monitor. The
commands are the same in the CLI and in the GUI binary: on Windows, replace
`mhub` with `.\mhub-gui\mhub-gui.exe` if you downloaded the GUI.

## 1. Initialise the database

MonitorHub stores profiles, monitors and support tables in a SQLite database.
The database is created explicitly, in the same spirit as `git init`:

```bash
mhub database init
```

Check what was created:

```bash
mhub database info
```

## 2. Create a profile

A profile holds the configuration of a handler. Create one interactively:

```bash
mhub profile new
```

The command asks for the profile category first — a remote profile for a storage
destination, or a command profile for a script. See
[Remote profiles](../guides/remote-profiles.md) and
[Command profiles](../guides/command-profiles.md) for what each needs.

## 3. Create a monitor

```bash
mhub monitor new
```

Attach one or more profiles while the command walks you through the settings.

## 4. Start and stop the monitor

```bash
mhub monitor start
```

The monitor runs as its own process. Stop it with:

```bash
mhub monitor stop
```

`mhub monitor stop --immediate` skips the graceful shutdown request and kills the
process instead. Use it only when a monitor does not stop on its own.

## 5. Look around

```bash
mhub profile show
mhub monitor show
```

## Optional: load example data

To see how profiles, monitors and their mapping fit together, load the sample
data. It creates one example monitor, one fake S3 profile and the mapping
between them, using clearly fake credentials and paths:

```bash
mhub database sample-data
```

The command only adds the examples once and is safe to run again. Delete them
with `mhub profile delete` and `mhub monitor delete`.

## Or use the web GUI

Start the GUI and configure the same profiles and monitors in your browser:

```bash
mhub webgui
```

## Where to go next

- Configure a storage destination: [Remote profiles](../guides/remote-profiles.md)
- Run a script on an event: [Command profiles](../guides/command-profiles.md)
- Full command list: [Command-line interface](../reference/cli.md)
