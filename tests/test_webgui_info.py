"""Headless Streamlit tests for the Info page."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

PAGE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "webgui" / "pages" / "info.py"
)


class TestInfoPage(unittest.TestCase):
    def test_renders_readme(self) -> None:
        at = AppTest.from_file(str(PAGE_PATH), default_timeout=30)
        at.run()

        self.assertFalse(at.exception, at.exception)
        markdown = "\n".join(element.value for element in at.markdown)
        self.assertIn("# Monitor Hub", markdown)
        self.assertIn("Quick Start", markdown)

    def test_missing_readme_shows_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.utils.project_paths.resource_root", return_value=Path(temp_dir)
        ):
            at = AppTest.from_file(str(PAGE_PATH), default_timeout=30)
            at.run()

        self.assertFalse(at.exception, at.exception)
        errors = [error.value for error in at.error]
        self.assertTrue(any("README.md" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
