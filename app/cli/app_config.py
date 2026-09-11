import logging
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "monitorhub" / "config.yaml"


class AppConfig:
    """Manages application-level user configuration stored in ~/.config/monitorhub/config.yaml."""

    def __init__(self, config_path: Path | str | os.PathLike[str] | None = None, logger: logging.Logger | None = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.logger = logger or logging.getLogger(__name__)
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        """Loads the configuration from YAML file if it exists."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        self._data = content
                    else:
                        self._data = {}
            except yaml.YAMLError as e:
                self.logger.warning(f"Failed to parse YAML configuration file at {self.config_path}: {e}")
                self._data = {}
            except Exception as e:  # noqa: BLE001
                self.logger.warning(f"Failed to read configuration file at {self.config_path}: {e}")
                self._data = {}
        else:
            self._data = {}
        return self._data

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def get_default_db_dir(self, fallback: str = "data") -> str:
        """
        Resolves the default database directory from configuration.
        
        Supports configuration formats:
        1. Named database mapping:
           default_database: dev
           databases:
             dev: testdb/dev
             prod: /var/lib/monitorhub/db
             
        2. Direct string path:
           default_database: testdb/dev
           
        Falls back to `fallback` (default "data") if not configured or found.
        """
        if not self._data:
            return fallback

        default_db = self._data.get("default_database")
        if not default_db:
            return fallback

        databases = self._data.get("databases", {})
        if isinstance(databases, dict) and default_db in databases:
            db_val = databases[default_db]
            if isinstance(db_val, str):
                return db_val
            if isinstance(db_val, dict) and "path" in db_val:
                return str(db_val["path"])

        if isinstance(default_db, str):
            return default_db

        return fallback
