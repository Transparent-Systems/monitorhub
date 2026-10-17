"""Unit tests for the shared project-root resolution helpers."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.utils.project_paths import project_conf, project_root

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestProjectRoot(unittest.TestCase):
    def test_source_run_roots_at_repository(self):
        self.assertEqual(project_root(), REPO_ROOT)

    def test_project_conf_points_into_conf_folder(self):
        self.assertEqual(project_conf("log.yaml"), REPO_ROOT / "conf" / "log.yaml")

    def test_frozen_run_roots_at_executable_directory(self):
        exe = Path(tempfile.mkdtemp()) / "mhub"
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "executable", str(exe)
        ):
            self.assertEqual(project_root(), exe.parent)
            self.assertEqual(project_conf("config.yaml"), exe.parent / "conf" / "config.yaml")


if __name__ == "__main__":
    unittest.main()