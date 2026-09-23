"""Single high-level factory that maps a profile type to a handler.

Every profile type resolves to exactly one action handler:

- ``event_command``  -> :class:`~app.monitor.action_handler.CommandActionHandler`
- ``s3``             -> :class:`~app.monitor.action_handler.RemoteActionHandler`
  wrapping :class:`~app.monitor.s3_handler.S3Handler`
- any other type     -> :class:`~app.monitor.action_handler.RemoteActionHandler`
  wrapping :class:`~app.monitor.rclone_handler.RcloneHandler`

Remote profiles are routed by their ``remote_handler`` config key (see
``app.utils.reference_data``): a key present in the declarative
:data:`REMOTE_HANDLERS` table gets its native handler, and the ``rclone`` key is
delegated to rclone.  A profile without a usable key falls back to its
``profile_type`` (native handler when mapped, otherwise rclone).  Command
profile types are the ones listed in
``app.utils.reference_data.COMMAND_PROFILE_TYPES`` -- the profile-type to
category table that also drives the CLI prompts.

The handler classes (``S3Handler``) pull in boto3, so this module is only
imported when handlers are actually constructed (monitor runtime and ``mhub
config test``); plain CLI imports stay free of boto3.
"""

import logging

from app.monitor.action_handler import (
    ActionHandler,
    CommandActionHandler,
    RemoteActionHandler,
)
from app.monitor.rclone_handler import RcloneHandler
from app.monitor.remote_handler import RemoteHandler
from app.monitor.s3_handler import S3Handler
from app.utils import reference_data
from app.utils.constants import DEFAULT_COMMAND_MAX_WORKERS

# Declarative remote_handler key -> RemoteHandler class mapping.  The ``rclone``
# key (reference_data.RCLONE_REMOTE_HANDLER) is the delegated fallback rather
# than a table entry.  Adding a native handler means one entry in this table
# (plus the handler class itself and its key in
# reference_data.NATIVE_PROFILE_TYPES).
REMOTE_HANDLERS: dict[str, type[RemoteHandler]] = {
    S3Handler.PROFILE_TYPE: S3Handler,
}


def get_remote_handler(
    monitor_path: str,
    remote_path: str,
    profile: dict,
    logger: logging.Logger | None = None,
    exclude_patterns: list[str] | None = None,
) -> RemoteHandler:
    """Return the :class:`RemoteHandler` for a profile's routing key.

    The profile's ``remote_handler`` config key selects the handler: a key
    present in :data:`REMOTE_HANDLERS` gets its native handler, and
    ``rclone`` is delegated to :class:`RcloneHandler`.  When the key is missing
    the route is derived from ``profile_type`` (see
    :func:`app.utils.reference_data.remote_handler_key`).

    :param monitor_path: Local monitor path
    :param remote_path: Remote path
    :param profile: Profile configuration dict
    :param logger: Optional logger instance
    :param exclude_patterns: Optional list of exclude patterns to apply during
        backup (local walk) and restore (remote listing).
    """
    logger = logger or logging.getLogger(__name__)

    profile_type = profile.get("profile_type", "").strip()
    profile_name = profile.get("name", "").strip()
    profile_config = profile.get("config", {})

    handler_key = reference_data.remote_handler_key(profile, logger=logger)
    logger.debug(
        f"get_remote_handler: profile '{profile_name}' "
        f"(type={profile_type or 'n/a'}) routed via '{handler_key}'"
    )

    handler_class = REMOTE_HANDLERS.get(handler_key)
    if handler_class is not None:
        return handler_class(
            base_monitor_path=monitor_path,
            base_remote_path=remote_path,
            profile_config=profile_config or {},
            logger=logger,
            exclude_patterns=exclude_patterns or [],
        )

    # The rclone key (and, defensively, any unresolvable key) uses the rclone
    # CLI.  The profile's configuration is passed through the environment
    # (RCLONE_CONFIG_<NAME>_*), so no section in rclone.conf is required.
    rclone_profile_name = profile_name or profile_type
    if not rclone_profile_name:
        logger.warning(
            "get_remote_handler: profile name and profile_type are empty; "
            "falling back to RcloneHandler with an empty profile name"
        )
    return RcloneHandler(
        base_monitor_path=monitor_path,
        base_remote_path=remote_path,
        profile_name=rclone_profile_name,
        logger=logger,
        exclude_patterns=exclude_patterns or [],
        profile=profile,
    )


