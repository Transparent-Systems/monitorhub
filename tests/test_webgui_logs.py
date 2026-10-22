"""Headless Streamlit tests for the monitor logs page."""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.utils.constants import MONITOR_STATUS_STOPPED
from app.utils.sqlite_handler import SQLiteHandler

PAGE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "webgui" / "pages" / "logs.py"
)

logger = logging.getLogger("test.webgui.logs")
logger.addHandler(logging.NullHandler())
logger.setLevel(logging.CRITICAL)


class TestLogsPage(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.db_dir = str(self.root / "db")
        Path(self.db_dir).mkdir()
        self.log_dir = self.root / "logs"
        self.log_dir.mkdir()

        # Keep these patches active for the whole test: the auto-refresh
        # fragment can re-run after at.run() returns.
        self._root_patcher = patch(
            "app.monitor.monitor_process_manager.project_root",
            return_value=self.root,
        )
        self._root_patcher.start()
        self._db_patcher = patch(
            "app.utils.app_config.AppConfig.get_default_db_dir",
            return_value=self.db_dir,
        )
        self._db_patcher.start()

        self.sqlite_handler = SQLiteHandler(logger=logger, db_dir=self.db_dir)
        self.sqlite_handler.create_schema()

    def tearDown(self) -> None:
        self.sqlite_handler.close()
        self._db_patcher.stop()
        self._root_patcher.stop()
        self._temp_dir.cleanup()

    def _add_monitor(self, name: str) -> int:
        monitor_id = self.sqlite_handler.add_monitor(
            name=name,
            monitor_path=self.db_dir,
            remote_path="remote:destination",
            monitor_type="instant",
            config={},
            status=MONITOR_STATUS_STOPPED,
            pid=0,
        )
        self.assertIsNotNone(monitor_id)
        return int(monitor_id)

    def _write_log(self, monitor_id: int, text: str) -> Path:
        path = self.log_dir / f"monitor_{monitor_id}.log"
        path.write_text(text, encoding="utf-8")
        return path

    def _run_page(self) -> AppTest:
        at = AppTest.from_file(str(PAGE_PATH), default_timeout=30)
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    @staticmethod
    def _selectbox(at: AppTest, label: str):
        matches = [widget for widget in at.selectbox if widget.label == label]
        assert len(matches) == 1, (label, [(w.label, w.value) for w in at.selectbox])
        return matches[0]

    @staticmethod
    def _code_text(at: AppTest) -> str:
        assert at.code, "no code block rendered"
        return at.code[0].value

    def test_renders_selected_monitor_log_and_auto_refresh_default(self) -> None:
        monitor_id = self._add_monitor("Alpha")
        self._write_log(monitor_id, "alpha line 1\nalpha line 2\n")

        at = self._run_page()
        self.assertEqual(self._selectbox(at, "Monitor").value, f"{monitor_id}: Alpha")
        self.assertEqual(self._selectbox(at, "Auto-refresh").value, "2 seconds")
        self.assertIn("alpha line 2", self._code_text(at))

    def test_selecting_another_monitor_switches_the_log(self) -> None:
        first = self._add_monitor("Alpha")
        second = self._add_monitor("Beta")
        self._write_log(first, "alpha log\n")
        self._write_log(second, "beta log\n")

        at = self._run_page()
        self._selectbox(at, "Monitor").select(f"{second}: Beta").run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("beta log", self._code_text(at))
        self.assertNotIn("alpha log", self._code_text(at))

    def test_missing_log_shows_expected_path(self) -> None:
        monitor_id = self._add_monitor("Alpha")
        at = self._run_page()
        infos = [info.value for info in at.info]
        self.assertTrue(any("No log file yet" in info for info in infos), infos)
        self.assertTrue(
            any(
                f"monitor_{monitor_id}.log" in caption.value
                for caption in at.caption
            ),
            [caption.value for caption in at.caption],
        )

    def test_empty_log_is_reported(self) -> None:
        monitor_id = self._add_monitor("Alpha")
        self._write_log(monitor_id, "")
        at = self._run_page()
        infos = [info.value for info in at.info]
        self.assertTrue(any("empty" in info for info in infos), infos)

    def test_refresh_reloads_the_log(self) -> None:
        monitor_id = self._add_monitor("Alpha")
        self._write_log(monitor_id, "first line\n")
        at = self._run_page()
        self.assertIn("first line", self._code_text(at))

        self._write_log(monitor_id, "first line\nsecond line\n")
        refresh = [button for button in at.button if button.label == "↻ Refresh"]
        self.assertEqual(len(refresh), 1)
        refresh[0].click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("second line", self._code_text(at))

    def test_no_monitors_shows_info(self) -> None:
        at = self._run_page()
        infos = [info.value for info in at.info]
        self.assertTrue(any("No monitors yet" in info for info in infos), infos)


class TestLogsPageUninitialisedDatabase(unittest.TestCase):
    """An uninitialised database must not surface as a raw traceback."""

    def test_friendly_error_instead_of_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_dir = root / "db"
            db_dir.mkdir()
            with patch(
                "app.utils.app_config.AppConfig.get_default_db_dir",
                return_value=str(db_dir),
            ), patch(
                "app.monitor.monitor_process_manager.project_root",
                return_value=root,
            ):
                at = AppTest.from_file(str(PAGE_PATH), default_timeout=30)
                at.run()

        self.assertFalse(at.exception, at.exception)
        errors = [error.value for error in at.error]
        self.assertTrue(
            any("not initialised" in error for error in errors), errors
        )
        self.assertTrue(any("database init" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
