"""Unit tests for :mod:`build_project`.

``build_project`` is a standalone script, so these tests import it directly and
verify the PyInstaller command it assembles: invoking PyInstaller through the
running interpreter (``sys.executable -m PyInstaller``) instead of a bare,
PATH-dependent ``pyinstaller``. Subprocess execution and filesystem cleanup are
mocked so nothing is actually built or deleted.
"""

import ast
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_project

REPO_ROOT = Path(__file__).resolve().parents[1]


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

    def test_cli_build_excludes_streamlit(self):
        # The CLI artifact must stay ~30 MB, not grow to ~120 MB by bundling the
        # Streamlit stack.
        self.assertIn("--exclude-module=streamlit", self._captured_argv("linux"))


class TestCliBinaryStaysSmall(unittest.TestCase):
    """mhub.py must reach the GUI launcher dynamically, not statically.

    A static import of app.webgui.launcher makes PyInstaller follow it into
    Streamlit and bundle the whole stack into the CLI binary.
    """

    def test_mhub_does_not_statically_import_the_gui_launcher(self):
        source = (REPO_ROOT / "mhub.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
                self.assertNotIn("app.webgui.launcher", names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotEqual(node.module, "app.webgui.launcher")
                self.assertFalse(node.module.startswith("app.webgui"))


class TestGuiBuildCommand(unittest.TestCase):
    """The gui target builds a separate, Streamlit-bundling artifact."""

    def _argv(self, platform: str = "linux", icon_exists: bool = False) -> list[str]:
        with mock.patch.object(
            build_project.sys, "platform", platform
        ), mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, mock.patch.object(
            build_project.os.path, "exists", return_value=icon_exists
        ):
            build_project.build_executable("gui")
        return run.call_args.args[0]

    def test_names_the_gui_entry_point_and_binary(self):
        argv = self._argv()
        self.assertEqual(argv[argv.index("--name") + 1], build_project.GUI_APP_NAME)
        self.assertEqual(argv[-1], build_project.GUI_MAIN_SCRIPT)
        self.assertIn("--onefile", argv)

    def test_the_webgui_spelling_is_still_accepted(self):
        with mock.patch.object(
            build_project.sys, "platform", "linux"
        ), mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, mock.patch.object(
            build_project.os.path, "exists", return_value=False
        ):
            build_project.build_executable("webgui")
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("--name") + 1], build_project.GUI_APP_NAME)

    def test_keeps_the_monitor_runner_hidden_import(self):
        self.assertIn("--hidden-import=app.monitor.run_monitor", self._argv())

    def test_collects_streamlit_without_a_pyinstaller_hook(self):
        argv = self._argv()
        self.assertIn("--collect-all=streamlit", argv)
        # streamlit/version.py calls importlib.metadata.version("streamlit").
        self.assertIn("--copy-metadata=streamlit", argv)

    def test_collects_application_submodules_imported_only_by_pages(self):
        self.assertIn("--collect-submodules=app", self._argv())

    def test_excludes_the_test_support_code(self):
        # The GUI never runs a test suite, so the pytest/pygments stack
        # (~430 modules) must not be bundled.
        argv = self._argv()
        for module in (
            "streamlit.testing",
            "pytest",
            "pygments",
            "pyarrow.conftest",
        ):
            with self.subTest(module=module):
                self.assertIn(f"--exclude-module={module}", argv)

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

    def test_windows_gui_build_still_adds_the_icon(self):
        argv = self._argv("win32", icon_exists=True)
        self.assertIn(f"--icon={build_project.ICON_FILE}", argv)

    def test_cli_build_does_not_include_the_gui_options(self):
        with mock.patch.object(
            build_project.sys, "platform", "linux"
        ), mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, mock.patch.object(
            build_project.os.path, "exists", return_value=False
        ):
            build_project.build_executable()
        argv = run.call_args.args[0]
        # None of the GUI bundling options may leak into the CLI build.
        for prefix in (
            "--collect-all=",
            "--collect-submodules=",
            "--copy-metadata=",
            "--add-data=",
        ):
            with self.subTest(prefix=prefix):
                self.assertFalse(any(arg.startswith(prefix) for arg in argv))


