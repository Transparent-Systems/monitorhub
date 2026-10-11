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
    def _captured_argv(self, platform: str, icon_exists: bool = False) -> list[str]:
        """Run build_executable with side effects mocked; return the argv used."""
        with mock.patch.object(build_project.sys, "platform", platform), mock.patch.object(
            build_project, "clean_previous_builds"
        ), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, mock.patch.object(
            build_project.os.path, "exists", return_value=icon_exists
        ):
            build_project.build_executable()
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
