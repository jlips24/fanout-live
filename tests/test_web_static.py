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

    def test_pipeline_panel_ui_is_shipped(self) -> None:
        index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        styles_css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn("Stream Manager", index_html)
        self.assertIn('id="manager-panels"', index_html)
        self.assertIn('id="panel-row-template"', index_html)
        self.assertNotIn('class="panel-width"', index_html)
        self.assertIn("renderStreamManager", app_js)
        self.assertIn("20260711-stream-manager-v14", index_html)
        self.assertIn("stream-manager-v14", app_js)
        self.assertIn('id="manager-preview-toggle"', index_html)
        self.assertIn('id="panel-layout-toggle"', index_html)
        self.assertIn('class="panel-enabled"', index_html)
        self.assertIn("manager-pipeline-chip", app_js)
        self.assertIn("panel.enabled", app_js)
        self.assertIn("manager-panel-resize", app_js)
        self.assertNotIn("manager-panel-resize-nw", app_js)
        self.assertIn("startPanelMove", app_js)
        self.assertIn("movePanelDuringPointer", app_js)
        self.assertIn("panelElementAtPoint", app_js)
        self.assertIn("panelElementByKey", app_js)
        self.assertIn("startPanelResize", app_js)
        self.assertIn("syncPanelSettingsFromConfig", app_js)
        self.assertIn("PANEL_GRID_COLUMNS", app_js)
        self.assertIn("PANEL_GRID_MAX_ROWS = 6", app_js)
        self.assertIn("setManagerPreviewCollapsed", app_js)
        self.assertIn("isPageActive", app_js)
        self.assertIn('isPageActive("stream-manager") && !managerPreviewCollapsed', app_js)
        self.assertIn("MANAGER_PREVIEW_COLLAPSED_KEY", app_js)
        self.assertIn('fields.managerPreviewImage.removeAttribute("src")', app_js)
        self.assertIn("normalizePanelEmbedUrl", app_js)
        self.assertIn("normalizePanelUrlScheme", app_js)
        self.assertIn("return `https://${url}`;", app_js)
        self.assertIn('url.searchParams.set("parent", window.location.hostname)', app_js)
        self.assertIn('url.searchParams.set("darkpopout", "1")', app_js)
        self.assertIn("normalizeYoutubeChatUrl", app_js)
        self.assertIn('url.pathname = "/live_chat";', app_js)
        self.assertIn('url.searchParams.set("embed_domain", window.location.hostname)', app_js)
        self.assertIn("renderManagerPipelineCards(status)", app_js)
        self.assertNotIn("renderStreamManager(status)", app_js)
        self.assertIn("grid-auto-rows: 210px;", styles_css)
        self.assertIn("grid-column: span var(--panel-columns, 6);", styles_css)
        self.assertIn("grid-row: span var(--panel-rows, 4);", styles_css)
        self.assertIn("padding-bottom: 260px;", styles_css)
        self.assertIn(".manager-panel-body", styles_css)
        self.assertIn("padding-bottom: 10px;", styles_css)
        self.assertIn("opacity: 1;", styles_css)
        self.assertIn("pointer-events: none;", styles_css)
        self.assertIn("touch-action: none;", styles_css)
        self.assertIn("display: block;", styles_css)
        self.assertIn("min-height: 0;", styles_css)
        self.assertNotIn("grid-template-rows: auto 630px;", styles_css)
        self.assertNotIn("max-height: 630px;", styles_css)
        self.assertNotIn(".manager-panel-resize-nw", styles_css)
        self.assertIn(".manager-preview-toolbar", styles_css)
        self.assertIn("background: var(--panel-strong);", styles_css)
        self.assertIn("border-bottom: 1px solid var(--line);", styles_css)
        self.assertIn("border: 0;", styles_css)


if __name__ == "__main__":
    unittest.main()
