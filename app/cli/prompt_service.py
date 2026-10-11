"""Thin abstraction over print() and input() for testability.

Inject a PromptService instance into command classes so unit tests can
supply mock I/O (stub print() calls and programmatic input() responses)
without monkey-patching builtins.

The ``prompt_required`` / ``prompt_choice`` / ``prompt_yes_no`` helpers build
on the raw ``input``/``print`` methods, so subclasses (such as the scripted
test double in ``tests/mock_prompt_service.py``) inherit the same retry and
validation behaviour by overriding only the raw I/O methods.
"""

from collections.abc import Callable


class PromptService:
    """Wraps built-in print() and input() behind a replaceable interface."""

    def print(self, *args, **kwargs) -> None:
        """Forward to built-in print()."""
        print(*args, **kwargs)

    def input(self, prompt: str = "") -> str:
        """Forward to built-in input()."""
        return input(prompt)

    # ------------------------------------------------------------------
    # Interactive prompt helpers
    # ------------------------------------------------------------------

    def prompt_required(
        self,
        prompt: str,
        *,
        current: str | None = None,
        default: str | None = None,
        allow_cancel: bool = False,
        empty_message: str | None = None,
        validator: Callable[[str], str | None] | None = None,
        render: Callable[[], None] | None = None,
        echo_label: str | None = None,
        echo_on_empty: bool = False,
    ) -> str | None:
        """Ask repeatedly until a non-empty, valid value is entered.

        Empty-input handling, in priority order:

        * return ``current`` when it is not None (press-Enter-to-keep);
        * else return ``default`` when it is not None;
        * else return ``None`` when ``allow_cancel`` is True;
        * else print ``empty_message`` (when given) and ask again.

        ``validator`` returns an error message to print before asking again, or
        ``None`` when the entered value is acceptable. ``render`` is called at
        the top of every iteration to (re)draw the current value, list, or
        instructions. When ``echo_label`` is set,
        ``You entered {echo_label}: {value}`` is printed; it is only echoed for
        an empty entry when ``echo_on_empty`` is True.

        Returns the stripped accepted value, or ``None`` when cancelled.
        """
        while True:
            if render is not None:
                render()

            value = self.input(prompt).strip()

            if value == "":
                if echo_label is not None and echo_on_empty:
                    self.print(f"You entered {echo_label}: {value}")
                if current is not None:
                    return current
                if default is not None:
                    return default
                if allow_cancel:
                    return None
                if empty_message is not None:
                    self.print(empty_message)
                continue

            if echo_label is not None:
                self.print(f"You entered {echo_label}: {value}")

            if validator is not None:
                error = validator(value)
                if error is not None:
                    self.print(error)
                    continue

            return value

    def prompt_choice(
        self,
        prompt: str,
        *,
        valid: Callable[[str], str | None],
        render: Callable[[], None] | None = None,
        allow_all: bool = False,
        allow_cancel: bool = False,
        empty_message: str | None = None,
        echo_label: str | None = None,
    ) -> str | None:
        """Ask until ``valid`` accepts a selection, returning the raw value.

        An empty entry returns ``None`` when ``allow_cancel`` is set, otherwise
        ``empty_message`` is printed (when given) and the question repeated.
        When ``allow_all`` is set, ``"0"`` is accepted without consulting
        ``valid`` so callers can map it to "select all". ``render`` redraws the
        selectable list on each iteration.
        """

        def validator(value: str) -> str | None:
            if allow_all and value == "0":
                return None
            return valid(value)

        return self.prompt_required(
            prompt,
            allow_cancel=allow_cancel,
            empty_message=empty_message,
            validator=validator,
            render=render,
            echo_label=echo_label,
        )

    def prompt_yes_no(
        self,
        prompt: str,
        *,
        default: bool | None = None,
        render: Callable[[], None] | None = None,
        error_message: str = "Please answer y or n.",
    ) -> bool:
        """Ask until the user answers yes or no.

        ``y``/``yes`` (case-insensitive) returns True and ``n``/``no`` returns
        False. An empty answer returns ``default`` when it is not None,
        otherwise ``error_message`` is printed and the question repeated.
        """
        while True:
            if render is not None:
                render()

            answer = self.input(prompt).strip().lower()

            if answer == "":
                if default is not None:
                    return default
                self.print(error_message)
                continue
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False

            self.print(error_message)