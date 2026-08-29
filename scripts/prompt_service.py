"""Thin abstraction over print() and input() for testability.

Inject a PromptService instance into command classes so unit tests can
supply mock I/O (stub print() calls and programmatic input() responses)
without monkey-patching builtins.
"""


class PromptService:
    """Wraps built-in print() and input() behind a replaceable interface."""

    def print(self, *args, **kwargs) -> None:
        """Forward to built-in print()."""
        print(*args, **kwargs)

    def input(self, prompt: str = "") -> str:
        """Forward to built-in input()."""
        return input(prompt)