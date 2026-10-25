"""Unit tests for the GUI binary entry point (``mhub_gui.py``).

The binary serves three roles: the Streamlit web GUI (the default), the full
CLI, and a monitor child when re-executed with ``run-monitor``.
"""

import contextlib
import io
import unittest
from unittest import mock

import mhub
import mhub_gui


class TestMonitorChild(unittest.TestCase):
    def test_run_monitor_is_dispatched_to_the_monitor_runner(self):
        with mock.patch(
            "app.monitor.run_monitor.run_monitor_main", return_value=0
        ) as runner:
            code = mhub_gui.main(["run-monitor", "--monitor-id", "7"])
        self.assertEqual(code, 0)
        runner.assert_called_once_with(["--monitor-id", "7"])

    def test_run_monitor_never_reaches_the_cli_or_the_launcher(self):
        with mock.patch(
            "app.monitor.run_monitor.run_monitor_main", return_value=0
        ), mock.patch("app.webgui.launcher.main") as launcher, mock.patch(
            "mhub.main"
        ) as cli:
            mhub_gui.main(["run-monitor", "--monitor-id", "7"])
        launcher.assert_not_called()
        cli.assert_not_called()


class TestGuiLaunch(unittest.TestCase):
    def _launch(self, argv):
        with mock.patch("app.webgui.launcher.main", return_value=0) as launcher:
            code = mhub_gui.main(argv)
        return code, launcher

    def test_no_arguments_starts_the_gui(self):
        code, launcher = self._launch([])
        self.assertEqual(code, 0)
        launcher.assert_called_once_with([], db_dir=None)

    def test_db_dir_is_passed_to_the_launcher(self):
        _, launcher = self._launch(["-d", "/tmp/mhub-db"])
        launcher.assert_called_once_with([], db_dir="/tmp/mhub-db")

    def test_long_form_db_dir(self):
        _, launcher = self._launch(["--db-dir=/tmp/mhub-db"])
        launcher.assert_called_once_with([], db_dir="/tmp/mhub-db")

    def test_streamlit_flags_are_forwarded(self):
        _, launcher = self._launch(["--server.port=8600"])
        launcher.assert_called_once_with(["--server.port=8600"], db_dir=None)

    def test_db_dir_and_streamlit_flags_together(self):
        _, launcher = self._launch(["-d", "/tmp/db", "--server.port=8600"])
        launcher.assert_called_once_with(["--server.port=8600"], db_dir="/tmp/db")

    def test_unrecognised_positional_starts_the_gui(self):
        # e.g. a value left over from a space-separated Streamlit flag.
        _, launcher = self._launch(["8600"])
        launcher.assert_called_once_with(["8600"], db_dir=None)

    def test_defaults_to_sys_argv(self):
        with mock.patch(
            "app.webgui.launcher.main", return_value=0
        ) as launcher, mock.patch("sys.argv", ["mhub-gui", "--server.port=8600"]):
            mhub_gui.main()
        launcher.assert_called_once_with(["--server.port=8600"], db_dir=None)

    def test_cli_only_options_point_at_the_cli(self):
        for argv in (["-l", "/tmp/log.yaml"], ["--log-level", "DEBUG"]):
            with self.subTest(argv=argv):
                output = io.StringIO()
                with contextlib.redirect_stderr(output):
                    code = mhub_gui.main(argv)
                self.assertEqual(code, 2)
                self.assertIn("only CLI commands accept", output.getvalue())
                self.assertIn(argv[0], output.getvalue())


class TestCliDelegation(unittest.TestCase):
    def test_every_cli_command_is_delegated_to_mhub_main(self):
        for command in sorted(mhub_gui.CLI_COMMANDS):
            with self.subTest(command=command), mock.patch(
                "mhub.main", return_value=0
            ) as cli:
                code = mhub_gui.main([command])
                cli.assert_called_once_with([command])
                self.assertEqual(code, 0)

    def test_global_options_before_the_command_are_kept(self):
        with mock.patch("mhub.main", return_value=0) as cli:
            mhub_gui.main(["-d", "/tmp/db", "monitor", "show"])
        cli.assert_called_once_with(["-d", "/tmp/db", "monitor", "show"])

    def test_option_values_are_not_mistaken_for_commands(self):
        # '-l' consumes its value, so 'monitor' is still the command.
        with mock.patch("mhub.main", return_value=0) as cli:
            mhub_gui.main(["-l", "/tmp/log.yaml", "monitor", "show"])
        cli.assert_called_once_with(["-l", "/tmp/log.yaml", "monitor", "show"])

    def test_help_prints_the_cli_help_plus_a_gui_note(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = mhub_gui.main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("webgui", output.getvalue())
        self.assertIn("127.0.0.1:8501", output.getvalue())


class TestDeclaredSurfaceMatchesTheParser(unittest.TestCase):
    """The entry point must not drift from the CLI it delegates to."""

    def test_every_declared_command_exists_in_the_parser(self):
        parser, _ = mhub.build_parser()
        for command in sorted(mhub_gui.CLI_COMMANDS):
            with self.subTest(command=command):
                self.assertEqual(parser.parse_args([command]).command, command)

    def test_value_options_cover_every_cli_option_that_takes_a_value(self):
        parser, _ = mhub.build_parser()
        # _actions is stdlib-internal but stable, and the alternative (parsing
        # the help text) would be far more brittle.
        takes_value = {
            option
            for action in parser._actions
            if action.option_strings and action.nargs != 0
            for option in action.option_strings
        }
        self.assertEqual(
            takes_value,
            set(mhub_gui.VALUE_OPTIONS),
            "mhub_gui.VALUE_OPTIONS is out of sync with the CLI parser",
        )


if __name__ == "__main__":
    unittest.main()
