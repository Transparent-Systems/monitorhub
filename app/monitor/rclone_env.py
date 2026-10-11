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
the option name uppercased.  rclone substitutes nothing in the name (verified:
``my-dest`` does not resolve ``RCLONE_CONFIG_MY_DEST_*``), so the remote name we
hand rclone must consist of letters, digits and underscores.  That is a purely
technical restriction of the environment-variable channel -- rclone itself
handles names with dashes perfectly well -- so :func:`env_remote_name` normalises
such names (``s3-test`` -> ``s3_test``) and the mapping is logged at DEBUG level.

A profile's ``rclone_options`` mirrors an ``rclone.conf`` section: a backend
property is stored under its bare name (``no_check_bucket``, ``chunk_size``) and
becomes ``RCLONE_<BACKEND>_<OPTION>`` (``RCLONE_S3_NO_CHECK_BUCKET``), while a
global session flag (``transfers``) becomes ``RCLONE_<OPTION>``.  See
:func:`resolve_option_env_name`.

:func:`build_environment` is the entry point for a handler: it returns the remote
name together with the variables, so the handler never has to know how the name
is derived.
"""

import logging
import re
import subprocess
from dataclasses import dataclass

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

# rclone's config option name is the profile key uppercased, which is what
# rclone-imported profiles already use (``host``, ``user``, ``pass``, ...).  The
# S3 credentials are stored under rclone's own names (``access_key_id``,
# ``secret_access_key``) and the provider under ``provider``, so ``provider``
# uppercases to ``PROVIDER`` with no mapping needed.

# Config key holding extra rclone options for the profile, e.g.
# ``{"transfers": 8, "no_check_bucket": "true", "chunk_size": "16M"}``.
# Backend properties are stored under their bare ``rclone.conf`` name and become
# ``RCLONE_<BACKEND>_<OPTION>`` (``RCLONE_S3_NO_CHECK_BUCKET``); global flags
# become ``RCLONE_<OPTION>`` (``RCLONE_TRANSFERS``).  See
# :func:`resolve_option_env_name`.
RCLONE_OPTIONS_KEY = "rclone_options"

_ENV_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_]")
_OPTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_FLAG_TOKEN_RE = re.compile(r"--([a-z0-9][a-z0-9-]*)")

# How long to wait for ``rclone help flags`` when validating options.
FLAGS_PROBE_TIMEOUT = 30.0

# Flags supported by an rclone binary, keyed by its path (probed once per run).
_KNOWN_FLAGS_CACHE: dict[str, frozenset[str]] = {}


@dataclass(frozen=True)
class RcloneEnvironment:
    """Everything a handler needs to run rclone for one profile.

    ``remote_name`` is the name rclone resolves from ``variables``; the handler
    uses it for the ``<remote>:path`` arguments.
    """

    remote_name: str
    variables: dict[str, str]
    unsupported_options: tuple[str, ...] = ()


def env_remote_name(profile_name: str, profile_id: int | None = None) -> str:
    """Return the remote name rclone will see for a profile.

    The name must be expressible as an environment variable name, so characters
    other than letters, digits and underscore are normalised to ``_`` (the
    profile-name to remote-name mapping is reported at DEBUG by
    :func:`build_environment`).  An empty name falls back to ``mh_<profile id>``.
    """
    name = (profile_name or "").strip()
    if _ENV_SAFE_NAME_RE.match(name):
        return name

    normalised = _UNSAFE_CHARS_RE.sub("_", name)
    if normalised:
        return normalised
    return f"mh_{profile_id}" if profile_id is not None else "mh_profile"


def build_rclone_env(
    remote_name: str,
    profile_type: str,
    profile_config: dict | None = None,
    rclone_path: str = "",
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
    :param rclone_path: rclone binary used to resolve ``rclone_options`` (a bare
        backend property becomes ``RCLONE_<BACKEND>_<OPTION>``); when empty the
        legacy ``RCLONE_<OPTION>`` form is used
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
        option = str(key).upper()
        env[f"{env_prefix}{option}"] = str(value)

    _add_rclone_options(
        env,
        config.get(RCLONE_OPTIONS_KEY),
        profile_type=profile_type,
        known_flags=known_rclone_flags(rclone_path, logger=logger),
        logger=logger,
    )
    return env


def _add_rclone_options(
    env: dict[str, str],
    options: object,
    profile_type: str = "",
    known_flags: frozenset[str] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Add per-profile rclone options as ``RCLONE_*`` variables.

    A backend property is stored under its bare ``rclone.conf`` name and becomes
    ``RCLONE_<BACKEND>_<NAME>``; a global flag becomes ``RCLONE_<NAME>``.  See
    :func:`resolve_option_env_name`.  When the installed rclone could not be
    probed (``known_flags`` is None) the legacy ``RCLONE_<NAME>`` form is used,
    so an option is never silently dropped.
    """
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
        option_name = normalize_option_name(name)
        if not _OPTION_NAME_RE.match(option_name):
            if logger is not None:
                logger.warning(
                    f"Ignoring rclone option {name!r}: option names must be "
                    "letters, digits and underscores (dashes and capitals are "
                    "normalised)"
                )
            continue
        if value is None or value == "":
            continue
        env_name = resolve_option_env_name(option_name, profile_type, known_flags)
        if env_name is None:
            if known_flags is None:
                # No probe available: keep the legacy global-flag form.
                env_name = f"RCLONE_{option_name.upper()}"
            else:
                # Reported by unknown_rclone_options; do not emit a dead variable.
                continue
        env[env_name] = str(value)


