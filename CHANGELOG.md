# Changelog

## [Unreleased]

- ``mhub profile new`` and ``mhub profile edit`` now prompt for
  ``command_max_workers`` (the maximum number of concurrent command processes,
  default ``100``, min ``1``, max ``1000``). ``mhub profile test`` also displays
  and validates the value.

- ``mhub monitor start`` and ``mhub monitor stop`` now operate on all monitors
  when neither ``--monitor-id`` nor ``--monitor-name`` is given, matching
  ``mhub monitor show``. The separate ``monitor start-all`` and
  ``monitor stop-all`` subcommands have been removed.

- Added a schema migration/upgrade path for the SQLite database.
    - ``mhub database upgrade`` applies any pending schema migrations in place
      (non-destructive) and refuses to downgrade a database created by a newer
      application.
    - ``mhub database version`` now reports the application version, the
      supported schema version, and whether the database is up to date, older,
      or newer than the schema this application supports.
    - ``mhub database init`` is now non-destructive on existing databases: it
      warns and suggests ``database upgrade`` instead of silently recreating.
- The ``schema_version`` table is now an append-only history with a descriptive
  ``description`` column. The schema version is compared numerically, fixing a
  bug where ``9.0.0`` was treated as newer than ``10.0.0``.
- New ``app/cli/schema_versioning.py`` module centralises version comparison,
  compatibility classification, and the ordered migration registry.

## [1.0.0] - 2026-09-01

Initial release of MonitorHub (formerly "FolderMonitor").

This release has been tested on Windows 11 and Linux (Ubuntu 22.04).

- ``profile new`` now selects the profile category interactively (``remote`` or
    ``command``) instead of requiring a hard-coded CLI subcommand.
    The ``profile new remote`` and ``profile new command`` subcommands have been
    removed to make ``profile new`` consistent with ``monitor new``, which
    already selects the monitor type interactively.

- Database creation is now explicit rather than implicit.
    ```bash
    python mhub.py database init        # create schema and load support tables
    python mhub.py database init --recreate   # drop and rebuild from scratch
    python mhub.py database info        # show database information
    python mhub.py database sample-data # load one example monitor, fake profile and mapping
    ```

    A monitor that is started before the database is initialised now reports a clear
    error instead of silently creating the database.

- Added opt-in sample data command.

    ``python mhub.py database sample-data`` seeds the database with one example
    monitor, one fake S3 profile, and their mapping. This lets end users see how
    profiles, monitors, and mappings look without reading the manual. The
    credentials and paths are clearly fake, and the command is idempotent.

- MIT License.
