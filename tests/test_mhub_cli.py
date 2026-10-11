"""Wiring tests for the ``mhub.py`` entry point.

Importing ``mhub`` executes only its module-level definitions -- all CLI logic
lives under ``if __name__ == "__main__"`` -- so the dispatch table can be
inspected without running the CLI or touching the database.
"""

import unittest

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


if __name__ == "__main__":
    unittest.main()
