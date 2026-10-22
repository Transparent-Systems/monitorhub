"""Mask secret profile values in output.

The profile commands print a profile's configuration so the user can inspect
and edit it.  Secret values (passwords, tokens, secret keys) must not end up in
terminal scrollback, screen shares or session logs, so every display path
renders them through :func:`masked_value` / :func:`format_value`.

This module only changes what is *printed*.  Editing is unaffected: a secret
the user types is never echoed (the secret prompts do not set an
``echo_label``), and pressing Enter keeps the stored value untouched.
"""

from typing import Any

# What a hidden secret looks like in the CLI.
MASK = "********"

# Keys treated as secrets, matched case-insensitively:
#   * exact common names;
#   * anything containing one of the markers (``client_secret``, ``token``,
#     ``passwd``, ``service_account_credentials``);
#   * anything ending in one of the suffixes (rclone option names such as
#     ``s3_sse_customer_key`` or ``key_pem``).
# Identifiers such as ``access_key_id`` and ``client_id`` are deliberately not
# masked: they are not secret and ``rclone config show`` displays them too.
_SECRET_EXACT = frozenset({"pass", "password"})
_SECRET_MARKERS = ("secret", "token", "passw", "credential")
_SECRET_SUFFIXES = ("_key", "_pem")


def is_secret_key(name: Any) -> bool:
    """Return True when a config key holds a secret value."""
    key = str(name).strip().lower()
    if not key:
        return False
    if key in _SECRET_EXACT:
        return True
    if any(marker in key for marker in _SECRET_MARKERS):
        return True
    return key.endswith(_SECRET_SUFFIXES)


def masked_value(name: Any, value: Any) -> Any:
    """Return ``MASK`` for a non-empty secret, otherwise the value unchanged.

    An unset value (``None`` or empty string) is returned as-is so the display
    can tell "not configured" apart from "configured but hidden".
    """
    if value is None or value == "":
        return value
    if is_secret_key(name):
        return MASK
    return value


def format_value(name: Any, value: Any) -> Any:
    """Return a display-ready value with secrets masked.

    A mapping value (e.g. ``rclone_options``) is rendered as ``{k=v, ...}``
    with every secret-looking option masked.  When the key itself is a secret
    the whole value is masked, whatever its type.
    """
    if isinstance(value, dict) and not is_secret_key(name):
        return "{" + ", ".join(
            f"{key}={masked_value(key, item)}" for key, item in value.items()
        ) + "}"
    return masked_value(name, value)