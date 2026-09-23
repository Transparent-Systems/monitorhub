"""Describe a MonitorHub profile to rclone through the environment.

MonitorHub owns every profile, so an rclone-routed profile does not need a
section in ``rclone.conf``.  Instead its configuration is passed to the rclone
subprocess as ``RCLONE_CONFIG_<REMOTE>_<OPTION>`` variables::

    RCLONE_CONFIG_MYDEST_TYPE=s3
    RCLONE_CONFIG_MYDEST_PROVIDER=Other
    RCLONE_CONFIG_MYDEST_ENDPOINT=https://example.invalid
    RCLONE_CONFIG_MYDEST_ACCESS_KEY_ID=...
    RCLONE_CONFIG_MYDEST_SECRET_ACCESS_KEY=...

rclone resolves ``<remote>:path`` from those variables, so
:class:`~app.monitor.rclone_handler.RcloneHandler` keeps its normal
``<profile>:path`` command shape and works without ``rclone.conf``.

The variables are passed per subprocess (``subprocess.Popen(env=...)``), so they
are local to that one rclone process: the MonitorHub process, other monitors and
other rclone invocations are unaffected, and secrets never appear in the command
line (``ps``) or in the log.

Environment names are ``RCLONE_CONFIG_`` + the remote name uppercased + ``_`` +
the option name uppercased.  rclone does not substitute characters in the name
(verified: ``my-dest`` does not resolve ``RCLONE_CONFIG_MY_DEST_*``), so a name
that is not ``[A-Za-z0-9_]`` cannot be expressed.  Such names are sanitised by
:func:`env_remote_name`; keep profile names to letters, digits and underscores to
have the name in the log match the one rclone sees.
"""

import logging
import re

from app.utils import reference_data

# Prefix of every rclone configuration variable.
RCLONE_CONFIG_PREFIX = "RCLONE_CONFIG_"

# Config keys that belong to MonitorHub and must never be sent to rclone as
# backend options.  ``comment``/``important`` are legacy display hints from the
# rclone-import era and are ignored here.
MONITORHUB_ONLY_KEYS = frozenset(
    {
        reference_data.CONFIG_REMOTE_HANDLER,
        "rclone_options",
        "comment",
        "important",
    }
)

# MonitorHub config key -> rclone backend option name.  Keys absent from this
# table keep their own name (uppercased), which is what rclone-imported profiles
# already use (host, user, pass, ...).
CONFIG_KEY_TO_RCLONE_OPTION: dict[str, str] = {
    "provider_name": "PROVIDER",
    "access_key_secret": "SECRET_ACCESS_KEY",
}

# Config key holding extra rclone options for the profile, e.g.
# ``{"transfers": 8, "s3_chunk_size": "16M"}``.  Each entry becomes a global
# rclone flag variable (``RCLONE_TRANSFERS``, ``RCLONE_S3_CHUNK_SIZE``).
RCLONE_OPTIONS_KEY = "rclone_options"

_ENV_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_]")
_OPTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def env_remote_name(profile_name: str, profile_id: int | None = None) -> str:
    """Return the remote name rclone will see for a profile.

    The name must be expressible as an environment variable name, so a name
    that is not ``[A-Za-z0-9_]`` is sanitised (invalid characters become ``_``).
    An empty name falls back to ``mh_<profile id>``.
    """
    name = (profile_name or "").strip()
    if _ENV_SAFE_NAME_RE.match(name):
        return name

    sanitised = _UNSAFE_CHARS_RE.sub("_", name)
    if sanitised:
        return sanitised
    return f"mh_{profile_id}" if profile_id is not None else "mh_profile"


def build_rclone_env(
    remote_name: str,
    profile_type: str,
    profile_config: dict | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, str]:
    """Build the rclone environment for one profile.

    Returns the ``RCLONE_*`` variables that describe the remote (``TYPE`` plus
    the profile's backend options) and any per-profile rclone options.
    MonitorHub-only keys and empty values are skipped; unknown option names are
    reported and ignored.

    :param remote_name: Remote name rclone resolves, from :func:`env_remote_name`
    :param profile_type: rclone backend type (the profile's ``profile_type``)
    :param profile_config: Profile configuration dict
    :param logger: Optional logger for warnings
    """
    env: dict[str, str] = {}
    remote_name = (remote_name or "").strip()
    if not remote_name:
        if logger is not None:
            logger.warning(
                "Cannot build the rclone environment: the profile has no usable name"
            )
        return env

    config = profile_config if isinstance(profile_config, dict) else {}
    env_prefix = f"{RCLONE_CONFIG_PREFIX}{remote_name.upper()}_"

    if profile_type:
        env[f"{env_prefix}TYPE"] = profile_type
    elif logger is not None:
        logger.warning(
            f"Profile '{remote_name}' has no profile_type; rclone needs a "
            f"{env_prefix}TYPE variable to resolve the remote"
        )

    for key, value in config.items():
        if key in MONITORHUB_ONLY_KEYS:
            continue
        if value is None or value == "":
            continue
        option = CONFIG_KEY_TO_RCLONE_OPTION.get(key, str(key).upper())
        env[f"{env_prefix}{option}"] = str(value)

    _add_rclone_options(env, config.get(RCLONE_OPTIONS_KEY), logger=logger)
    return env


def _add_rclone_options(
    env: dict[str, str],
    options: object,
    logger: logging.Logger | None = None,
) -> None:
    """Add per-profile rclone options as ``RCLONE_<OPTION>`` flag variables."""
    if options is None:
        return
    if not isinstance(options, dict):
        if logger is not None:
            logger.warning(
                f"{RCLONE_OPTIONS_KEY} must be a mapping of option name to value; "
                f"ignoring {options!r}"
            )
        return

    for name, value in options.items():
        option_name = str(name).strip()
        if not _OPTION_NAME_RE.match(option_name):
            if logger is not None:
                logger.warning(
                    f"Ignoring rclone option {name!r}: option names must be "
                    "lowercase letters, digits and underscores"
                )
            continue
        if value is None or value == "":
            continue
        env[f"RCLONE_{option_name.upper()}"] = str(value)

