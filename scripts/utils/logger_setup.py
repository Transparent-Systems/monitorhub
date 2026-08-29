import logging
import os
from logging.handlers import RotatingFileHandler

import yaml


def setup_logging(
    log_config_path: str | os.PathLike[str],
    log_level: str | None = None,
    log_file: str | None = None,
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

    Returns:
        A tuple of (:class:`logging.Logger`, config dict).
    """
    config_path = str(log_config_path)

    # --- Load configuration ----------------------------------------------------
    if not os.path.exists(config_path):
        print(f"Log configuration file '{config_path}' does not exist. Creating default.")
        os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write("version: 1.0.0\n")
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

    # --- Ensure log folder exists ------------------------------------------------
    if not os.path.exists(LOG_FOLDER):
        os.makedirs(LOG_FOLDER, exist_ok=True)
        print(f"Log folder '{LOG_FOLDER}' created.")

    # --- Handlers ---------------------------------------------------------------
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )

    file_handler = RotatingFileHandler(
        os.path.join(LOG_FOLDER, LOG_FILE),
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
    effective_level = (
        log_level
        or os.environ.get("MONITORHUB_LOG_LEVEL")
        or log_config.get("log_level", "INFO")
    ).upper()
    root_logger.setLevel(effective_level)

    # Remove any pre-existing handlers (clean slate).
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger("MonitorHub"), log_config
