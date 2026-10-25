"""Unit tests for :mod:`app.webgui.launcher`.

The launcher is the single place that knows how to boot Streamlit, shared by
``mhub webgui`` (source) and the frozen ``mhub-gui`` binary. These tests pin down
the script location, the default flags, the database override and the two
failure paths, without ever starting a real server.
"""

import builtins
import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from app.utils.app_config import DB_DIR_ENV_VAR
from app.utils.project_paths import resource_root
from app.webgui import launcher


class TestScriptPath(unittest.TestCase):
    def test_points_at_the_home_page_next_to_its_pages_folder(self):
        script = launcher.script_path()
        self.assertEqual(script, resource_root() / "app" / "webgui" / "home.py")
        self.assertTrue(script.is_file(), script)
        # Streamlit discovers the sidebar pages from the folder next to the
        # main script, so that folder must ship alongside it.
        self.assertTrue((script.parent / "pages").is_dir())


class TestMain(unittest.TestCase):
    def _run(self, argv=None):
        """Run launcher.main with Streamlit's CLI mocked; return (code, argv)."""
        captured: dict[str, list[str]] = {}
        original_argv = sys.argv
        fake_cli = mock.Mock()
        fake_cli.main.side_effect = lambda: captured.update(argv=list(sys.argv))

        # Patch the attribute on the real `streamlit.web` package so the
        # launcher's `from streamlit.web import cli` binds the fake without ever
        # starting a server, regardless of what earlier tests imported.
        try:
            with mock.patch("streamlit.web.cli", fake_cli, create=True):
                code = launcher.main(argv)
        finally:
            sys.argv = original_argv
        return code, captured.get("argv", [])

    def test_builds_a_streamlit_run_command_vector(self):
        code, argv = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(argv[0], "streamlit")
        self.assertEqual(argv[1], "run")
        self.assertEqual(argv[2], str(launcher.script_path()))

    def test_applies_the_desktop_defaults(self):
        _, argv = self._run()
        for flag in launcher.DEFAULT_FLAGS:
            self.assertIn(flag, argv)

    def test_forces_development_mode_off(self):
        # Inside a PyInstaller bundle Streamlit defaults global.developmentMode
        # to True (its config.py is not in site-packages), which makes an
        # explicit server.port a hard error.
        _, argv = self._run()
        self.assertIn("--global.developmentMode=false", argv)

    def test_user_arguments_come_last(self):
        _, argv = self._run(["--server.port=8600"])
        self.assertEqual(argv[-1], "--server.port=8600")

    def test_missing_script_reports_an_error(self):
        output = io.StringIO()
        with mock.patch.object(
            launcher, "script_path", return_value=Path("/nonexistent/home.py")
        ), contextlib.redirect_stderr(output):
            code = launcher.main([])
        self.assertEqual(code, 1)
        self.assertIn("not found", output.getvalue())

    def test_missing_streamlit_reports_guidance(self):
        output = io.StringIO()
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name.startswith("streamlit"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with mock.patch(
            "builtins.__import__", side_effect=blocked
        ), contextlib.redirect_stderr(output):
            code = launcher.main([])
        self.assertEqual(code, 1)
        self.assertIn("mhub-gui", output.getvalue())


class TestDatabaseOverride(unittest.TestCase):
    """``-d/--db-dir`` reaches the pages through the environment."""

    def _start(self, **kwargs) -> int:
        with mock.patch("streamlit.web.cli", mock.Mock(), create=True):
            return launcher.main([], **kwargs)

    def test_db_dir_is_exported_for_the_pages(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DB_DIR_ENV_VAR, None)
            self._start(db_dir="/tmp/mhub-db")
            self.assertEqual(os.environ.get(DB_DIR_ENV_VAR), "/tmp/mhub-db")

    def test_absent_db_dir_leaves_the_environment_untouched(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DB_DIR_ENV_VAR, None)
            self._start()
            self.assertNotIn(DB_DIR_ENV_VAR, os.environ)

    def test_pages_resolve_the_exported_directory(self):
        # End to end: launcher exports, AppConfig resolves. This is the contract
        # the GUI pages rely on when they build their SQLiteHandler.
        from app.utils.app_config import AppConfig

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DB_DIR_ENV_VAR, None)
            self._start(db_dir="/tmp/mhub-db")
            self.assertEqual(AppConfig().get_default_db_dir(fallback="data"), "/tmp/mhub-db")


if __name__ == "__main__":
    unittest.main()
