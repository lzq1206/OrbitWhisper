import re
import unittest
from pathlib import Path


class TestIndexHtmlUi(unittest.TestCase):
    def setUp(self) -> None:
        self.project_root = Path(__file__).resolve().parents[1]
        self.index_html = (self.project_root / "index.html").read_text(encoding="utf-8")

    def test_upload_uses_api_fetch_fallback(self):
        self.assertRegex(self.index_html, re.compile(r"async function apiFetch\("))
        self.assertRegex(self.index_html, re.compile(r"await apiFetch\('/api/upload_tle'"))
        self.assertRegex(self.index_html, re.compile(r"await apiFetch\('/api/upload_image'"))
        self.assertRegex(self.index_html, re.compile(r"function bindClickUpload\("))
        self.assertIn('id="tleUploadBtn"', self.index_html)
        self.assertIn('id="imageUploadBtn"', self.index_html)
        self.assertRegex(self.index_html, re.compile(r"bindClickUpload\('tleUploadBtn',\s*'tleFileInput'"))
        self.assertRegex(self.index_html, re.compile(r"bindClickUpload\('imageUploadBtn',\s*'imageFileInput'"))

    def test_modal_overlay_uses_fixed_position(self):
        self.assertRegex(
            self.index_html,
            re.compile(r"#namingModal\s*\{[^}]*position:\s*fixed;", re.DOTALL),
        )

    def test_window_toggle_controls_exist_for_all_panels(self):
        self.assertIn('data-target="hud"', self.index_html)
        self.assertIn('data-target="controlPanel"', self.index_html)
        self.assertIn('data-target="chartPanel"', self.index_html)
        self.assertRegex(
            self.index_html,
            re.compile(r"windowToggleButtons\.forEach\(btn => \{"),
        )


if __name__ == "__main__":
    unittest.main()
