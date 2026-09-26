# Changelog

## [Unreleased]

- The S3 access key secret is now stored under rclone's own option name,
  ``secret_access_key``, instead of MonitorHub's ``access_key_secret``.  An
  rclone-imported profile keeps rclone's keys verbatim, so switching such a
  profile from ``remote_handler=rclone`` to the built-in ``s3`` handler left the
  secret under a name ``S3Factory`` did not read: boto3 received an access key
  id without a secret and failed with ``PartialCredentialsError``.  ``profile
  new`` now writes the rclone-compatible key and ``S3Factory`` reads it, so a
  profile can be switched between the built-in handler and rclone without
  renaming its credentials; the ``access_key_secret`` -> ``SECRET_ACCESS_KEY``
  entry in ``app.monitor.rclone_env`` is gone because the key now uppercases to
  the rclone option by identity.  Profiles created before this change still
  carry ``access_key_secret`` and must be re-created or re-imported.

- ``profile import`` now detects a corrupt ``rclone.conf`` instead of trying to
  work around it.  rclone writes one ``key = value`` per line, so a line that is
  not a section header, a comment, a blank line or a ``key = value`` line is
  corruption (for example a value wrapped across lines).  ``ProfileImporter``
  reports every offending line with its section and one-based line number and
  refuses the import as a whole -- nothing is written to the profiles table until
  the user fixes the file.  The prior behaviour folded such a wrapped line back
  into the previous value, which silently imported a mangled profile (a doubled
  ``google-drive`` token).  Clean configs are still parsed with
  ``interpolation=None`` and ``=``-only delimiters so a ``%`` or ``:`` in a
  value is left untouched, and a key that is not an rclone option name is
  skipped with a warning instead of being imported as a bogus property.

- Importing rclone profiles moved out of ``DiagnosticUtil`` into the new
  ``app.cli.profile_importer.ProfileImporter``; ``mhub profile import`` now
  delegates to it.  ``config test`` no longer offers an import: its
  ``check_profile_import`` only reports, logging an ``INFO`` line naming the
  rclone profiles that are not imported yet and telling the user to run
  ``mhub profile import``.  The importer instance is shared, so the check and
  the import cannot disagree on the rclone.conf reading rules.

- Secret profile values are now masked (``********``) in every profile display:
  ``profile show``, the ``s3`` edit wizard (the current access key secret) and
  the rclone property/``rclone_options`` listing of ``profile edit``.  The new
  ``app.cli.profile_display`` owns the rule (``pass``/``password``, anything
  containing ``secret``/``token``/``passw``/``credential``, and keys ending in
  ``_key``/``_pem``), so ``access_key_id`` and ``client_id`` stay visible while
  secrets no longer reach the terminal scrollback.  Masking is display-only:
  pressing Enter keeps the stored value and typed secrets are never echoed.

- ``profile edit`` now edits every remote profile, not only ``s3`` and
  ``event_command``.  An ``s3`` profile using the built-in S3Handler keeps its
  provider/credentials/region wizard, while every rclone-routed profile -- an
  imported ``ftp``/``sftp``/``drive``/... remote, or an ``s3`` profile switched
  to rclone -- is edited property by property: each backend option is listed
  with its current value and pressing Enter keeps it.  ``rclone_options`` has
  its own ``key=value`` prompt (``none`` removes them; option names are
  validated with the rule shared with ``app.monitor.rclone_env``), the legacy
  ``comment``/``important`` hints are not offered, and ``remote_handler`` stays
  a yes/no question so an ``s3`` profile can still switch between the built-in
  S3Handler and rclone.

- A profile's ``rclone_options`` are now checked against the installed rclone:
  rclone silently ignores ``RCLONE_*`` variables for flags it does not have, so
  MonitorHub logs a warning naming the unsupported options (a typo, or an rclone
  build without object lock).  The ``rclone help flags`` probe is cached per
  rclone binary and never fails a transfer.

