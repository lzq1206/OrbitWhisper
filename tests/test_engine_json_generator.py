import json
import tempfile
import unittest
from pathlib import Path

from src.engine.json_generator import generate_daily_outputs


class TestEngineJsonGenerator(unittest.TestCase):
    def test_generate_daily_outputs_writes_required_hud_and_satellite_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = generate_daily_outputs(base_dir=Path(tmpdir))
            self.assertTrue(report_path.exists())

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(set(payload.keys()), {"hud_data", "satellites"})

            hud = payload["hud_data"]
            self.assertEqual(hud["status"], "风险监控中")
            self.assertIn("high_risk_count", hud)
            self.assertIn("total_premium_var", hud)

            satellites = payload["satellites"]
            self.assertEqual(len(satellites), 300)
            first = satellites[0]
            self.assertEqual(
                set(first.keys()),
                {"id", "lat", "lng", "alt", "radius", "color", "pof", "suggested_premium"},
            )
            self.assertIn(first["color"], {"#00ffcc", "#ff0044"})


if __name__ == "__main__":
    unittest.main()
