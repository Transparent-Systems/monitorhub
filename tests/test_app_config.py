import shutil
import tempfile
import unittest
from pathlib import Path

import yaml
from app.cli.app_config import AppConfig


class TestAppConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_config_file_returns_fallback(self):
        config = AppConfig(config_path=self.config_path)
        self.assertEqual(config.get_default_db_dir(fallback="data"), "data")

    def test_config_with_direct_default_database(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"default_database": "testdb/dev"}, f)

        config = AppConfig(config_path=self.config_path)
        self.assertEqual(config.get_default_db_dir(), "testdb/dev")

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
        self.assertEqual(config.get_default_db_dir(), "testdb/dev")

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


if __name__ == "__main__":
    unittest.main()