- An rclone-routed profile no longer needs a section in ``rclone.conf``:
  MonitorHub passes the profile's settings to the rclone subprocess through
  ``RCLONE_CONFIG_<REMOTE>_<OPTION>`` environment variables (new
  ``app.monitor.rclone_env``), so rclone resolves the profile's remote from
  MonitorHub alone and the variables stay local to that one rclone process
  (secrets never reach the command line).  Verified against the installed
  rclone: the remote resolves with no config file at all, and the MonitorHub
  values win over a same-named ``rclone.conf`` section.  Per-profile rclone
  tuning is stored in the profile config as ``rclone_options`` (``transfers``,
  ``s3_chunk_size``, ``s3_storage_class``, ``s3_object_lock_mode``, ...) and
  becomes ``RCLONE_<OPTION>`` flag variables.  ``RcloneHandler`` accepts the
  full profile (and so does ``test_connection``, via ``profile test``); a
  profile name is normalised for the rclone remote name when it contains
  characters the environment-variable channel cannot express (``s3-test`` ->
  ``s3_test``), reported at DEBUG level -- rclone itself handles such names
  fine.  ``app.monitor.rclone_env.build_environment`` owns that whole mapping and
  returns the remote name plus the variables.  The ``comment``/``important``
  display hints of the
  rclone-import era are no longer written (existing ones are ignored when the
  environment is built), and ``profile edit`` reports that editing non-s3
  remote types is not implemented yet instead of pointing at ``rclone config``.

- Remote profiles now carry an explicit ``remote_handler`` config key (``s3`` or
  ``rclone``) that selects their handler, so an S3 profile can be delegated to
  rclone instead of the builtin S3Handler -- useful for rclone transfer tuning
  (``transfers``), object lock mode, chunk size and storage class, which are set
  in the profile's ``rclone.conf`` remote.  ``reference_data`` owns the routing
  vocabulary and resolver (``remote_handler_key``, ``default_remote_handler_key``,
  ``remote_handler_keys``, ``is_rclone_profile``), and ``handler_factory``,
  ``profile test`` and ``check_rclone_dependency`` all resolve through it, so the
  CLI and the monitor runtime cannot disagree.  ``profile new`` stores ``s3``,
  ``profile import`` stores ``rclone`` (imported profiles are rclone-managed by
  definition, so an imported ``type = s3`` profile now runs through rclone) and
  ``profile edit`` gained a yes/no prompt to switch an S3 profile to rclone and
  back.  A missing or unknown value falls back to profile-type routing with a
  warning, which is the only role ``profile_type`` keeps in routing.

- ``mhub profile import`` now lets the user choose which rclone profiles to
  import instead of importing all or nothing.  The numbered list accepts ``0``
  to select all, a profile number to add individual entries one at a time, and
  Enter to stop; selecting nothing cancels the import.  The selection lives in
  the new ``ProfileImportSelector``, while ``config test`` keeps its existing
  Y/n confirmation.  ``DiagnosticUtil.check_profile_import`` was split into
  focused helpers and accepts an injectable ``rclone_config_path`` for testing.

- AWS provider detection in ``S3Factory.get_s3_client`` now matches the
  built-in ``"Amazon AWS S3"`` provider name (and any name containing
  ``amazon``) in addition to the bare rclone key ``"AWS"``, so CLI-created AWS
  profiles take the region-only path instead of a derived endpoint URL.
  ``ScheduledMonitorHandler.MONITOR_TYPE`` now reports the actual
  ``direction`` (backup or restore) rather than always backup, and
  ``setup_logging`` accepts a numeric YAML ``log_level`` without raising on
  ``.upper()``.

- Minor CLI cleanups: the interactive profile selector now redraws the profile
  list after an invalid entry (matching the monitor selector, which already
  did), and a local string variable in the command-event editor no longer
  shadows the ``prompt`` service it is built from.

- ``RcloneHandler.get_remote_path`` now falls back to the path's file name when
  the given path is not relative to ``base_monitor_path`` instead of raising
  ``ValueError``, matching ``S3Handler.get_remote_path``.  ``profile test`` also
  accepts a legacy comma-separated ``command_events`` string: it is parsed into
  a list first, so events are no longer validated one character at a time and
  reported as bogus "Invalid event(s)" entries.

