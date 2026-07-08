from __future__ import annotations

import unittest
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "fanout_live" / "web" / "static"


class WebStaticTests(unittest.TestCase):
    def test_bitrate_ui_always_formats_kbps(self) -> None:
        app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("return `${Math.round(value)} kbps`;", app_js)
        self.assertNotIn("Mbps", app_js)
        self.assertNotIn("mbps", app_js)

    def test_bitrate_graph_uses_one_second_30_second_window(self) -> None:
        app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("const BITRATE_GRAPH_SECONDS = 30;", app_js)
        self.assertIn("const BITRATE_GRAPH_POINTS = 30;", app_js)
        self.assertIn("setInterval(refreshStatus, 1000)", app_js)


if __name__ == "__main__":
    unittest.main()
