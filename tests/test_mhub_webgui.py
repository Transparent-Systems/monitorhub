"""Unit tests for the frozen web GUI entry point (``mhub_webgui.py``).

The binary has two roles: launch the Streamlit GUI, or run a monitor child when
re-executed with ``run-monitor`` (see ``MonitorProcessManager.launch``).
"""

import unittest
from unittest import mock

import mhub_webgui


class TestMain(unittest.TestCase):
    def test_run_monitor_is_dispatched_to_the_monitor_runner(self):
        with mock.patch(
            "app.monitor.run_monitor.run_monitor_main", return_value=0
        ) as run_monitor, mock.patch("app.webgui.launcher.main") as launcher:
            code = mhub_webgui.main(["run-monitor", "--monitor-id", "7"])
        self.assertEqual(code, 0)
        run_monitor.assert_called_once_with(["--monitor-id", "7"])
        launcher.assert_not_called()

    def test_run_monitor_does_not_import_the_launcher(self):
        # Importing Streamlit for a monitor child would cost seconds per start.
        with mock.patch(
            "app.monitor.run_monitor.run_monitor_main", return_value=0
        ), mock.patch("app.webgui.launcher.main") as launcher:
            mhub_webgui.main(["run-monitor", "--monitor-id", "7"])
        launcher.assert_not_called()

    def test_no_arguments_launches_the_gui(self):
        with mock.patch("app.webgui.launcher.main", return_value=0) as launcher:
            code = mhub_webgui.main([])
        self.assertEqual(code, 0)
        launcher.assert_called_once_with([])

    def test_extra_arguments_are_forwarded_to_the_launcher(self):
        with mock.patch("app.webgui.launcher.main", return_value=0) as launcher:
            mhub_webgui.main(["--server.port=8600"])
        launcher.assert_called_once_with(["--server.port=8600"])

    def test_defaults_to_sys_argv(self):
        with mock.patch("app.webgui.launcher.main", return_value=0) as launcher, mock.patch(
            "sys.argv", ["mhub-webgui", "--server.port=8600"]
        ):
            mhub_webgui.main()
        launcher.assert_called_once_with(["--server.port=8600"])


if __name__ == "__main__":
    unittest.main()
