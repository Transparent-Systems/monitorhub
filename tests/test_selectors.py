"""Unit tests for :mod:`app.cli.selectors` interactive list selectors.

Focused on :class:`ProfileImportSelector`, which lets the user import none
(press Enter), all (enter ``0``), or individual rclone profiles from a numbered
list until pressing Enter stops the selection.
"""

import unittest

from app.cli.selectors import ProfileImportSelector
from tests.mock_prompt_service import MockPromptService


class ProfileImportSelectorTest(unittest.TestCase):
    def _make(self, inputs):
        prompt = MockPromptService(inputs=inputs)
        selector = ProfileImportSelector(prompt=prompt)
        return selector, prompt

    def test_select_all_with_zero(self):
        selector, _ = self._make(["0"])

        selected = selector.select_interactive(["alpha", "beta"])

        self.assertEqual(selected, ["alpha", "beta"])

    def test_select_single_then_stop(self):
        selector, _ = self._make(["1", ""])

        selected = selector.select_interactive(["alpha", "beta"])

        self.assertEqual(selected, ["alpha"])

    def test_select_none(self):
        selector, _ = self._make([""])

        selected = selector.select_interactive(["alpha", "beta"])

        self.assertEqual(selected, [])

    def test_select_multiple_then_stop(self):
        selector, _ = self._make(["2", "1", ""])

        selected = selector.select_interactive(["alpha", "beta"])

        self.assertEqual(selected, ["beta", "alpha"])

    def test_invalid_entry_reprompts(self):
        selector, prompt = self._make(["x", "9", "1", ""])

        selected = selector.select_interactive(["alpha", "beta"])

        self.assertEqual(selected, ["alpha"])
        self.assertIn("Invalid profile number: x", prompt.output_text)
        self.assertIn("Invalid profile number: 9", prompt.output_text)

    def test_empty_list_returns_empty_without_prompting(self):
        selector, _ = self._make([])

        self.assertEqual(selector.select_interactive([]), [])

    def test_select_all_is_advertised(self):
        selector, prompt = self._make(["0"])

        selector.select_interactive(["alpha"])

        self.assertIn("0.  Select all profiles", prompt.output_text)


if __name__ == "__main__":
    unittest.main()
