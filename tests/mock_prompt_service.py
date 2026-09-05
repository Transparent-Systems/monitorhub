"""Scripted PromptService for unit tests.

Implements the same interface as :class:`scripts.prompt_service.PromptService`
but supplies ``input()`` responses from a queue and records ``print()`` output,
so tests can drive interactive command flows and assert on the output without a
human or monkey-patching builtins.
"""

from app.cli.prompt_service import PromptService


class MockPromptService(PromptService):
    """A PromptService that replays scripted inputs and captures output."""

    def __init__(self, inputs: list[str] | None = None) -> None:
        super().__init__()
        self._inputs: list[str] = list(inputs or [])
        self.outputs: list[str] = []

    def input(self, prompt: str = "") -> str:
        """Return the next scripted response, failing loudly if exhausted."""
        if not self._inputs:
            raise RuntimeError(
                f"MockPromptService ran out of scripted input (prompt: {prompt!r})."
            )
        return self._inputs.pop(0)

    def print(self, *args, **kwargs) -> None:
        """Record output as a single joined string per call."""
        self.outputs.append(" ".join(str(arg) for arg in args))

    @property
    def output_text(self) -> str:
        """Return the full captured output as a newline-joined string."""
        return "\n".join(self.outputs)
