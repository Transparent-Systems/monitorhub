import logging
from collections.abc import Callable

from app.monitor.rclone_handler import RcloneHandler
from app.monitor.remote_handler import RemoteHandler
from app.monitor.s3_handler import S3Handler


class RemoteHandlerFactory:
    """
    Registry/factory for creating RemoteHandler instances.

    Native handlers are registered via ``RemoteHandlerFactory.register()`` (see
    the registration block at the bottom of this module). This mirrors the
    registry pattern used by ``MonitorHandlerFactory`` and keeps the factory
    extensible: adding a new remote profile type only requires a new
    ``RemoteHandler`` subclass plus one ``register()`` call.

    The set of registered types is the single source of truth for which profile
    types are implemented natively (as opposed to delegated to rclone). See
    ``a/reference_data.py``.
    """

    _handlers: dict[str, Callable[..., RemoteHandler]] = {}

    @classmethod
    def register(cls, profile_type: str, handler_factory: Callable[..., RemoteHandler]) -> None:
        """Register a handler class or callable for a profile_type."""
        if not profile_type:
            raise ValueError("profile_type must not be empty")
        cls._handlers[profile_type] = handler_factory

    @classmethod
    def is_registered(cls, profile_type: str) -> bool:
        """Return True if a native handler is registered for profile_type."""
        return profile_type in cls._handlers

    @classmethod
    def registered_types(cls) -> list[str]:
        """Return the sorted list of natively implemented profile types."""
        return sorted(cls._handlers)

    @classmethod
    def get_handler(
        cls,
        monitor_path: str,
        remote_path: str,
        profile: dict,
        logger: logging.Logger | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> RemoteHandler:
        """
        Returns a RemoteHandler instance based on the profile_type.

        :param monitor_path: Local monitor path
        :param remote_path: Remote path
        :param profile: Profile configuration dict
        :param logger: Optional logger instance
        :param exclude_patterns: Optional list of exclude patterns to apply
            during backup (local walk) and restore (remote listing).
        """
        logger = logger or logging.getLogger(__name__)

        # We need to instantiate a remote handler based on the profile_type
        # A profile can be a native profile or imported from Rclone
        profile_type = profile.get("profile_type", "").strip()
        profile_name = profile.get("name", "").strip()
        profile_config = profile.get("config", {})

        handler_factory = cls._handlers.get(profile_type)
        if handler_factory is not None:
            kwargs = {
                "base_monitor_path": monitor_path,
                "base_remote_path": remote_path,
                "profile_config": profile_config or {},
                "logger": logger,
            }
            # Native ``RemoteHandler`` subclasses declare ``exclude_patterns``
            # as part of their contract, so forward it to those. A custom
            # callable registered here may not accept it.
            if isinstance(handler_factory, type) and issubclass(
                handler_factory, RemoteHandler
            ):
                kwargs["exclude_patterns"] = exclude_patterns or []
            return handler_factory(**kwargs)

        # Any profile type without a native handler is delegated to rclone,
        # using the profile's name (which matches the remote section name in
        # rclone.conf).
        rclone_profile_name = profile_name or profile_type
        if not rclone_profile_name:
            logger.warning(
                "RemoteHandlerFactory: profile name and profile_type are empty; "
                "falling back to RcloneHandler with an empty profile name"
            )
        return RcloneHandler(
            base_monitor_path=monitor_path,
            base_remote_path=remote_path,
            profile_name=rclone_profile_name,
            logger=logger,
            exclude_patterns=exclude_patterns or [],
        )


# Register the built-in native handlers. Adding a new native handler (e.g. FTP)
# means adding a RemoteHandler subclass plus one register() call here.
RemoteHandlerFactory.register(S3Handler.PROFILE_TYPE, S3Handler)
