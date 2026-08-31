# Changelog

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
