import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

from app.utils.project_paths import project_root
from version import VERSION_STRING

# Third-party library loggers whose chatter is silenced by default.
DEPENDENCY_LOGGER_NAMES = ("boto3", "botocore", "s3transfer", "urllib3")


def _resolve_dependency_level(dependency_log_level: str | None) -> int | None:
    """Resolve the effective level for the third-party library loggers.

    Precedence: explicit ``dependency_log_level`` argument, then the
    ``MONITORHUB_DEPENDENCY_LOG_LEVEL`` environment variable.  Returns None
    when neither is set, meaning the ``quiet_dependencies=True`` WARNING floor
    (the default) applies.
    """
    level = dependency_log_level or os.environ.get("MONITORHUB_DEPENDENCY_LOG_LEVEL")
    if level is None:
        return None
    resolved = logging.getLevelNamesMapping().get(str(level).upper())
    if resolved is None:
        raise ValueError(
            f"Invalid dependency log level '{level}'. Choose from "
            "DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )
    return resolved


def setup_logging(
    log_config_path: str | os.PathLike[str],
    log_level: str | None = None,
    log_file: str | None = None,
    quiet_dependencies: bool = True,
    dependency_log_level: str | None = None,
) -> tuple[logging.Logger, dict]:
    """Read a YAML log configuration file and configure the root logger.

    Sets up a RotatingFileHandler and a StreamHandler directly on the root
    logger (no async queue).  Returns a tuple of (logger, log_config dict)
    for use by the main entry-point.

    Args:
        log_config_path: Path to the YAML file containing a ``logging`` key.
        log_level: Optional explicit log level that overrides both the
            ``MONITORHUB_LOG_LEVEL`` environment variable and the YAML
            ``logging.log_level`` value.
        log_file: Optional explicit log file name that overrides the YAML
            ``logging.file_name`` value.
            Relative ``logging.folder`` / ``logging.file_name`` values resolve
            against the project root (the folder that owns the application), so
            log files land in a stable location regardless of the current
            working directory; absolute paths are used verbatim.
        quiet_dependencies: When True (the default) and no explicit
            ``dependency_log_level`` is given, the ``boto3``, ``botocore``,
            ``s3transfer`` and ``urllib3`` loggers are floored to WARNING so
            their INFO/DEBUG chatter does not flood the console or the log
            file.  Only those four top-level library names are touched; child
            loggers (e.g. ``botocore.credentials``,
            ``urllib3.connectionpool``) inherit the floor through the logger
            hierarchy.  This console-policy lives here - not in the CLI wiring
            factory - and is applied inside the clean-slate block, so the
            ``MonitorHub`` logger still honours the effective ``log_level``
            (``--log-level DEBUG`` works end to end).
        dependency_log_level: Optional explicit log level for the third-party
            dependency loggers (``boto3``, ``botocore``, ``s3transfer``,
            ``urllib3``).  Takes precedence over both the
            ``MONITORHUB_DEPENDENCY_LOG_LEVEL`` environment variable and the
            ``quiet_dependencies`` WARNING floor, and lets you debug those
            libraries without touching every other package.  E.g. pass
            ``"DEBUG"`` (plus ``log_level="DEBUG"``) to see the full boto3
            request/response traffic.  Child loggers inherit the level through
            the logger hierarchy.

    Returns:
        A tuple of (:class:`logging.Logger`, config dict).
    """
    config_path = str(log_config_path)

    # --- Load configuration ----------------------------------------------------
    if not os.path.exists(config_path):
        print(f"Log configuration file '{config_path}' does not exist. Creating default.")
        os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write(f"version: {VERSION_STRING}\n")
            fh.write("logging:\n")
            fh.write("  file_name: monitorhub.log\n")
            fh.write("  folder: logs\n")
            fh.write("  max_bytes: 10485760\n")
            fh.write("  max_backup_count: 5\n")
            fh.write("  # log_level: DEBUG | INFO | WARNING | ERROR | CRITICAL\n")
            fh.write("  log_level: INFO\n")

    with open(config_path, "r", encoding="utf-8") as fh:
        full_config = yaml.safe_load(fh)

    log_config = full_config.get("logging") if isinstance(full_config, dict) else None
    if log_config is None:
        print(f"Configuration for 'logging' not found in {config_path}.")
        raise ValueError(f"Configuration for 'logging' not found in {config_path}")

    LOG_FILE = log_file or log_config.get("file_name", "monitorhub.log")
    LOG_FOLDER = log_config.get("folder", "logs")
    MAX_BYTES = log_config.get("max_bytes", 10 * 1024 * 1024)
    BACKUP_COUNT = log_config.get("max_backup_count", 5)

    # --- Resolve the log file against the project root --------------------------
    # A relative ``folder`` / ``file_name`` in the logging config is anchored at
    # the project root (the folder that owns the application) so log files end
    # up in a stable place no matter what the current working directory is.
    # Absolute paths pass through verbatim.
    file_path = Path(LOG_FILE)
    if file_path.is_absolute():
        log_dir = file_path.parent
    else:
        folder_path = Path(LOG_FOLDER)
        if folder_path.is_absolute():
            log_dir = folder_path
        else:
            log_dir = project_root() / LOG_FOLDER
        file_path = log_dir / LOG_FILE

    # --- Ensure the log folder exists -------------------------------------------
    if not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)
        print(f"Log folder '{log_dir}' created.")

    # --- Handlers ---------------------------------------------------------------
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )

    file_handler = RotatingFileHandler(
        str(file_path),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # --- Root logger ------------------------------------------------------------
    root_logger = logging.getLogger()

    # Resolve the effective level: explicit argument wins, then the
    # MONITORHUB_LOG_LEVEL environment variable, then the YAML value.
    # Coerce to str first: a non-string YAML value (e.g. an unquoted number)
    # would otherwise raise AttributeError on .upper().
    raw_level = (
        log_level
        or os.environ.get("MONITORHUB_LOG_LEVEL")
        or log_config.get("log_level", "INFO")
    )
    if isinstance(raw_level, int) and not isinstance(raw_level, bool):
        # logging accepts a numeric level directly (e.g. 20 == INFO); coercing
        # it to a string would make setLevel reject "20".
        effective_level: int | str = raw_level
    else:
        # Coerce to str first: a non-string YAML value (e.g. an unquoted float)
        # would otherwise raise AttributeError on .upper().
        effective_level = str(raw_level).upper()
    root_logger.setLevel(effective_level)

    # Remove any pre-existing handlers (clean slate).
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # Floor verbose third-party libraries to WARNING (opt-in via
    # quiet_dependencies).  Setting the top-level name also covers every child
    # logger (e.g. ``botocore.credentials``, ``urllib3.connectionpool``)
    # through the logger hierarchy.  An explicit dependency_log_level (from the
    # argument or the MONITORHUB_DEPENDENCY_LOG_LEVEL env var) takes precedence
    # over the WARNING floor, e.g. to debug the boto3 request/response traffic.
    dependency_level = _resolve_dependency_level(dependency_log_level)
    if dependency_level is None and quiet_dependencies:
        dependency_level = logging.WARNING
    if dependency_level is not None:
        for name in DEPENDENCY_LOGGER_NAMES:
            logging.getLogger(name).setLevel(dependency_level)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger("MonitorHub"), log_config