class TestBuildTargets(unittest.TestCase):
    def test_target_table_maps_cli_and_gui(self):
        self.assertEqual(
            build_project.TARGETS["cli"],
            (build_project.MAIN_SCRIPT, build_project.APP_NAME),
        )
        self.assertEqual(
            build_project.TARGETS["gui"],
            (build_project.GUI_MAIN_SCRIPT, build_project.GUI_APP_NAME),
        )

    def test_webgui_is_an_alias_for_gui(self):
        self.assertEqual(build_project.resolve_target("webgui"), "gui")
        self.assertEqual(build_project.resolve_target("gui"), "gui")
        self.assertEqual(build_project.resolve_target("cli"), "cli")

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
                code = build_project.build_executable()
        self.assertIn("ERROR: PyInstaller build failed.", output.getvalue())
        # A failed build must fail the caller: CI used to carry on regardless.
        self.assertEqual(code, 1)


class TestCleanPreviousBuilds(unittest.TestCase):
    """Cleaning is target-scoped: building one target keeps the other's binary."""

    @staticmethod
    def _output_name(target: str) -> str:
        name = build_project.TARGETS[target][1]
        return f"{name}.exe" if sys.platform == "win32" else name

    def _make_layout(self) -> None:
        """Create the CLI and GUI build outputs plus a test database."""
        for target in ("cli", "gui"):
            os.makedirs(os.path.join("build", build_project.TARGETS[target][1]))
            os.makedirs(build_project.DIST_DIR, exist_ok=True)
            with open(
                os.path.join(build_project.DIST_DIR, self._output_name(target)),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("x")
        os.makedirs(os.path.join(build_project.DIST_DIR, "data"))
        with open(
            os.path.join(build_project.DIST_DIR, "data", "monitorhub.db"),
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write("x")

    def test_removes_only_the_targets_own_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                self._make_layout()
                build_project.clean_previous_builds("gui")

                # The GUI's own outputs are gone...
                self.assertFalse(
                    os.path.exists(os.path.join("build", build_project.TARGETS["gui"][1]))
                )
                self.assertFalse(
                    os.path.exists(
                        os.path.join(build_project.DIST_DIR, self._output_name("gui"))
                    )
                )
                # ...while the CLI binary and the runtime data survive.
                self.assertTrue(
                    os.path.exists(os.path.join("build", build_project.TARGETS["cli"][1]))
                )
                self.assertTrue(
                    os.path.exists(
                        os.path.join(build_project.DIST_DIR, self._output_name("cli"))
                    )
                )
                self.assertTrue(
                    os.path.exists(
                        os.path.join(build_project.DIST_DIR, "data", "monitorhub.db")
                    )
                )
            finally:
                os.chdir(cwd)

    def test_removes_a_previous_onedir_folder(self):
        # An onedir build writes dist/<name>/ instead of dist/<name>.
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                os.makedirs(
                    os.path.join(
                        build_project.DIST_DIR, build_project.GUI_APP_NAME, "_internal"
                    )
                )
                build_project.clean_previous_builds("gui")
                self.assertFalse(
                    os.path.exists(
                        os.path.join(build_project.DIST_DIR, build_project.GUI_APP_NAME)
                    )
                )
            finally:
                os.chdir(cwd)

    def test_defaults_to_the_cli_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                self._make_layout()
                build_project.clean_previous_builds()
                self.assertFalse(
                    os.path.exists(
                        os.path.join(build_project.DIST_DIR, self._output_name("cli"))
                    )
                )
                self.assertTrue(
                    os.path.exists(
                        os.path.join(build_project.DIST_DIR, self._output_name("gui"))
                    )
                )
            finally:
                os.chdir(cwd)

    def test_is_a_no_op_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                # Must not raise when build/ and dist/ are absent.
                build_project.clean_previous_builds()
                build_project.clean_previous_builds("gui")
            finally:
                os.chdir(cwd)


class TestPreflight(unittest.TestCase):
    """Fail early and explain, instead of a cryptic PyInstaller error."""

    def test_no_problem_when_pyinstaller_is_installed(self):
        self.assertIsNone(build_project.pyinstaller_problem())

    def test_missing_pyinstaller_names_the_interpreter_and_the_fix(self):
        with mock.patch.object(
            build_project.importlib.util, "find_spec", return_value=None
        ):
            problem = build_project.pyinstaller_problem()
        self.assertIn(sys.executable, problem)
        self.assertIn("pip install -r requirements.txt", problem)

    def test_build_aborts_before_invoking_pyinstaller(self):
        output = io.StringIO()
        with mock.patch.object(
            build_project, "pyinstaller_problem", return_value="no PyInstaller"
        ), mock.patch.object(build_project, "clean_previous_builds") as clean, mock.patch.object(
            build_project.subprocess, "run"
        ) as run, contextlib.redirect_stderr(output):
            code = build_project.build_executable("cli")
        self.assertEqual(code, 2)
        run.assert_not_called()
        clean.assert_not_called()
        self.assertIn("ERROR: no PyInstaller", output.getvalue())

    def test_missing_inputs_abort_the_build(self):
        output = io.StringIO()
        with mock.patch.object(
            build_project, "missing_inputs", return_value=["README.md"]
        ), mock.patch.object(build_project, "clean_previous_builds") as clean, mock.patch.object(
            build_project.subprocess, "run"
        ) as run, contextlib.redirect_stderr(output):
            code = build_project.build_executable("gui")
        self.assertEqual(code, 2)
        run.assert_not_called()
        clean.assert_not_called()
        self.assertIn("README.md", output.getvalue())

    def test_missing_inputs_for_the_gui_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                missing = build_project.missing_inputs("gui", "mhub_gui.py")
            finally:
                os.chdir(cwd)
        for expected in (
            "mhub_gui.py",
            "README.md",
            "app_icon_512.png",
            "app/webgui/*.py",
            "app/webgui/pages/*.py",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, missing)

    def test_a_complete_checkout_has_every_input(self):
        cwd = os.getcwd()
        os.chdir(REPO_ROOT)
        try:
            self.assertEqual(build_project.missing_inputs("cli", "mhub.py"), [])
            self.assertEqual(build_project.missing_inputs("gui", "mhub_gui.py"), [])
        finally:
            os.chdir(cwd)

    def test_banner_names_the_interpreter(self):
        output = io.StringIO()
        with mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ), contextlib.redirect_stdout(output):
            build_project.build_executable("cli")
        self.assertIn(sys.executable, output.getvalue())


class TestLayout(unittest.TestCase):
    """``--layout`` selects the PyInstaller bundle layout."""

    @staticmethod
    def _exe(name: str) -> str:
        return f"{name}.exe" if sys.platform == "win32" else name

    def _argv(self, target: str, layout: str) -> list[str]:
        with mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, contextlib.redirect_stdout(io.StringIO()):
            code = build_project.build_executable(target, layout)
        self.assertEqual(code, 0)
        return run.call_args.args[0]

    def test_onefile_is_the_default(self):
        argv = self._argv("gui", build_project.DEFAULT_LAYOUT)
        self.assertIn("--onefile", argv)
        self.assertNotIn("--onedir", argv)

    def test_onedir_builds_a_folder(self):
        argv = self._argv("gui", "onedir")
        self.assertIn("--onedir", argv)
        self.assertNotIn("--onefile", argv)

    def test_all_honours_the_layout(self):
        with mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run"
        ) as run, contextlib.redirect_stdout(io.StringIO()):
            build_project.build_executable("all", "onedir")
        self.assertEqual(len(run.call_args_list), 2)
        for call in run.call_args_list:
            self.assertIn("--onedir", call.args[0])

    def test_output_path_onefile(self):
        self.assertEqual(
            build_project.output_path("cli"),
            os.path.join(build_project.DIST_DIR, self._exe(build_project.APP_NAME)),
        )

    def test_output_path_onedir(self):
        self.assertEqual(
            build_project.output_path("gui", "onedir"),
            os.path.join(
                build_project.DIST_DIR,
                build_project.GUI_APP_NAME,
                self._exe(build_project.GUI_APP_NAME),
            ),
        )

    def test_parse_args_defaults(self):
        self.assertEqual(build_project.parse_args([]), ("cli", "onefile"))
        self.assertEqual(build_project.parse_args(["gui"]), ("gui", "onefile"))

    def test_parse_args_accepts_both_layout_forms(self):
        self.assertEqual(
            build_project.parse_args(["gui", "--layout", "onedir"]), ("gui", "onedir")
        )
        self.assertEqual(
            build_project.parse_args(["--layout=onedir", "all"]), ("all", "onedir")
        )

    def test_parse_args_rejects_bad_input(self):
        for argv in (["gui", "--layout"], ["gui", "--layout", "nope"], ["gui", "cli"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                build_project.parse_args(argv)

    def test_main_passes_the_layout_through(self):
        with mock.patch.object(
            build_project, "build_executable", return_value=0
        ) as build:
            code = build_project.main(["gui", "--layout", "onedir"])
        self.assertEqual(code, 0)
        build.assert_called_once_with("gui", "onedir")

    def test_main_rejects_an_unknown_layout(self):
        output = io.StringIO()
        with mock.patch.object(
            build_project, "build_executable"
        ) as build, contextlib.redirect_stdout(output):
            code = build_project.main(["gui", "--layout", "nope"])
        self.assertEqual(code, 2)
        build.assert_not_called()
        self.assertIn("unknown layout", output.getvalue())


class TestAllTarget(unittest.TestCase):
    def _run_all(self, side_effect=None):
        with mock.patch.object(build_project, "clean_previous_builds"), mock.patch.object(
            build_project.subprocess, "run", side_effect=side_effect
        ) as run, contextlib.redirect_stdout(io.StringIO()):
            code = build_project.build_executable("all")
        return code, [call.args[0] for call in run.call_args_list]

    def test_builds_the_cli_then_the_gui(self):
        code, argvs = self._run_all()
        self.assertEqual(code, 0)
        self.assertEqual(len(argvs), 2)
        self.assertEqual(
            [argv[argv.index("--name") + 1] for argv in argvs],
            [build_project.APP_NAME, build_project.GUI_APP_NAME],
        )
        self.assertEqual(argvs[0][-1], build_project.MAIN_SCRIPT)
        self.assertEqual(argvs[1][-1], build_project.GUI_MAIN_SCRIPT)

    def test_failure_of_either_build_is_reported(self):
        error = subprocess.CalledProcessError(1, ["PyInstaller"])
        code, _ = self._run_all(side_effect=[None, error])
        self.assertEqual(code, 1)


class TestMainEntryPoint(unittest.TestCase):
    def _main(self, argv):
        output = io.StringIO()
        with mock.patch.object(
            build_project, "build_executable", return_value=0
        ) as build, contextlib.redirect_stdout(output):
            code = build_project.main(argv)
        return code, build, output.getvalue()

    def test_defaults_to_the_cli_and_says_so(self):
        code, build, output = self._main([])
        self.assertEqual(code, 0)
        build.assert_called_once_with("cli", "onefile")
        self.assertIn("building the CLI only", output)
        self.assertIn("build_project.py gui", output)
        self.assertIn("build_project.py all", output)

    def test_an_explicit_target_is_not_nudged(self):
        _, build, output = self._main(["cli"])
        build.assert_called_once_with("cli", "onefile")
        self.assertNotIn("building the CLI only", output)

    def test_every_choice_is_accepted(self):
        for target in build_project.TARGET_CHOICES:
            with self.subTest(target=target):
                _, build, _ = self._main([target])
                build.assert_called_once_with(target, "onefile")

    def test_webgui_is_still_an_alias(self):
        _, build, _ = self._main(["webgui"])
        build.assert_called_once_with("gui", "onefile")

    def test_unknown_target_is_rejected(self):
        code, build, output = self._main(["nope"])
        self.assertEqual(code, 2)
        build.assert_not_called()
        self.assertIn("Unknown target 'nope'", output)
        self.assertIn("cli, gui, all", output)

    def test_help_is_available(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                code, build, output = self._main([flag])
                self.assertEqual(code, 0)
                build.assert_not_called()
                self.assertIn("Targets:", output)
                self.assertIn("python build_project.py all", output)

    def test_defaults_to_sys_argv(self):
        with mock.patch.object(
            build_project, "build_executable", return_value=0
        ) as build, mock.patch.object(sys, "argv", ["build_project.py", "gui"]):
            build_project.main()
        build.assert_called_once_with("gui", "onefile")


if __name__ == "__main__":
    unittest.main()