- ``DiagnosticUtil.check_rclone_dependency`` now decides whether rclone is
  required from each profile's ``profile_type`` rather than a
  ``config["handler"]`` key that nothing in the application writes any more.
  Previously every profile was skipped, so ``config test`` silently passed even
  when an rclone-backed profile (e.g. ``ftp``, ``sftp``, ``drive``) existed and
  rclone was not installed.  The routing rule lives in the new
  ``reference_data.is_rclone_profile_type`` helper (command types and native
  ``s3`` profiles never need rclone); ``NATIVE_PROFILE_TYPES`` mirrors the
  native handler mapping and a new ``test_reference_data`` guard keeps the two
  from drifting.  Tests cover native/command profiles, rclone-backed profiles,
  a missing rclone, and a stale ``config["handler"]`` key.

- ``mhub database info`` now reports whether the database file actually exists
  instead of only printing its configured location. A missing database is
  reported as ``SQLite database does not exist: <path>`` with a hint to run
  ``database init``; an existing one is confirmed with ``SQLite database
  exists: <path>``. The check uses ``os.path.exists`` on the resolved path, so
  it stays read-only and never opens the lazy connection (which would have
  created the very file it is reporting on).

- Added an explicit ``SQLiteHandler.is_closed()`` state accessor (True once
  ``close()`` has been called, regardless of whether the lazy connection was
  ever opened). ``DatabaseTestData.remove_test_data()`` now uses it instead of
  probing ``sqlite_handler.connection is None``, a condition that could never
  be true because ``close()`` leaves the (closed) connection object in place.
  The guard now actually detects a closed handler and skips cleanup as its
  comment always claimed.

- ``SQLiteHandler`` now opens its connection lazily, on first use, instead of
  in ``__init__``. Constructing a handler no longer touches the filesystem, so
  read-only commands such as ``mhub version``, ``mhub database info`` and
  ``mhub database version`` no longer silently create ``data/monitorhub.db``
  before ``database init`` has ever run. The ``connection`` attribute became a
  property that connects (and creates the file) on first access; ``close()``
  remains idempotent and now marks the handler closed so a never-opened handler
  cannot be resurrected, while an already-open connection is still returned
  after close as before. ``is_initialized()`` reports a missing database file as
  uninitialised without opening it. New lifecycle tests pin the laziness,
  first-use open, and closed-handler behaviour, and a new ``test_commands``
  case asserts the read-only commands leave the database file absent. The
  generated Commands diagram was regenerated.

- ``monitor edit`` now validates the monitor-type selection like every other
  prompt.  ``MonitorCommands._edit_basic_fields`` previously called
  ``int(...)`` on the raw ``input()`` result, so a typo (``abc``) raised an
  uncaught ``ValueError``, an out-of-range number (``99``) raised
  ``IndexError``, and ``0`` silently selected the last type via ``[-1]``.
  The type prompt now goes through ``prompt_choice`` with the new shared
  ``validate_monitor_type_number`` helper (also used by ``monitor new``),
  which rejects non-digits and values outside ``1..len(monitor_types)`` and
  re-asks; an empty entry still keeps the current type.  New unit tests cover
  the non-numeric, out-of-range and ``0`` cases.

- Replaced the "implemented profile type" vocabulary with a single
  profile-type -> handler mapping.  ``RemoteHandlerFactory`` is gone: the
  remote mapping is now a declarative ``REMOTE_HANDLERS`` table in the new
  ``app.monitor.handler_factory`` module, and ``HandlerFactory.get_handler``
  is the one high-level factory.  Dispatch is purely by profile type --
  ``s3`` -> ``S3Handler``, ``event_command`` -> ``CommandActionHandler``, and
  any type absent from the table -> ``RcloneHandler`` -- so the
  ``is_profile_type_implemented`` / ``get_implemented_profile_types`` /
  ``filter_implemented_profiles`` helpers and ``NATIVE_REMOTE_PROFILE_TYPES``
  are removed.  The profile-type -> category table stays in
  ``reference_data`` because it drives the CLI prompts and editor dispatch.
  ``profile edit`` now lists every profile but only the ``s3`` remote type has
  a wizard; other remote types are refused with the rclone-config hint, which
  rclone imports now store on the profile (``comment`` and ``important``).
  The generated ActionHandler diagram now includes ``HandlerFactory``.
