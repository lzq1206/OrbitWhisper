import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestAppJsRefresh(unittest.TestCase):
    def test_refresh_logic_detects_new_generated_at(self):
        project_root = Path(__file__).resolve().parents[1]
        app_js = project_root / "app.js"
        source = app_js.read_text(encoding="utf-8")

        self.assertRegex(
            source,
            re.compile(r"window\.__orbitwhisperCheckForReportUpdate\s*=\s*checkForReportUpdate\s*;"),
        )
        self.assertRegex(
            source,
            re.compile(r"if\s*\(\s*options\.dryRun\s*\)\s*return\s+true\s*;"),
        )
        self.assertRegex(
            source,
            re.compile(r"setInterval\s*\(\s*checkForReportUpdate\s*,\s*120000\s*\)\s*;"),
        )
        self.assertRegex(
            source,
            re.compile(r"const\s+EXTERNAL_ORBIT_FEED_POLL_MS\s*=\s*60000\s*;"),
        )
        self.assertRegex(
            source,
            re.compile(r"function\s+normalizeExternalOrbitPayload\s*\("),
        )
        self.assertRegex(
            source,
            re.compile(r"window\.__orbitwhisperRefreshExternalOrbitFeed\s*=\s*refreshExternalOrbitFeed\s*;"),
        )

    def test_engine_writes_data_under_root_data_dir(self):
        from src.engine.json_generator import generate_daily_outputs

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            data_dir.joinpath("latest_tles.json").write_text(
                json.dumps({"tles": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("src.engine.json_generator.run_engine") as run_engine_mock:
                run_engine_mock.return_value = data_dir / "daily_report.json"
                generate_daily_outputs(base_dir=Path(tmpdir))
                out_path = run_engine_mock.call_args.kwargs["output_path"]
                self.assertEqual(out_path, data_dir / "daily_report.json")


if __name__ == "__main__":
    unittest.main()
