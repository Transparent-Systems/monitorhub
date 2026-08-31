# Changelog

## [Unreleased]

- ``profile new`` now selects the profile category interactively (``remote`` or
    ``command``) instead of requiring a hard-coded CLI subcommand.
    The ``profile new remote`` and ``profile new command`` subcommands have been
    removed to make ``profile new`` consistent with ``monitor new``, which
    already selects the monitor type interactively.

- Merged ``main.py`` into the CLI.
    ``main.py`` duplicated the launcher behaviour of ``mhub.py monitor start-all``.
    It has been removed. Use:

    ```bash
    python mhub.py monitor start-all
    ```

    ``monitor start-all`` now also cleans up stale monitors (running monitors whose
    heartbeat is missing or older than 60 seconds) before starting any monitor that
    is not running.

- Database creation is now explicit rather than implicit.  
    Previously ``main.py`` silently created the database schema and support tables on startup when no database was present.  
    This behaviour was removed in favour of an explicit initialisation command, modelled after ``git init``:

    ```bash
    python mhub.py database init        # create schema and load support tables
    python mhub.py database init --recreate   # drop and rebuild from scratch
    python mhub.py database info        # show database information
    python mhub.py database sample-data # load one example monitor, fake profile and mapping
    ```

    A monitor that is started before the database is initialised now reports a clear error instead of silently creating the database.

- Added opt-in sample data command.  
    ``python mhub.py database sample-data`` seeds the database with one example
    monitor, one fake S3 profile, and their mapping. This lets end users see how
    profiles, monitors, and mappings look without reading the manual. The
    credentials and paths are clearly fake, and the command is idempotent.

## [2.0.0] - 2026-02-10

- Added Python S3Handler.  
    The S3Handler is a native Python handler that handles requests to S3 storage providers.  
    Having a native S3 handler eliminates the need for Rclone for S3 compatible cloud storage providers, like:
    - Amazon S3
    - Cloudflare R2
    - IDrive E2
    - Backblaze B2
    - Alibaba Cloud OSS

- Added CommandProcessor
    The Command Processor handles commands like verson, test, profile, config and their subcommands and parameters
- Added remote_profiles to YAML configuration
    This allows a monitor to be propagates to one or more cloud providers at the same time.  
    This adds fault tolerance to a monitor in case a connection to one of the cloud providers is lost.  
- Removed remote_profile from YAML configuration
- Removed testing configuration from YAML example as testing configuration is for development purposes only

## [1.3.0] - 2026-02-01

Removed mode from backup configuration.
Now a backup only runs on copy mode, i.e backup will never delete a file at destination.

## [1.2.0] - 2026-01-26

- Create exe file with PyInstaller
- Moved checks from check-env.py and check_config.py to main.py
- Changed argument --config-path to --config
- Added short arguments for main.py: -c (--config) and -t (--test)

## [1.1.0] - 2026-01-25

- Check monitor path exist.
- Check rclone can copy a temporary file to the destination path

## [1.0.0] - 2026-01-19

- Initial release of MonitorHub.
- This release has been tested on Windows 11 and Linux (Ubuntu 22.04).
- MIT License