- ``setup_logging`` gains a ``dependency_log_level`` parameter (and the
  ``MONITORHUB_DEPENDENCY_LOG_LEVEL`` environment variable) to debug the
  third-party libraries it silences by default.  The default WARNING floor
  for ``boto3``/``botocore``/``s3transfer``/``urllib3`` stays unchanged, but
  an explicit level - e.g. the new ``--dependency-log-level DEBUG`` CLI flag
  on ``mhub.py``, ``run_monitor.py`` and the interactive test script - now
  takes precedence over it, so s3/boto3 log traffic can be turned up from
  the command line without touching every other package.  The flag is
  forwarded to monitor child processes (``build_commands`` ->
  ``MonitorCommands`` -> ``MonitorProcessManager``), so a ``monitor start``
  child inherits the same dependency level as its parent.  Precedence in
  ``setup_logging``: explicit argument, then the env var, then the
  ``quiet_dependencies`` WARNING floor.  ``--log-level`` continues to govern
  only the app/root level.  New unit tests pin the precedence, scoping and
  child-process forwarding.

- ``DiagnosticUtil``'s constructor no longer mutates the module logger.  When
  no logger was injected it previously forced ``logging.DEBUG`` on the shared
  ``logging.getLogger(__name__)`` logger and appended a fresh
  ``StreamHandler`` on every construction, so building more than one
  ``DiagnosticUtil`` stacked handlers on the module logger and duplicated
  every log line.  It now uses the same injection fallback as the
  ``StoppableWorker`` base class (``logger or logging.getLogger(__name__)``),
  leaving level and handlers to the ``setup_logging`` configuration.
  ``tests/test_diagnostic_util.py`` was converted from an orphaned manual
  script into unit tests pinning that the module logger stays unmutated across
  repeated ``DiagnosticUtil(sqlite_handler=..., logger=None)`` constructions.

- Console-policy/log silencing moved out of the CLI wiring factory
  (``build_commands``) and into ``setup_logging`` behind a documented
  ``quiet_dependencies: bool = True`` parameter.  ``setup_logging`` now floors
  ``boto3``/``botocore``/``s3transfer``/``urllib3`` to WARNING inside its
  clean-slate block (child loggers inherit the floor through the logger
  hierarchy, so only those four top-level names are touched); pass
  ``quiet_dependencies=False`` to debug those libraries.  ``build_commands``
  no longer mutates the ``MonitorHub`` logger - it previously forced level
  WARNING and ``propagate=False``, which (because that logger has no handlers
  of its own) silently dropped every application log record and made
  ``--log-level DEBUG`` a no-op.  ``--log-level DEBUG`` now works end to end,
  and the monitor subprocess (``run_monitor.py``) gains the same dependency
  silencing.  The default ``conf/log.yaml`` level was lowered from DEBUG to
  INFO to keep the default console calm (DEBUG stays opt-in).  New unit tests
  in ``tests/test_logger_setup.py`` pin the opt-in/scoped silencing, the
  clean-slate handler behaviour and the level-resolution precedence, and a
  regression test in ``tests/test_commands.py`` pins that ``build_commands``
  has no log side effects.

- ``SQLiteHandler`` now releases its database connection deterministically. The
  implicit ``__del__`` hook — which could raise ``AttributeError`` when
  ``__init__`` failed part-way, could not be relied on during interpreter
  shutdown, and every ``Exception ignored in: <function SQLiteHandler.__del__>``
  on stderr — was replaced by a ``weakref.finalize`` registered in ``__init__``.
  The finalizer callback receives the connection object itself (not ``self``),
  so it is safe for partially-constructed objects and at shutdown, and fires at
  most once. ``close()`` is now idempotent and safe on a partially-constructed
  handler; garbage collection and interpreter exit are covered by the finalizer
  as a safety net. ``mhub.py`` now closes the ``SQLiteHandler`` built by
  ``build_commands()`` in a ``finally`` block, so the connection is returned to
  the OS at CLI exit instead of being left to garbage collection. Four new
  lifecycle tests in ``tests/test_sqlite_handler.py`` pin the behaviour: close
  idempotence, close-on-garbage-collection, the partial-init no-op, and the
  context-manager path.

