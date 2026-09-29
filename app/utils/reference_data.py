"""Static reference data that was previously stored in database lookup tables.

All data here is owned by the code, not the database.  It holds the
profile-type *category* vocabulary -- how a profile type is categorized
(``remote`` or ``command``) and how that category is presented in the CLI
prompts.  It also owns the ``remote_handler`` vocabulary: the config key that
records which handler a remote profile is routed through, and the helpers that
resolve it (falling back to profile-type routing).  Which concrete handler a
key maps to is decided by ``app.monitor.handler_factory`` (the
``REMOTE_HANDLERS`` table plus the rclone fallback); this module stays free of
the handler classes because importing them would pull in boto3, which the CLI
must avoid on startup.

Import convention
-----------------
Import the module as a whole and access members through the module name::

    from app.utils import reference_data
    reference_data.get_profile_category("s3")

rather than ``from app.utils.reference_data import ...``.  Almost the
whole codebase uses the module form, and it keeps these names from
colliding with constants imported from ``app.utils.constants``.
"""

import logging
from dataclasses import dataclass

from app.utils import constants

# ---------------------------------------------------------------------------
# Provider reference data (previously the "providers" table)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Provider:
    name: str
    profile_type: str          # currently always "s3"
    description: str


PROVIDERS: tuple[Provider, ...] = (
    Provider("AWS", "s3", "Amazon AWS S3"),
    Provider("Cloudflare",    "s3", "Cloudflare R2 - S3 compatible cloud storage"),
    Provider("IDrive",        "s3", "IDrive E2 - S3 compatible cloud storage"),
    Provider("Backblaze",     "s3", "Backblaze B2 - S3 compatible cloud storage"),
    Provider("Other",         "s3", "Other S3 compatible cloud storage"),
)


def get_provider(provider: str) -> Provider | None:
    """Look up a provider by exact name (case-sensitive)."""
    for p in PROVIDERS:
        if p.name == provider:
            return p
    return None


def get_providers() -> tuple[Provider, ...]:
    """Return all known providers."""
    return PROVIDERS


def is_aws_provider(provider: str) -> bool:
    """Return True when a provider name refers to Amazon AWS S3.

    The built-in provider is named ``AWS`` (matching the rclone remote key) and
    rclone-imported profiles may carry ``AWS`` or a name containing ``amazon``
    (e.g. the historical ``Amazon AWS S3``).  AWS profiles need a region instead
    of an endpoint, so this rule is shared by the CLI wizard and the S3 client
    factory.
    """
    provider_key = (provider or "").strip().lower()
    return provider_key == "aws" or "amazon" in provider_key


# ---------------------------------------------------------------------------
# Monitor type reference data
# ---------------------------------------------------------------------------

# (name, description) tuples — used for UI display in monitor commands.
# The name element references the canonical value in ``app.utils.constants``,
# so display keys can never drift from the type writer vocabulary.
MONITOR_TYPES: tuple[tuple[str, str], ...] = (
    (constants.MONITOR_TYPE_INSTANT, "Instant upload of changed file to remote"),
    (constants.MONITOR_TYPE_BACKUP,  "Backup to remote"),
    (constants.MONITOR_TYPE_RESTORE, "Restore from remote"),
)


# ---------------------------------------------------------------------------
# Profile type categories and command types
# ---------------------------------------------------------------------------

PROFILE_CATEGORY_REMOTE  = "remote"
PROFILE_CATEGORY_COMMAND = "command"

# (name, description) tuples — used for UI display in profile commands.
# Mirrors MONITOR_TYPES so the user selects a category interactively the same
# way they select a monitor type in "monitor new".
PROFILE_CATEGORIES: tuple[tuple[str, str], ...] = (
    (PROFILE_CATEGORY_REMOTE,  "Remote profile (upload/download via provider or rclone)"),
    (PROFILE_CATEGORY_COMMAND, "Command profile (run a shell command on events)"),
)

# These profile types are handled by CommandActionHandler, not RemoteHandler.
COMMAND_PROFILE_TYPES = ("event_command",)

# Remote profile types that have a native Python handler and therefore do not
# need rclone. Mirrors the keys of
# ``app.monitor.handler_factory.REMOTE_HANDLERS``; that module is deliberately
# not imported here because it pulls in boto3. tests/test_reference_data.py
# asserts the two stay in sync.
NATIVE_PROFILE_TYPES: tuple[str, ...] = ("s3",)

