"""Unit tests for ``app.utils.logger_setup.setup_logging``.

``setup_logging`` mutates process-global logging state (the root logger's
level and handler set, plus the levels of the third-party dependency
loggers), so every test snapshots that state in ``setUp`` and restores it in
``tearDown`` via ``addCleanup``.  The YAML config and log files live in a
per-test temporary directory, so no repository ``conf/`` or ``logs/`` files
are touched.
"""

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.utils.logger_setup import setup_logging

DEPENDENCY_LOGGERS = ("boto3", "botocore", "s3transfer", "urllib3")
UNRELATED_LOGGERS = ("MonitorHub", "watchdog")


def _write_config(tmp_dir: str, log_level: str = "INFO") -> str:
    """Write a minimal logging config into ``tmp_dir`` and return its path."""
    config_path = os.path.join(tmp_dir, "log.yaml")
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(
            "version: 1.0.0\n"
            "logging:\n"
            "  file_name: test_logger.log\n"
            f"  folder: {os.path.join(tmp_dir, 'logs')}\n"
            "  max_bytes: 10485760\n"
            "  max_backup_count: 5\n"
            f"  log_level: {log_level}\n"
        )
    return config_path


def _write_relative_config(
    tmp_dir: str, folder: str = "logs", file_name: str = "app.log"
) -> str:
    """Write a logging config with the given (possibly relative) folder/file."""
    config_path = os.path.join(tmp_dir, "log_relative.yaml")
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(
            "version: 1.0.0\n"
            "logging:\n"
            f"  file_name: {file_name}\n"
            f"  folder: {folder}\n"
            "  max_bytes: 10485760\n"
            "  max_backup_count: 5\n"
            "  log_level: INFO\n"
        )
    return config_path


