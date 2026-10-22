import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from app.utils.app_config import DB_DIR_ENV_VAR, AppConfig


class TestAppConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        self.config_path = self.project_root / "conf" / "config.yaml"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_config_file_returns_fallback(self):
        config = AppConfig(config_path=self.config_path)
        self.assertEqual(
            config.get_default_db_dir(fallback="data"), str(self.project_root / "data")
        )

    def test_config_with_direct_default_database(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"default_database": "testdb/dev"}, f)

        config = AppConfig(config_path=self.config_path)
        self.assertEqual(
            config.get_default_db_dir(), str(self.project_root / "testdb/dev")
        )

    def test_config_with_named_database_mapping(self):
        content = {
            "default_database": "dev",
            "databases": {
                "dev": "testdb/dev",
                "prod": "/var/lib/monitorhub/db",
            },
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f)

        config = AppConfig(config_path=self.config_path)
        self.assertEqual(
            config.get_default_db_dir(), str(self.project_root / "testdb/dev")
        )

    def test_config_with_named_database_dict_mapping(self):
        content = {
            "default_database": "prod",
            "databases": {
                "dev": {"path": "testdb/dev"},
                "prod": {"path": "/var/lib/monitorhub/db"},
            },
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f)

        config = AppConfig(config_path=self.config_path)
        self.assertEqual(config.get_default_db_dir(), "/var/lib/monitorhub/db")

    def test_default_config_path_is_project_conf(self):
        """Config is read from <project root>/conf/config.yaml, never ~/.config."""
        expected = Path(__file__).resolve().parents[1] / "conf" / "config.yaml"
        self.assertEqual(AppConfig().config_path, expected)
        self.assertTrue(expected.exists())
        # The real project config maps the default database to the project
        # folder's testdb/dev, resolved to an absolute path.
        self.assertEqual(
            AppConfig().get_default_db_dir(),
            str(Path(__file__).resolve().parents[1] / "testdb/dev"),
        )

    def test_relative_paths_resolve_against_config_project_root(self):
        """Relative db paths anchor at the config's project folder, not the CWD."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"default_database": "data"}, f)

        config = AppConfig(config_path=self.config_path)
        self.assertEqual(config.get_default_db_dir(), str(self.project_root / "data"))

    def test_absolute_db_paths_pass_through(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"default_database": "/srv/monitorhub/db"}, f)

        config = AppConfig(config_path=self.config_path)
        self.assertEqual(config.get_default_db_dir(), "/srv/monitorhub/db")

    def test_project_root_is_parent_of_conf_folder(self):
        config = AppConfig(config_path=self.config_path)
        self.assertEqual(config.project_root(), self.project_root)


class TestDbDirEnvironmentOverride(unittest.TestCase):
    """``MONITORHUB_DB_DIR`` is how the GUI receives -d/--db-dir."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        self.config_path = self.project_root / "conf" / "config.yaml"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_env_var_wins_over_the_config_file(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"default_database": "testdb/dev"}, f)

        config = AppConfig(config_path=self.config_path)
        with mock.patch.dict(os.environ, {DB_DIR_ENV_VAR: "/tmp/from-env"}):
            self.assertEqual(config.get_default_db_dir(), "/tmp/from-env")

    def test_env_var_applies_without_a_config_file(self):
        config = AppConfig(config_path=self.config_path)
        with mock.patch.dict(os.environ, {DB_DIR_ENV_VAR: "/tmp/from-env"}):
            self.assertEqual(
                config.get_default_db_dir(fallback="data"), "/tmp/from-env"
            )

    def test_relative_env_var_anchors_at_the_project_root(self):
        config = AppConfig(config_path=self.config_path)
        with mock.patch.dict(os.environ, {DB_DIR_ENV_VAR: "testdb/env"}):
            self.assertEqual(
                config.get_default_db_dir(),
                str(self.project_root / "testdb" / "env"),
            )

    def test_empty_env_var_falls_back_to_the_configuration(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"default_database": "testdb/dev"}, f)

        config = AppConfig(config_path=self.config_path)
        with mock.patch.dict(os.environ, {DB_DIR_ENV_VAR: ""}):
            self.assertEqual(
                config.get_default_db_dir(), str(self.project_root / "testdb/dev")
            )


if __name__ == "__main__":
    unittest.main()