def normalize_option_name(name: str) -> str:
    """Return the canonical rclone config name for user input.

    Users type the flag spelling (``no-check-upload``, ``--ftp-no-check-upload``)
    or any capitalisation; the stored name is the lowercase underscore form used
    by ``rclone.conf`` (``ftp_no_check_upload``).  A leading ``--``/``-`` is
    dropped, so a name copied from ``rclone help flags`` can be pasted as-is.
    """
    return str(name).strip().lstrip("-").lower().replace("-", "_")


def is_valid_option_name(name: str) -> bool:
    """Return True when ``name`` is a valid rclone option name.

    Option names become ``RCLONE_<OPTION>`` flag variables, so they are limited
    to lowercase letters, digits and underscores (``transfers``,
    ``s3_chunk_size``).  Callers should pass a name through
    :func:`normalize_option_name` first, which lowercases it and turns dashes
    into underscores.  Exposed so the CLI can validate the same names it asks
    the user for without duplicating the rule.
    """
    return bool(_OPTION_NAME_RE.match(str(name)))


def resolve_option_env_name(
    option_name: str,
    profile_type: str = "",
    known_flags: frozenset[str] | None = None,
) -> str | None:
    """Return the ``RCLONE_*`` variable name an option maps to, or None.

    ``rclone_options`` mirrors an ``rclone.conf`` section: backend properties are
    stored under their bare name (``no_check_bucket``, ``chunk_size``) and the
    backend is implied by ``profile_type``.  A bare name is therefore tried as
    ``<profile_type>-<name>`` first -- the backend property, emitted as
    ``RCLONE_<BACKEND>_<NAME>`` -- and only then as a global flag
    (``RCLONE_<NAME>``).  A backend-qualified name (``s3_chunk_size``) still
    resolves because its bare form matches the backend flag.

    Returns None when the name is neither a backend property of ``profile_type``
    nor a global flag, and when ``known_flags`` is None (no rclone probe).
    """
    if known_flags is None:
        return None
    name = normalize_option_name(option_name)
    if not name:
        return None

    dashed = name.replace("_", "-")
    backend = str(profile_type or "").strip().lower()
    if backend and f"{backend}-{dashed}" in known_flags:
        return f"RCLONE_{backend.upper()}_{name.upper()}"
    if dashed in known_flags:
        return f"RCLONE_{name.upper()}"
    return None