# Config key that records which handler a remote profile is routed through.
# Every remote profile stores it explicitly, so routing never has to be
# re-derived from profile_type at runtime.  Valid values are the native handler
# keys (mirrored by NATIVE_PROFILE_TYPES) plus RCLONE_REMOTE_HANDLER.
CONFIG_REMOTE_HANDLER = "remote_handler"

# Value of CONFIG_REMOTE_HANDLER meaning "delegate to the rclone CLI".  Using
# rclone requires a matching remote section in rclone.conf.
RCLONE_REMOTE_HANDLER = "rclone"

# Display hints stored in the config of profiles imported from rclone.  They
# are no longer written: MonitorHub owns the profile configuration and feeds it
# to rclone through the environment (see ``app.monitor.rclone_env``).  Existing
# profiles may still carry ``comment``/``important``; they are ignored when the
# rclone environment is built.

# Documentation-only — handled by rclone, not a native handler.
# Listed here so the vocabulary is visible; no runtime behaviour depends on them.
KNOWN_RCLONE_PROFILE_TYPES: tuple[tuple[str, str], ...] = (
    ("ftp",   "FTP Server"),
    ("sftp",  "SFTP Server"),
    ("drive", "Google Drive"),
    ("azure", "Azure Blob Storage"),
    ("ssh",   "SSH Server"),
    ("http",  "HTTP Server"),
)


# ---------------------------------------------------------------------------
# Helpers (replace the old SQLiteHandler lookup-table / provider methods)
# ---------------------------------------------------------------------------

def get_profile_category(profile_type: str) -> str:
    """Return the category ('remote' or 'command') for a profile type.

    Anything that is not an explicit command profile type is treated as
    "remote" and delegated to a native handler or rclone.
    """
    if profile_type in COMMAND_PROFILE_TYPES:
        return PROFILE_CATEGORY_COMMAND
    return PROFILE_CATEGORY_REMOTE


def remote_handler_keys() -> tuple[str, ...]:
    """Return every valid value of the ``remote_handler`` config key."""
    return NATIVE_PROFILE_TYPES + (RCLONE_REMOTE_HANDLER,)


def default_remote_handler_key(profile_type: str) -> str:
    """Return the handler key a profile type is routed through by default.

    Command profile types have no remote handler and yield ``""``; a profile
    type with a native handler is routed to that handler; every other remote
    profile type is delegated to rclone.
    """
    if not profile_type or profile_type in COMMAND_PROFILE_TYPES:
        return ""
    if profile_type in NATIVE_PROFILE_TYPES:
        return profile_type
    return RCLONE_REMOTE_HANDLER


def remote_handler_key(
    profile: dict,
    logger: logging.Logger | None = None,
) -> str:
    """Return the handler key a profile is routed through.

    Reads the profile's ``remote_handler`` config key and falls back to
    :func:`default_remote_handler_key` when the key is missing or holds an
    unrecognised value (logged as a warning when a logger is given), so a
    hand-edited profile can never break handler routing.
    """
    profile_type = str(profile.get("profile_type") or "").strip()
    default_key = default_remote_handler_key(profile_type)

    config = profile.get("config") or {}
    if not isinstance(config, dict):
        return default_key

    stored = config.get(CONFIG_REMOTE_HANDLER)
    if stored is None:
        return default_key

    stored_key = str(stored).strip()
    if stored_key == "":
        return default_key

    if stored_key in remote_handler_keys():
        return stored_key

    if logger is not None:
        logger.warning(
            f"Profile '{profile.get('name')}' has unknown "
            f"{CONFIG_REMOTE_HANDLER}={stored!r}; falling back to '{default_key}'"
        )
    return default_key


def is_rclone_profile(
    profile: dict,
    logger: logging.Logger | None = None,
) -> bool:
    """Return True when a profile is handled by the rclone CLI.

    Command profile types and profiles routed to a native handler do not need
    rclone; every profile whose ``remote_handler`` resolves to
    :data:`RCLONE_REMOTE_HANDLER` does.
    """
    return remote_handler_key(profile, logger=logger) == RCLONE_REMOTE_HANDLER
