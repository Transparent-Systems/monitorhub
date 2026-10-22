"""Headless Streamlit test for the web GUI home page."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

HOME_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "webgui" / "home.py"
)


class TestHomePage(unittest.TestCase):
    def test_home_page_shows_app_icon_and_title(self) -> None:
        at = AppTest.from_file(str(HOME_PATH), default_timeout=30)
        at.run()

        self.assertFalse(at.exception, at.exception)
        self.assertEqual([title.value for title in at.title], ["MonitorHub"])
        self.assertEqual(len(at.image), 1)
        self.assertEqual(
            [metric.label for metric in at.metric], ["Monitors", "Profiles"]
        )
        self.assertTrue(
            any(
                "github.com/Transparent-Systems/monitorhub" in markdown.value
                for markdown in at.markdown
            ),
            [markdown.value for markdown in at.markdown],
        )
        self.assertTrue(at.title[0].proto.hide_anchor)


if __name__ == "__main__":
    unittest.main()
