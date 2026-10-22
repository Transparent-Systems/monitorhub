"""Wiring tests for the ``mhub.py`` entry point.

Importing ``mhub`` executes only its module-level definitions -- all CLI logic
lives under ``if __name__ == "__main__"`` -- so the dispatch table can be
inspected without running the CLI or touching the database.
"""

import argparse
import unittest
from unittest import mock

import mhub


class TestSubcommandDispatch(unittest.TestCase):
    def test_config_python_is_dispatched_to_app_commands(self):
        owner, method, _ = mhub._SUBCOMMAND_DISPATCH[("config", "python")]
        self.assertEqual((owner, method), ("app", "config_python"))

    def test_config_test_is_still_dispatched(self):
        owner, method, _ = mhub._SUBCOMMAND_DISPATCH[("config", "test")]
        self.assertEqual((owner, method), ("app", "config_test"))

    def test_every_dispatch_entry_targets_a_known_owner(self):
        for (_, _), (owner, _, _) in mhub._SUBCOMMAND_DISPATCH.items():
            self.assertIn(owner, {"app", "profile", "monitor", "database"})


class TestBuildParser(unittest.TestCase):
    """``build_parser`` is shared with the mhub-gui entry point."""

    def test_returns_the_parser_and_its_command_parsers(self):
        parser, command_parsers = mhub.build_parser()
        self.assertIsInstance(parser, argparse.ArgumentParser)
        self.assertEqual(
            set(command_parsers), {"profile", "monitor", "database", "config"}
        )

    def test_parses_a_global_option_and_a_command(self):
        parser, _ = mhub.build_parser()
        args = parser.parse_args(["-d", "/tmp/db", "monitor", "show"])
        self.assertEqual(args.db_dir, "/tmp/db")
        self.assertEqual(args.command, "monitor")
        self.assertEqual(args.monitor_subcommand, "show")

    def test_webgui_is_a_command(self):
        parser, _ = mhub.build_parser()
        self.assertEqual(parser.parse_args(["webgui"]).command, "webgui")


class TestWebguiDispatch(unittest.TestCase):
    def test_db_dir_is_forwarded_to_the_launcher(self):
        with mock.patch("app.webgui.launcher.main", return_value=0) as launcher:
            code = mhub.main(["-d", "/tmp/db", "webgui"])
        self.assertEqual(code, 0)
        launcher.assert_called_once_with(db_dir="/tmp/db")

    def test_without_db_dir_the_launcher_resolves_it_itself(self):
        with mock.patch("app.webgui.launcher.main", return_value=0) as launcher:
            mhub.main(["webgui"])
        launcher.assert_called_once_with(db_dir=None)


if __name__ == "__main__":
    unittest.main()