- Exception-handler hygiene (the ``BLE001`` blind-except rule is now enforced
  by the lint configuration): the per-directory ``app/*/ruff.toml`` files were
  folded into a single ``[tool.ruff.lint]`` table in ``pyproject.toml`` that
  explicitly enables the blind-except (``BLE001``) and import-sorting
  (``I001``) rules, so the quality bar no longer depends on the ruff version's
  default rule set. Handlers that could be narrowed now catch specific types
  (``OSError``, ``ValueError``, ``subprocess.SubprocessError``,
  ``sqlite3.Error``, ``BotoCoreError``, ``UnicodeDecodeError``) instead of
  ``Exception``; deliberately broad guards (the debounce/action/queue workers,
  the S3 ``_failure_from_exception`` boundary, the monitor status poller and
  process bookkeeping) keep ``except Exception`` with a one-line justification
  next to their ``noqa``. ``SQLiteHandler`` mutators now log and re-raise only
  ``sqlite3.Error`` (the ``transaction`` and migration context managers already
  roll back on any exception). The ``try/except/self.fail`` wrapper was removed
  from 30 tests in ``tests/test_sqlite_handler.py`` — an exception in a test
  already fails the test with a full traceback — and 11 import blocks were
  re-sorted for the ``I001`` rule (a consequence of removing the per-directory
  configs).

- ``DiagnosticUtil`` moved from ``app/utils/`` to ``app/cli/``: it drives an
  interactive CLI report (prompting the user, printing summary tables, running
  rclone and copy/delete probes), so it now lives with its only consumers
  (``commands.py``, ``profile_commands.py``, ``monitor_commands.py``). With
  that, ``app/utils`` no longer imports ``app.cli`` at all, and the lazy
  ``DiagnosticUtil`` import inside ``MonitorCommands.test()`` became a normal
  top-level import (there was no circular import to guard against).
  ``tests/test_import_layering.py`` now pins the rule down statically: no
  module under ``app/utils/`` or ``app/monitor/`` may import ``app.cli``.

- The schema-version registry moved out of the CLI package (from
  ``app/cli/schema_versioning.py`` to ``app/utils/schema_versioning.py``), so
  ``app/utils/sqlite_handler.py`` no longer imports ``app.cli``. The lazy
  ``_remote_handler_factory`` workaround in ``app/utils/reference_data.py`` was
  removed in favour of a normal top-level import; there was no circular import
  between that module and the monitor package to guard against.

- The monitor's status poller now retries a heartbeat write once when SQLite
  reports a transient lock ("database is locked") before it warns and, as
  before, continues with the next poll. The two attempts are separated by a
  short pause that a shutdown request interrupts, so stopping a monitor is
  never delayed by a retry. The poll tick is split into
  ``MonitorRunContext._write_heartbeat`` and ``_poll_status_once``, so both
  halves are unit-testable without a running thread.

- Database constraint violations are translated into user-facing messages
  instead of raw SQLite text (new ``app/cli/db_error_messages.py``). A duplicate
  monitor name now reports "Monitor name: X already exists" from
  ``monitor new``, ``monitor edit`` and ``database sample-data``, or "A monitor
  with that name already exists." if it reaches the CLI boundary; a mapping whose
  profile was deleted reports "The referenced record does not exist (it may have
  been deleted)." Previously these surfaced as
  "Database error: UNIQUE constraint failed: monitors.name" with an irrelevant
  "is the database initialised?" hint.

- ``SQLiteHandler`` reads now go through a ``read_cursor`` context manager (the
  read-only twin of ``transaction``), so every reader logs a database error and
  re-raises it with the same messages-and-raising convention as the mutators.
  ``get_current_schema_version`` and ``get_schema_versions`` no longer probe for
  the ``schema_version`` table themselves: like every other reader they just
  query it, returning ``""``/``[]`` only when the table exists but is empty, and
  raising when the schema is missing. ``mhub database version`` therefore
  reports "Database is not initialised. Run 'database init' first." for an
  uninitialised database, rather than relying on an in-band empty string.

- ``SQLiteHandler`` now follows a single error convention: an expected absence
  returns ``None`` (unknown monitor/profile) or ``False`` (an UPDATE/DELETE that
  matched no row), while an unexpected ``sqlite3.Error`` is logged and re-raised
  instead of being swallowed as ``False``. ``get_monitor``/``get_profile``
  return ``None`` rather than an empty dict, ``update_monitor``/``update_profile``
  return ``None`` when the row does not exist, and a duplicate
  ``monitor_profile_map`` insert returns ``False``. The CLI (``mhub.py``) and the
  monitor process (``run_monitor.py``) now report database errors with a clear
  message and exit code 1 instead of printing a traceback, and a monitor that
  cannot record its own state fails loudly instead of leaving a stale
  ``running`` record.

- Remote storage operations now return a typed result. The ad-hoc
  ``(result_code, result_output)`` tuple is replaced by ``RemoteResult``
  (``app/monitor/remote_result.py``), which carries ``ok``, ``message``,
  ``code``, a classified ``RemoteErrorKind`` (not-found, access-denied,
  timeout, transient, fatal) and a ``retryable`` flag. ``RemoteHandler``,
  ``S3Handler``, ``RcloneHandler`` (including ``run_command``) and their
  callers were updated. ``file_exists`` can now distinguish an expected
  "the path does not exist" from a check that failed (e.g. access denied),
  and failed copies/deletes are logged with their reason instead of being
  discarded. Behaviour is otherwise unchanged.

- Internal refactor: ``run_monitor_main()`` in ``app/monitor/run_monitor.py`` is
  decomposed into the lifecycle phases ``parse_args``, ``get_monitor_context``,
  ``run_until_shutdown`` and ``teardown``, which share a ``MonitorRunContext``
  dataclass. The public entry points (``run_monitor_main`` and ``main``) and
  the behaviour of a standalone monitor process are unchanged; only the
  internal structure moved.

- Internal refactor: the monitor lifecycle phases are now methods of
  ``MonitorRunContext`` (``get_monitor_context``, ``run_until_shutdown`` and
  ``teardown``), with a ``run()`` convenience that combines them;
  ``parse_args`` stays a module-level function. Behaviour and the public entry
  points are unchanged.

- Internal refactor: the oversized ``MonitorCommands`` and ``ProfileCommands``
  handlers are split into focused collaborators. ``MonitorProcessManager``
  now owns the launch/track/kill/reap mechanics of monitor child processes,
  ``MonitorSelector``/``ProfileSelector`` own interactive list selection, and
  ``ProfileEditor`` owns the ``profile new``/``profile edit`` prompt flows.
  The public command handlers and their behaviour are unchanged; only the
  internal structure moved.

- The ``monitor edit`` and ``monitor new`` profile-selection prompts are faster
  and more consistent: the available-profiles list is redrawn after every
  selection and the list is stopped by pressing Enter (``Enter profile id to
  add. To stop just press Enter:``). The per-profile
  ``Do you want to add another profile? (y/N)`` confirmation has been removed.

- Internal refactor: ``PromptService`` now exposes reusable ``prompt_required``,
  ``prompt_choice`` and ``prompt_yes_no`` helpers, and the interactive
  ``monitor``/``profile``/``database`` command flows use them instead of
  repeating ad-hoc input loops. There is no user-facing behaviour change,
  except that the destructive ``database init --recreate`` and Rclone
  profile-import confirmations now also accept ``yes``/``no`` (previously only
  ``y`` was accepted).

- Internal refactor: the repeated ``-i/--<object>-id`` / ``-n/--<object>-name``
  argument definitions in ``mhub.py`` are now generated by a single
  ``_add_selector_args`` helper. There is no user-facing behaviour change (the
  generated help text is identical).

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
- New ``app/utils/schema_versioning.py`` module centralises version comparison,
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
