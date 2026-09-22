"""Static reference data that was previously stored in database lookup tables.

All data here is owned by the code, not the database.  It holds the
profile-type *category* vocabulary -- how a profile type is categorized
(``remote`` or ``command``) and how that category is presented in the CLI
prompts.  Which concrete handler a profile type maps to is decided by
``app.monitor.handler_factory`` (the ``REMOTE_HANDLERS`` table plus the rclone
fallback); this module stays free of the handler classes because importing them
would pull in boto3, which the CLI must avoid on startup.

Import convention
-----------------
Import the module as a whole and access members through the module name::

    from app.utils import reference_data
    reference_data.get_profile_category("s3")

rather than ``from app.utils.reference_data import ...``.  Almost the
whole codebase uses the module form, and it keeps these names from
colliding with constants imported from ``app.utils.constants``.
"""

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
    Provider("Amazon AWS S3", "s3", "Amazon AWS S3"),
    Provider("Cloudflare",    "s3", "Cloudflare R2 - S3 compatible cloud storage"),
    Provider("IDrive",        "s3", "IDrive E2 - S3 compatible cloud storage"),
    Provider("Backblaze",     "s3", "Backblaze B2 - S3 compatible cloud storage"),
    Provider("Other",         "s3", "Other S3 compatible cloud storage"),
)


def get_provider(provider_name: str) -> Provider | None:
    """Look up a provider by exact name (case-sensitive)."""
    for p in PROVIDERS:
        if p.name == provider_name:
            return p
    return None


def get_providers() -> tuple[Provider, ...]:
    """Return all known providers."""
    return PROVIDERS


# ---------------------------------------------------------------------------
# Monitor type / status reference data
# ---------------------------------------------------------------------------

# (name, description) tuples — used for UI display in monitor commands.
# The name element references the canonical value in ``app.utils.constants``,
# so display keys can never drift from the status/type writer vocabulary.
MONITOR_TYPES: tuple[tuple[str, str], ...] = (
    (constants.MONITOR_TYPE_INSTANT, "Instant upload of changed file to remote"),
    (constants.MONITOR_TYPE_BACKUP,  "Backup to remote"),
    (constants.MONITOR_TYPE_RESTORE, "Restore from remote"),
)

MONITOR_STATUSES: tuple[tuple[str, str], ...] = (
    (constants.MONITOR_STATUS_RUNNING, "Monitor is running"),
    (constants.MONITOR_STATUS_STOP,    "Monitor is about to stop"),
    (constants.MONITOR_STATUS_STOPPED, "Monitor has stopped running"),
    (constants.MONITOR_STATUS_ERROR,   "Monitor has an error state"),
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

# Display hints stored in the config of profiles imported from rclone.  They
# explain that the stored credentials are informational only and that the
# profile must stay in rclone.conf to keep working.  Rclone-managed profile
# types are not editable from MonitorHub; see ProfileEditor._edit_remote.
RCLONE_PROFILE_COMMENT = (
    "Credentials stored here are for informational purposes only."
)
RCLONE_PROFILE_IMPORTANT = (
    "Profile must be in rclone config in order to work ! "
)

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


def is_rclone_profile_type(profile_type: str) -> bool:
    """Return True when a profile type is backed by the rclone CLI.

    Command profile types and profile types with a native handler do not need
    rclone; every other remote profile type is delegated to rclone by
    ``app.monitor.handler_factory``.
    """
    if not profile_type or profile_type in COMMAND_PROFILE_TYPES:
        return False
    return profile_type not in NATIVE_PROFILE_TYPES