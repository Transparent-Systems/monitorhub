"""Unit tests for the PromptService interactive prompt helpers.

These exercise ``prompt_required`` / ``prompt_choice`` / ``prompt_yes_no``
directly through the scripted :class:`MockPromptService`, verifying the retry,
validation, keep-current, cancel and echo behaviour independently of the
command flows in ``tests/test_commands.py``.
"""

import unittest

from tests.mock_prompt_service import MockPromptService


class TestPromptRequired(unittest.TestCase):
    def test_returns_accepted_value_stripped(self):
        prompt = MockPromptService(["  hello  "])
        self.assertEqual(prompt.prompt_required("Name: "), "hello")

    def test_retries_until_validator_accepts(self):
        prompt = MockPromptService(["bad", "good"])

        def validator(value: str) -> str | None:
            return None if value == "good" else f"Invalid: {value}"

        self.assertEqual(prompt.prompt_required("Name: ", validator=validator), "good")
        self.assertIn("Invalid: bad", prompt.output_text)

    def test_returns_current_on_empty(self):
        prompt = MockPromptService([""])
        self.assertEqual(prompt.prompt_required("Name: ", current="old"), "old")
        self.assertNotIn("Please try again", prompt.output_text)

    def test_returns_default_on_empty(self):
        prompt = MockPromptService([""])
        self.assertEqual(prompt.prompt_required("Name: ", default="fallback"), "fallback")

    def test_cancels_on_empty(self):
        prompt = MockPromptService([""])
        self.assertIsNone(prompt.prompt_required("Name: ", allow_cancel=True))

    def test_empty_message_retries_then_accepts(self):
        prompt = MockPromptService(["", "value"])
        result = prompt.prompt_required("Name: ", empty_message="Cannot be empty")
        self.assertEqual(result, "value")
        self.assertIn("Cannot be empty", prompt.output_text)

    def test_render_is_called_each_iteration(self):
        prompt = MockPromptService(["bad", "good"])
        calls = {"n": 0}

        def render() -> None:
            calls["n"] += 1

        prompt.prompt_required(
            "Name: ",
            validator=lambda value: None if value == "good" else "retry",
            render=render,
        )
        self.assertEqual(calls["n"], 2)

    def test_echo_label_printed_for_non_empty(self):
        prompt = MockPromptService(["value"])
        prompt.prompt_required("Name: ", echo_label="name")
        self.assertIn("You entered name: value", prompt.output_text)

    def test_echo_label_suppressed_for_empty_by_default(self):
        prompt = MockPromptService([""])
        prompt.prompt_required("Name: ", allow_cancel=True, echo_label="name")
        self.assertNotIn("You entered name:", prompt.output_text)

    def test_echo_on_empty_prints_echo(self):
        prompt = MockPromptService(["", "x"])
        prompt.prompt_required(
            "Name: ",
            empty_message="empty",
            echo_label="name",
            echo_on_empty=True,
        )
        self.assertIn("You entered name:", prompt.output_text)


class TestPromptChoice(unittest.TestCase):
    def test_returns_valid_choice(self):
        prompt = MockPromptService(["3"])
        result = prompt.prompt_choice("Pick: ", valid=lambda value: None)
        self.assertEqual(result, "3")

    def test_invalid_then_valid(self):
        prompt = MockPromptService(["x", "2"])

        def valid(value: str) -> str | None:
            return None if value.isdigit() else f"Bad: {value}"

        self.assertEqual(prompt.prompt_choice("Pick: ", valid=valid), "2")
        self.assertIn("Bad: x", prompt.output_text)

    def test_allow_all_accepts_zero(self):
        prompt = MockPromptService(["0"])

        def valid(value: str) -> str | None:
            return "nope"  # Should not be consulted for "0" when allow_all.

        self.assertEqual(
            prompt.prompt_choice("Pick: ", valid=valid, allow_all=True), "0"
        )

    def test_empty_cancels(self):
        prompt = MockPromptService([""])
        self.assertIsNone(
            prompt.prompt_choice("Pick: ", valid=lambda value: None, allow_cancel=True)
        )

    def test_empty_message_retries_then_accepts(self):
        prompt = MockPromptService(["", "1"])
        result = prompt.prompt_choice(
            "Pick: ",
            valid=lambda value: None,
            empty_message="Spaces only",
        )
        self.assertEqual(result, "1")
        self.assertIn("Spaces only", prompt.output_text)


class TestPromptYesNo(unittest.TestCase):
    def test_yes_variants(self):
        for answer in ("y", "Y", "yes", "YES"):
            prompt = MockPromptService([answer])
            self.assertTrue(prompt.prompt_yes_no("Ok? "))

    def test_no_variants(self):
        for answer in ("n", "N", "no", "NO"):
            prompt = MockPromptService([answer])
            self.assertFalse(prompt.prompt_yes_no("Ok? "))

    def test_empty_uses_default_true(self):
        prompt = MockPromptService([""])
        self.assertTrue(prompt.prompt_yes_no("Ok? ", default=True))

    def test_empty_uses_default_false(self):
        prompt = MockPromptService([""])
        self.assertFalse(prompt.prompt_yes_no("Ok? ", default=False))

    def test_empty_without_default_reprompts(self):
        prompt = MockPromptService(["", "y"])
        self.assertTrue(prompt.prompt_yes_no("Ok? "))
        self.assertIn("Please answer y or n.", prompt.output_text)

    def test_invalid_then_valid(self):
        prompt = MockPromptService(["maybe", "n"])
        self.assertFalse(prompt.prompt_yes_no("Ok? "))
        self.assertIn("Please answer y or n.", prompt.output_text)


if __name__ == "__main__":
    unittest.main()
