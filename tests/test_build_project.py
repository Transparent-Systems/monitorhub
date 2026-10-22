"""Unit tests for :mod:`build_project`.

``build_project`` is a standalone script, so these tests import it directly and
verify the PyInstaller command it assembles: invoking PyInstaller through the
running interpreter (``sys.executable -m PyInstaller``) instead of a bare,
PATH-dependent ``pyinstaller``. Subprocess execution and filesystem cleanup are
mocked so nothing is actually built or deleted.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import build_project


class TestBuildCommand(unittest.TestCase):
    def _captured_argv(
        self, platform: str, icon_exists: bool = False, target: str = "cli"
    ) -> list[str]:
        """Run build_executable with side effects mocked; return the argv used."""
        with mock.patch.object(build_project.sys, "platform", platform), mock.patch.object(
            build_project, "clean_previous_builds"
        ), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, mock.patch.object(
            build_project.os.path, "exists", return_value=icon_exists
        ):
            build_project.build_executable(target)
        return run.call_args.args[0]

    def test_invokes_pyinstaller_through_the_running_interpreter(self):
        argv = self._captured_argv("linux")
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1:3], ["-m", "PyInstaller"])

    def test_bare_pyinstaller_is_never_used(self):
        argv = self._captured_argv("linux")
        self.assertNotIn("pyinstaller", argv)

    def test_common_flags_and_main_script(self):
        argv = self._captured_argv("linux")
        self.assertIn("--onefile", argv)
        self.assertEqual(argv[argv.index("--name") + 1], build_project.APP_NAME)
        self.assertIn("--hidden-import=app.monitor.run_monitor", argv)
        self.assertEqual(argv[-1], build_project.MAIN_SCRIPT)

    def test_run_is_checked_and_called_once(self):
        with mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, mock.patch.object(build_project.os.path, "exists", return_value=False):
            build_project.build_executable()
        run.assert_called_once()
        self.assertTrue(run.call_args.kwargs["check"])

    def test_linux_build_has_no_icon(self):
        argv = self._captured_argv("linux", icon_exists=True)
        self.assertFalse(any(arg.startswith("--icon") for arg in argv))

    def test_windows_build_adds_icon_when_present(self):
        argv = self._captured_argv("win32", icon_exists=True)
        self.assertIn(f"--icon={build_project.ICON_FILE}", argv)

    def test_windows_build_omits_icon_when_absent(self):
        argv = self._captured_argv("win32", icon_exists=False)
        self.assertFalse(any(arg.startswith("--icon") for arg in argv))


class TestWebguiBuildCommand(unittest.TestCase):
    """The webgui target builds a separate, Streamlit-bundling artifact."""

    def _argv(self, platform: str = "linux", icon_exists: bool = False) -> list[str]:
        with mock.patch.object(
            build_project.sys, "platform", platform
        ), mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, mock.patch.object(
            build_project.os.path, "exists", return_value=icon_exists
        ):
            build_project.build_executable("webgui")
        return run.call_args.args[0]

    def test_names_the_webgui_entry_point_and_binary(self):
        argv = self._argv()
        self.assertEqual(argv[argv.index("--name") + 1], build_project.WEBGUI_APP_NAME)
        self.assertEqual(argv[-1], build_project.WEBGUI_MAIN_SCRIPT)
        self.assertIn("--onefile", argv)

    def test_keeps_the_monitor_runner_hidden_import(self):
        self.assertIn("--hidden-import=app.monitor.run_monitor", self._argv())

    def test_collects_streamlit_without_a_pyinstaller_hook(self):
        argv = self._argv()
        self.assertIn("--collect-all=streamlit", argv)
        # streamlit/version.py calls importlib.metadata.version("streamlit").
        self.assertIn("--copy-metadata=streamlit", argv)

    def test_collects_application_submodules_imported_only_by_pages(self):
        self.assertIn("--collect-submodules=app", self._argv())

    def test_ships_the_pages_and_read_only_resources_as_data(self):
        argv = self._argv()
        separator = os.pathsep
        for source, destination in (
            ("app/webgui/*.py", "app/webgui"),
            ("app/webgui/pages/*.py", "app/webgui/pages"),
            ("README.md", "."),
            ("app_icon_512.png", "."),
        ):
            with self.subTest(source=source):
                self.assertIn(
                    f"--add-data={source}{separator}{destination}", argv
                )

    def test_windows_webgui_build_still_adds_the_icon(self):
        argv = self._argv("win32", icon_exists=True)
        self.assertIn(f"--icon={build_project.ICON_FILE}", argv)

    def test_cli_build_does_not_include_the_webgui_options(self):
        with mock.patch.object(
            build_project.sys, "platform", "linux"
        ), mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, mock.patch.object(
            build_project.os.path, "exists", return_value=False
        ):
            build_project.build_executable()
        argv = run.call_args.args[0]
        self.assertFalse(any("streamlit" in arg for arg in argv))
        self.assertFalse(any(arg.startswith("--add-data=") for arg in argv))


class TestBuildTargets(unittest.TestCase):
    def test_target_table_maps_cli_and_webgui(self):
        self.assertEqual(
            build_project.TARGETS["cli"],
            (build_project.MAIN_SCRIPT, build_project.APP_NAME),
        )
        self.assertEqual(
            build_project.TARGETS["webgui"],
            (build_project.WEBGUI_MAIN_SCRIPT, build_project.WEBGUI_APP_NAME),
        )

    def test_data_spec_uses_the_platform_separator(self):
        self.assertEqual(
            build_project._data_spec("src", "dest"),
            f"src{os.pathsep}dest",
        )


class TestBuildFailure(unittest.TestCase):
    def test_called_process_error_is_reported_not_raised(self):
        error = subprocess.CalledProcessError(1, ["PyInstaller"])
        with mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run", side_effect=error
        ), mock.patch.object(build_project.os.path, "exists", return_value=False):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                build_project.build_executable()
        self.assertIn("ERROR: PyInstaller build failed.", output.getvalue())


class TestCleanPreviousBuilds(unittest.TestCase):
    def test_removes_existing_build_and_dist_directories(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                for folder in (build_project.DIST_DIR, "build"):
                    os.makedirs(folder)
                    with open(os.path.join(folder, "artifact"), "w", encoding="utf-8") as fh:
                        fh.write("x")
                build_project.clean_previous_builds()
                self.assertFalse(os.path.exists(build_project.DIST_DIR))
                self.assertFalse(os.path.exists("build"))
            finally:
                os.chdir(cwd)

    def test_is_a_no_op_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                # Must not raise when build/ and dist/ are absent.
                build_project.clean_previous_builds()
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