class TestSetupLogging(unittest.TestCase):
    """Behavioural tests for level resolution, clean-slate and silencing."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = tmp.name
        self.config_path = _write_config(self.tmp_dir)

        root = logging.getLogger()
        self._snapshot = {
            "root_level": root.level,
            "root_handlers": list(root.handlers),
            "levels": {
                name: logging.getLogger(name).level
                for name in DEPENDENCY_LOGGERS + UNRELATED_LOGGERS
            },
            "env": os.environ.get("MONITORHUB_LOG_LEVEL"),
            "dep_env": os.environ.get("MONITORHUB_DEPENDENCY_LOG_LEVEL"),
        }
        self.addCleanup(self._restore_logging_state)

    def _restore_logging_state(self) -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if handler not in self._snapshot["root_handlers"]:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(self._snapshot["root_level"])
        for name, level in self._snapshot["levels"].items():
            logging.getLogger(name).setLevel(level)
        if self._snapshot["env"] is None:
            os.environ.pop("MONITORHUB_LOG_LEVEL", None)
        else:
            os.environ["MONITORHUB_LOG_LEVEL"] = self._snapshot["env"]
        if self._snapshot["dep_env"] is None:
            os.environ.pop("MONITORHUB_DEPENDENCY_LOG_LEVEL", None)
        else:
            os.environ["MONITORHUB_DEPENDENCY_LOG_LEVEL"] = self._snapshot["dep_env"]

    # --- config / level resolution -------------------------------------------

    def test_returns_monitorhub_logger_and_config(self):
        logger, log_config = setup_logging(self.config_path)
        self.assertEqual(logger.name, "MonitorHub")
        self.assertIs(logger, logging.getLogger("MonitorHub"))
        self.assertEqual(log_config["log_level"], "INFO")
        self.assertEqual(log_config["file_name"], "test_logger.log")

    def test_yaml_level_used_by_default(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("MONITORHUB_LOG_LEVEL", None)
            setup_logging(self.config_path)
        self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_explicit_log_level_overrides_yaml(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("MONITORHUB_LOG_LEVEL", None)
            setup_logging(self.config_path, log_level="DEBUG")
        self.assertEqual(logging.getLogger().level, logging.DEBUG)

    def test_yaml_numeric_level_is_accepted(self):
        """A numeric YAML log_level must not raise on .upper()."""
        config_path = _write_config(self.tmp_dir, log_level="20")
        with mock.patch.dict(os.environ):
            os.environ.pop("MONITORHUB_LOG_LEVEL", None)
            setup_logging(config_path)
        self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_env_var_overrides_yaml(self):
        with mock.patch.dict(os.environ, {"MONITORHUB_LOG_LEVEL": "ERROR"}):
            setup_logging(self.config_path)
        self.assertEqual(logging.getLogger().level, logging.ERROR)

    def test_explicit_log_level_wins_over_env_var(self):
        with mock.patch.dict(os.environ, {"MONITORHUB_LOG_LEVEL": "ERROR"}):
            setup_logging(self.config_path, log_level="CRITICAL")
        self.assertEqual(logging.getLogger().level, logging.CRITICAL)

    # --- handlers / clean slate ----------------------------------------------

    def test_handlers_configured_on_root(self):
        setup_logging(self.config_path)
        handlers = logging.getLogger().handlers
        file_handlers = [
            h for h in handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        console_handlers = [
            h
            for h in handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        self.assertEqual(len(handlers), 2)
        self.assertEqual(len(file_handlers), 1)
        self.assertEqual(len(console_handlers), 1)
        self.assertTrue(file_handlers[0].baseFilename.endswith("test_logger.log"))

    def test_clean_slate_removes_pre_existing_handlers(self):
        root = logging.getLogger()
        dummy = logging.StreamHandler()
        root.addHandler(dummy)
        setup_logging(self.config_path)
        self.assertNotIn(dummy, root.handlers)
        self.assertEqual(len(root.handlers), 2)

    def test_missing_config_creates_default(self):
        cwd = os.getcwd()
        os.chdir(self.tmp_dir)
        self.addCleanup(os.chdir, cwd)
        missing = os.path.join(self.tmp_dir, "missing", "log.yaml")
        with mock.patch(
            "app.utils.logger_setup.project_root", return_value=Path(self.tmp_dir)
        ):
            logger, log_config = setup_logging(missing)
        self.assertTrue(os.path.exists(missing))
        self.assertEqual(log_config["log_level"], "INFO")
        self.assertEqual(logger.name, "MonitorHub")

    def _file_handlers(self):
        return [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]

    def test_relative_folder_anchors_to_project_root(self):
        """A relative ``folder`` resolves against the project root, not the CWD."""
        root_dir = Path(self.tmp_dir) / "app"
        root_dir.mkdir(parents=True, exist_ok=True)
        config_path = _write_relative_config(
            self.tmp_dir, folder="logs", file_name="app.log"
        )
        with mock.patch("app.utils.logger_setup.project_root", return_value=root_dir):
            setup_logging(config_path)
        handlers = self._file_handlers()
        self.assertEqual(handlers[0].baseFilename, str(root_dir / "logs" / "app.log"))
        self.assertTrue((root_dir / "logs").is_dir())

    def test_absolute_folder_passes_through(self):
        """An absolute ``folder`` is used verbatim."""
        abs_dir = Path(self.tmp_dir) / "abs-logs"
        config_path = _write_relative_config(
            self.tmp_dir, folder=str(abs_dir), file_name="app.log"
        )
        setup_logging(config_path)
        handlers = self._file_handlers()
        self.assertEqual(handlers[0].baseFilename, str(abs_dir / "app.log"))
        self.assertTrue(abs_dir.is_dir())

    def test_absolute_file_name_is_full_log_path(self):
        """An absolute ``file_name`` overrides the folder entirely."""
        abs_dir = Path(self.tmp_dir) / "var" / "log"
        config_path = _write_relative_config(
            self.tmp_dir, folder="logs", file_name=str(abs_dir / "app.log")
        )
        setup_logging(config_path)
        handlers = self._file_handlers()
        self.assertEqual(handlers[0].baseFilename, str(abs_dir / "app.log"))
        self.assertTrue(abs_dir.is_dir())

    # --- dependency silencing (quiet_dependencies) ---------------------------

    def test_quiet_dependencies_default_silences_libraries(self):
        setup_logging(self.config_path)
        for name in DEPENDENCY_LOGGERS:
            self.assertEqual(
                logging.getLogger(name).level,
                logging.WARNING,
                f"{name} should be floored to WARNING by default",
            )

    def test_quiet_dependencies_opt_out_leaves_libraries_alone(self):
        setup_logging(self.config_path, quiet_dependencies=False)
        for name in DEPENDENCY_LOGGERS:
            self.assertEqual(
                logging.getLogger(name).level,
                logging.NOTSET,
                f"{name} must be untouched when quiet_dependencies=False",
            )

    def test_quiet_dependencies_is_scoped(self):
        setup_logging(self.config_path)
        # Only the four dependency names are touched; unrelated loggers and
        # the MonitorHub app logger keep their default (NOTSET) level.
        for name in UNRELATED_LOGGERS:
            self.assertEqual(
                logging.getLogger(name).level,
                logging.NOTSET,
                f"unrelated logger {name} must not be silenced",
            )
        # The app's own logger is intentionally NOT floored, so a requested
        # --log-level DEBUG reaches the console and file handlers.
        self.assertEqual(logging.getLogger("MonitorHub").level, logging.NOTSET)
        # Child loggers inherit the WARNING floor through the logger hierarchy,
        # so a single setLevel on each top-level name covers all of them.
        self.assertEqual(
            logging.getLogger("botocore.credentials").getEffectiveLevel(),
            logging.WARNING,
        )
        self.assertEqual(
            logging.getLogger("urllib3.connectionpool").getEffectiveLevel(),
            logging.WARNING,
        )

    # --- dependency log level override (dependency_log_level) ---------------

    def test_dependency_log_level_overrides_default_floor(self):
        setup_logging(self.config_path, dependency_log_level="DEBUG")
        for name in DEPENDENCY_LOGGERS:
            self.assertEqual(
                logging.getLogger(name).level,
                logging.DEBUG,
                f"{name} should be raised to DEBUG via dependency_log_level",
            )
        # Child loggers inherit DEBUG through the logger hierarchy.
        self.assertEqual(
            logging.getLogger("botocore.credentials").getEffectiveLevel(),
            logging.DEBUG,
        )

    def test_dependency_log_level_env_var_respected(self):
        with mock.patch.dict(
            os.environ, {"MONITORHUB_DEPENDENCY_LOG_LEVEL": "DEBUG"}
        ):
            setup_logging(self.config_path)
        for name in DEPENDENCY_LOGGERS:
            self.assertEqual(
                logging.getLogger(name).level,
                logging.DEBUG,
                f"{name} should honour MONITORHUB_DEPENDENCY_LOG_LEVEL",
            )

    def test_dependency_log_level_argument_wins_over_env_var(self):
        with mock.patch.dict(
            os.environ, {"MONITORHUB_DEPENDENCY_LOG_LEVEL": "ERROR"}
        ):
            setup_logging(self.config_path, dependency_log_level="DEBUG")
        for name in DEPENDENCY_LOGGERS:
            self.assertEqual(logging.getLogger(name).level, logging.DEBUG)

    def test_dependency_log_level_is_scoped(self):
        setup_logging(self.config_path, dependency_log_level="DEBUG")
        for name in UNRELATED_LOGGERS:
            self.assertEqual(
                logging.getLogger(name).level,
                logging.NOTSET,
                f"unrelated logger {name} must not be changed",
            )
        # The app logger still honours the request --log-level, untouched by
        # the dependency override.
        self.assertEqual(logging.getLogger("MonitorHub").level, logging.NOTSET)

    def test_dependency_log_level_invalid_raises_value_error(self):
        with self.assertRaises(ValueError):
            setup_logging(self.config_path, dependency_log_level="VERBOSE")


if __name__ == "__main__":
    unittest.main()