def known_rclone_flags(
    rclone_path: str,
    logger: logging.Logger | None = None,
) -> frozenset[str] | None:
    """Return the flags the rclone binary supports, or None when unknown.

    The probe runs ``rclone help flags`` once per binary and is cached for the
    rest of the run.  It never raises: a missing or failing rclone yields None.
    """
    rclone_path = (rclone_path or "").strip()
    if not rclone_path:
        return None
    if rclone_path in _KNOWN_FLAGS_CACHE:
        return _KNOWN_FLAGS_CACHE[rclone_path]

    try:
        completed = subprocess.run(
            [rclone_path, "help", "flags"],
            capture_output=True,
            text=True,
            check=False,
            timeout=FLAGS_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        if logger is not None:
            logger.warning(f"Could not read the rclone flags: {error}")
        return None

    flags = frozenset(_FLAG_TOKEN_RE.findall(completed.stdout))
    _KNOWN_FLAGS_CACHE[rclone_path] = flags
    return flags


def unknown_rclone_options(
    options: object,
    rclone_path: str,
    profile_type: str = "",
    logger: logging.Logger | None = None,
) -> list[str]:
    """Return the configured rclone options the installed rclone does not know.

    An option is known when it is either a backend property of ``profile_type``
    (stored under its bare ``rclone.conf`` name) or a global flag.  rclone
    silently ignores variables for flags it does not have, so a typo or a machine
    with an older rclone would otherwise apply nothing without saying so.
    Returns an empty list when the options are unknown or the flags cannot be
    read.
    """
    if not isinstance(options, dict) or not options:
        return []

    known = known_rclone_flags(rclone_path, logger=logger)
    if not known:
        return []

    unknown = []
    for name in options:
        option_name = normalize_option_name(name)
        if not _OPTION_NAME_RE.match(option_name):
            continue  # already reported by _add_rclone_options
        if resolve_option_env_name(option_name, profile_type, known) is None:
            unknown.append(option_name)
    return sorted(unknown)


def build_environment(
    profile: dict,
    rclone_path: str = "",
    logger: logging.Logger | None = None,
) -> RcloneEnvironment:
    """Build the rclone environment for a profile.

    Owns the whole profile-to-rclone mapping, so callers (handlers) never deal
    with the remote-name derivation or the option validation themselves:

    * the remote name (normalised for the environment-variable channel, reported
      at DEBUG when it changes);
    * the ``RCLONE_CONFIG_<NAME>_*`` variables for the profile's backend options;
    * the ``RCLONE_<BACKEND>_<OPTION>`` / ``RCLONE_<OPTION>`` variables for the
      profile's ``rclone_options`` (backend properties are stored under their
      bare ``rclone.conf`` name, global flags under their own name);
    * the options the installed rclone does not support (reported as a warning,
      because rclone ignores unknown values silently).

    :param profile: Profile dict with ``name``, ``profile_type`` and ``config``
    :param rclone_path: rclone binary used to validate the options; when empty
        the options are not validated
    :param logger: Optional logger for the normalisation and option messages
    """
    profile_name = str(profile.get("name") or "")
    remote_name = env_remote_name(profile_name, profile.get("id"))
    if logger is not None and remote_name != profile_name:
        logger.debug(
            f"Profile '{profile_name}': rclone remote name normalised to "
            f"'{remote_name}' (rclone environment variable names allow letters, "
            "digits and underscores only)"
        )

    config = profile.get("config")
    profile_config = config if isinstance(config, dict) else {}
    profile_type = str(profile.get("profile_type") or "")
    variables = build_rclone_env(
        remote_name=remote_name,
        profile_type=profile_type,
        profile_config=profile_config,
        rclone_path=rclone_path,
        logger=logger,
    )

    unsupported: tuple[str, ...] = ()
    if rclone_path:
        unknown = unknown_rclone_options(
            profile_config.get(RCLONE_OPTIONS_KEY),
            rclone_path,
            profile_type,
            logger=logger,
        )
        if unknown:
            if logger is not None:
                scope = (
                    f"a '{profile_type}' backend property"
                    if profile_type
                    else "a backend property"
                )
                logger.warning(
                    f"Profile '{profile_name or remote_name}': rclone does not "
                    f"support {', '.join(unknown)} as a global flag or {scope}; "
                    f"these settings are ignored"
                )
            unsupported = tuple(unknown)

    return RcloneEnvironment(
        remote_name=remote_name,
        variables=variables,
        unsupported_options=unsupported,
    )

