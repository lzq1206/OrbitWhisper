import io
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from src.api.main import _reset_state_for_tests, app


class TestOpticalApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "satellites_test.db"
        _reset_state_for_tests(self.db_path)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @staticmethod
    def _png_bytes(value: int = 0) -> bytes:
        img = Image.new("L", (16, 16), color=value)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_upload_tle_and_search(self):
        tle_text = (
            "ISS\n"
            "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994\n"
            "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823"
        )
        resp = self.client.post("/api/upload_tle", json={"tle_text": tle_text})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("satellite", payload)

        q = payload["satellite"]["name"][:3]
        search = self.client.get(f"/api/satellites/search?q={q}")
        self.assertEqual(search.status_code, 200)
        self.assertGreaterEqual(len(search.json()["results"]), 1)

    def test_upload_tle_rejects_duplicate_by_catalog_id_and_returns_orbit_preview(self):
        tle_text = (
            "ISS\n"
            "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994\n"
            "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823"
        )
        first = self.client.post("/api/upload_tle", json={"tle_text": tle_text, "name": "ISS-A"})
        self.assertEqual(first.status_code, 200)
        first_payload = first.json()
        self.assertFalse(first_payload["duplicate"])
        self.assertIn("orbit", first_payload)

        dup = self.client.post("/api/upload_tle", json={"tle_text": tle_text, "name": "ISS-B"})
        self.assertEqual(dup.status_code, 200)
        dup_payload = dup.json()
        self.assertTrue(dup_payload["duplicate"])
        self.assertEqual(dup_payload["satellite"]["name"], "ISS-A")
        self.assertIn("orbit", dup_payload)

    def test_upload_tle_accepts_extra_header_lines(self):
        tle_text = (
            "Downloaded from CelesTrak\n"
            "ISS (ZARYA)\n"
            "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994\n"
            "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823\n"
        )
        resp = self.client.post("/api/upload_tle", json={"tle_text": tle_text})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["satellite"]["name"], "ISS (ZARYA)")

    def test_name_binding_roundtrip(self):
        bind = self.client.post("/api/satellites/name", json={"temp_id": "UNKN-2026-A", "custom_name": "Astro-X1"})
        self.assertEqual(bind.status_code, 200)

        search = self.client.get("/api/satellites/search?q=Astro-X1")
        self.assertEqual(search.status_code, 200)
        names = [item["name"] for item in search.json()["results"]]
        self.assertIn("Astro-X1", names)

    def test_upload_image_returns_frame_payload(self):
        image_bytes = self._png_bytes(0)
        resp = self.client.post(
            "/api/upload_image",
            files=[("files", ("obs1.png", image_bytes, "image/png"))],
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("frames", payload)
        self.assertEqual(len(payload["frames"]), 1)
        self.assertIn("iod_result", payload)


if __name__ == "__main__":
    unittest.main()
