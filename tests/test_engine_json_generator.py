import json
import tempfile
import unittest
from pathlib import Path

from src.engine.json_generator import generate_daily_outputs


class TestEngineJsonGenerator(unittest.TestCase):
    def test_generate_daily_outputs_writes_expected_report_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = generate_daily_outputs(base_dir=Path(tmpdir))
            self.assertTrue(report_path.exists())

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["project"], "AstroQuant 3D")
            self.assertIn("generated_at", payload)
            self.assertIn("collision_events", payload)
            self.assertIn("asset_pricing", payload)
            self.assertIn("orbits", payload)
            self.assertGreaterEqual(len(payload["orbits"]), 1)


if __name__ == "__main__":
    unittest.main()

