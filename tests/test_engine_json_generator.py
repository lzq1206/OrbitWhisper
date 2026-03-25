import json
import tempfile
import unittest
from pathlib import Path

from src.engine.json_generator import generate_daily_outputs


SATELLITE_COUNT = 300


class TestEngineJsonGenerator(unittest.TestCase):
    def test_generate_daily_outputs_writes_required_hud_and_satellite_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            data_dir.joinpath("latest_tles.json").write_text(
                json.dumps(
                    {
                        "tles": [
                            {
                                "line1": "1 25544U 98067A   24001.10000000  .00014266  00000+0  26094-3 0  9994",
                                "line2": "2 25544  51.6416  13.3500 0005001 130.5360 289.5733 15.49938556439616",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report_path = generate_daily_outputs(base_dir=Path(tmpdir))
            self.assertTrue(report_path.exists())

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(payload.keys()),
                {"generated_at", "hud_data", "satellites", "orbits", "high_risk_events", "asset_pricing"},
            )

            hud = payload["hud_data"]
            self.assertIn(hud["status"], {"空间天气平稳", "地磁暴警报：所有低轨资产阻力飙升"})
            self.assertIn("high_risk_count", hud)
            self.assertIn("total_premium_var", hud)
            self.assertIn("update_time", hud)

            satellites = payload["satellites"]
            self.assertEqual(len(satellites), SATELLITE_COUNT)
            first = satellites[0]
            self.assertEqual(
                set(first.keys()),
                {"id", "lat", "lng", "alt", "radius", "color", "pof", "suggested_premium"},
            )
            self.assertIn(first["color"], {"#00ffcc", "#ff0044"})
            self.assertEqual(len(payload["orbits"]), SATELLITE_COUNT)
            self.assertEqual(
                set(payload["asset_pricing"][0].keys()),
                {"asset_id", "pof_12m", "expected_loss", "pure_premium", "survival_curve"},
            )
            self.assertEqual(
                set(payload["asset_pricing"][0]["survival_curve"][0].keys()),
                {"timeline_days", "survival_prob"},
            )


if __name__ == "__main__":
    unittest.main()