class HandlerFactory:
    """Factory creating the ActionHandler for a monitor/profile pair.

    Dispatch is driven purely by ``profile_type``: command profile types
    (``reference_data.COMMAND_PROFILE_TYPES``) get a
    :class:`CommandActionHandler`; every other profile type is a remote profile
    wrapped in a :class:`RemoteActionHandler` whose underlying
    :class:`RemoteHandler` is chosen by the profile's ``remote_handler`` key
    (native handler when mapped in :data:`REMOTE_HANDLERS`, otherwise rclone).
    """

    @classmethod
    def get_handler(
        cls,
        monitor: dict,
        profile: dict | None,
        logger: logging.Logger | None = None,
        debounce_delay: float = 1.0,
    ) -> ActionHandler | None:
        """Create the ActionHandler for *profile*.

        :param monitor: Monitor dictionary with 'monitor_path'/'path',
            'remote_path', 'name', etc.
        :param profile: Profile dictionary with 'profile_type', 'config', etc.
        :param logger: Optional logger instance.
        :param debounce_delay: Delay for debounce in remote handlers (default 1.0s).
        :return: An ActionHandler (CommandActionHandler or RemoteActionHandler),
            or None when the profile is missing or cannot be built.
        """
        logger = logger or logging.getLogger(__name__)
        if not profile:
            return None

        profile_type = profile.get("profile_type", "").strip()
        if profile_type in reference_data.COMMAND_PROFILE_TYPES:
            return cls._create_command_handler(
                monitor=monitor,
                profile=profile,
                profile_type=profile_type,
                logger=logger,
            )
        return cls._create_remote_handler(
            monitor=monitor,
            profile=profile,
            logger=logger,
            debounce_delay=debounce_delay,
        )

    @classmethod
    def _create_command_handler(
        cls,
        monitor: dict,
        profile: dict,
        profile_type: str,
        logger: logging.Logger,
    ) -> ActionHandler | None:
        """Create a CommandActionHandler for a command profile type."""
        config_obj = profile.get("config")
        cfg: dict = config_obj if isinstance(config_obj, dict) else {}

        cmd = profile.get("command") or cfg.get("command", "")
        cmd_str = cmd.strip() if isinstance(cmd, str) else ""
        if not cmd_str:
            logger.warning(
                f"Profile '{profile.get('name')}' is a command profile ({profile_type}) but has no 'command' configured"
            )
            return None

        events = cfg.get("command_events", "")
        cooldown = cfg.get("command_cooldown", "0s")
        shell = cfg.get("command_shell", False)
        # String default matches CommandActionHandler's declared contract. A
        # float default (60.0) collapsed to 0 in convert_to_seconds, making
        # subprocess.run(timeout=0) kill every command instantly.
        timeout = cfg.get("command_timeout", "60s")
        max_workers = cfg.get("command_max_workers", DEFAULT_COMMAND_MAX_WORKERS)

        return CommandActionHandler(
            command=cmd_str,
            monitor_name=monitor.get("name", ""),
            profile_name=profile.get("name", ""),
            events=events,
            cooldown=cooldown,
            shell=bool(shell),
            timeout=timeout,
            logger=logger,
            max_workers=max_workers,
        )

    @classmethod
    def _create_remote_handler(
        cls,
        monitor: dict,
        profile: dict,
        logger: logging.Logger,
        debounce_delay: float,
    ) -> ActionHandler | None:
        """Create a RemoteActionHandler for a remote profile type."""
        monitor_path = monitor.get("monitor_path") or monitor.get("path", "")
        remote_path = monitor.get("remote_path", "")
        remote_handler = get_remote_handler(
            monitor_path=monitor_path,
            remote_path=remote_path,
            profile=profile,
            logger=logger,
        )
        return RemoteActionHandler(
            remote_handler=remote_handler,
            logger=logger,
            debounce_delay=debounce_delay,
        )