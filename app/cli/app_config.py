import logging
import os
from pathlib import Path
from typing import Any

import yaml

from app.utils.project_paths import project_conf

DEFAULT_CONFIG_PATH = project_conf("config.yaml")


class AppConfig:
    """Manages application-level configuration stored in <project root>/conf/config.yaml."""

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
            except (OSError, UnicodeDecodeError) as e:
                self.logger.warning(f"Failed to read configuration file at {self.config_path}: {e}")
                self._data = {}
        else:
            self._data = {}
        return self._data

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def project_root(self) -> Path:
        """Directory that owns this config: the parent of the conf/ folder."""
        return self.config_path.resolve().parent.parent

    def _resolve_db_dir(self, value: str) -> str:
        """Resolve a database directory to a stable absolute path.

        Absolute paths pass through unchanged; relative paths are anchored at
        :meth:`project_root` so the database location does not depend on the
        current working directory.
        """
        path = Path(value)
        if path.is_absolute():
            return value
        return str(self.project_root() / path)

    def get_default_db_dir(self, fallback: str = "data") -> str:
        """
        Resolves the default database directory from configuration.

        Relative paths are resolved against the config's project folder (the
        directory that contains ``conf/``), so the database location is
        independent of the current working directory.

        Supports configuration formats:
        1. Named database mapping:
           default_database: dev
           databases:
             dev: testdb/dev
             prod: /var/lib/monitorhub/db
             
        2. Direct string path:
           default_database: testdb/dev
           
        Falls back to `fallback` (default "data", resolved against the same
        project folder) if not configured or found.
        """
        if not self._data:
            return self._resolve_db_dir(fallback)

        default_db = self._data.get("default_database")
        if not default_db:
            return self._resolve_db_dir(fallback)

        databases = self._data.get("databases", {})
        if isinstance(databases, dict) and default_db in databases:
            db_val = databases[default_db]
            if isinstance(db_val, str):
                return self._resolve_db_dir(db_val)
            if isinstance(db_val, dict) and "path" in db_val:
                return self._resolve_db_dir(str(db_val["path"]))

        if isinstance(default_db, str):
            return self._resolve_db_dir(default_db)

        return self._resolve_db_dir(fallback)
