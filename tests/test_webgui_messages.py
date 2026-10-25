"""Unit tests for the web GUI status messages."""

import unittest

from app.webgui.messages import start_result_message


class TestStartResultMessage(unittest.TestCase):
    def test_settled_start_is_a_success(self):
        kind, message = start_result_message("Alpha", 3, alive=True, settled=True)
        self.assertEqual(kind, "success")
        self.assertIn("started.", message)

    def test_slow_start_is_a_warning_naming_the_refresh_button(self):
        # A frozen child can take ~10 s to unpack and report in, which used to
        # look like a settled start showing a stale 'stopped' status.
        kind, message = start_result_message("Alpha", 3, alive=True, settled=False)
        self.assertEqual(kind, "warning")
        self.assertIn("still starting", message)
        self.assertIn("↻ Refresh", message)

    def test_dead_child_is_an_error_naming_the_log(self):
        kind, message = start_result_message("Alpha", 3, alive=False, settled=False)
        self.assertEqual(kind, "error")
        self.assertIn("exited during startup", message)
        self.assertIn("logs/monitor_3.log", message)

    def test_a_dead_child_wins_over_a_settled_status(self):
        kind, _ = start_result_message("Alpha", 3, alive=False, settled=True)
        self.assertEqual(kind, "error")


if __name__ == "__main__":
    unittest.main()
