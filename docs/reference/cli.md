# Command-line interface

The `mhub` command manages profiles, monitors and configuration. The GUI binary
`mhub-gui` carries the same command surface, so on Windows you can run
`.\mhub-gui\mhub-gui.exe monitor start` instead of `mhub monitor start`.

Every command documents itself:

```bash
mhub --help
mhub database --help
mhub profile --help
mhub monitor --help
```

## Global options

Global options come before the subcommand, for example
`mhub -d /srv/monitorhub/data monitor start`:

| Option | Description |
| --- | --- |
| `-d`, `--db-dir <PATH>` | Directory of the SQLite database. Defaults to the `default_database` setting in `conf/config.yaml`, or `data`. Relative paths in the config resolve against the application folder. |
| `-l`, `--log <PATH>` | Path to the logging configuration YAML. Defaults to `conf/log.yaml` beside the application. |
| `--log-level <LEVEL>` | Override the configured log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--dependency-log-level <LEVEL>` | Override the log level of third-party libraries (boto3/botocore/s3transfer/urllib3); defaults to `WARNING`. |

## Commands

### General

| Command | Purpose |
| --- | --- |
| `mhub version` | Show the MonitorHub version. |
| `mhub webgui` | Launch the Streamlit web GUI. |

### Configuration

| Command | Purpose |
| --- | --- |
| `mhub config test` | Run environment and configuration checks. |
| `mhub config python` | Show the Python version in use and the version the project is pinned to. |

### Profiles

| Command | Purpose |
| --- | --- |
| `mhub profile show` | Show all profiles. |
| `mhub profile new` | Create a profile (select the profile category interactively). |
| `mhub profile edit` | Edit a profile. |
| `mhub profile delete` | Delete a profile. |
| `mhub profile test [--live]` | Test a profile. Without `--live` the test is a dry run; `--live` executes with sample values. |
| `mhub profile import` | Import profiles from an existing rclone configuration. |

### Database

| Command | Purpose |
| --- | --- |
| `mhub database init [--recreate]` | Initialise the database schema and load support tables. `--recreate` drops the existing schema first. |
| `mhub database info` | Show database information. |
| `mhub database version` | Show the database schema version. |
| `mhub database upgrade` | Apply pending schema migrations. |
| `mhub database sample-data` | Load example profile and monitor sample data. |

See [Database](database.md) for the details and the safety notes.

### Monitors

| Command | Purpose |
| --- | --- |
| `mhub monitor show` | Show all monitors. |
| `mhub monitor new` | Create a monitor. |
| `mhub monitor edit` | Edit a monitor. |
| `mhub monitor delete` | Delete a monitor. |
| `mhub monitor clone` | Clone a monitor. |
| `mhub monitor start` | Start a monitor (omit the selector to start all monitors). |
| `mhub monitor test` | Test a monitor. |
| `mhub monitor stop [--immediate]` | Stop a monitor (omit the selector to stop all monitors). `--immediate` force-kills instead of requesting a graceful shutdown. |

## Selecting a profile or monitor

The commands that act on an existing profile or monitor accept a selector. If you
omit it, the command either prompts you to choose interactively or operates on all
items, as noted in each command's help text.

| Flag | Applies to | Description |
| --- | --- | --- |
| `-i`, `--profile-id <ID>` | `profile edit`, `delete`, `test` | ID of the profile |
| `-n`, `--profile-name <NAME>` | `profile edit`, `delete`, `test` | Name of the profile |
| `-i`, `--monitor-id <ID>` | `monitor edit`, `delete`, `clone`, `show`, `start`, `test`, `stop` | ID of the monitor |
| `-n`, `--monitor-name <NAME>` | `monitor edit`, `delete`, `clone`, `show`, `start`, `test`, `stop` | Name of the monitor |

## Internal command

`mhub run-monitor` is used internally by the monitor process manager to start a
monitor in its own process. It is not part of the public interface and its flags
may change without notice.

Next: [Database](database.md) covers the database commands in detail.
