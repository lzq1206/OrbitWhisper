"""Daily ETL pipeline for AstroQuant 3D static report generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


@dataclass
class PipelineOutput:
    """Container for ETL outputs used by downstream compute modules."""

    tle: pd.DataFrame
    space_weather: pd.DataFrame
    maritime_notices: pd.DataFrame
    generated_at: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_daily_dataset() -> PipelineOutput:
    """Build deterministic placeholder dataset.

    The scaffold uses in-repo synthetic data so GitHub Actions can run without
    external credentials. Real connectors can replace these stubs later.
    """

    generated_at = _utc_now_iso()
    tle = pd.DataFrame(
        [
            {
                "asset_id": "AQ-1001",
                "name": "ORBITWHISPER-DEMO-1",
                "line1": "1 25544U 98067A   24001.10000000  .00014266  00000+0  26094-3 0  9994",
                "line2": "2 25544  51.6416  13.3500 0005001 130.5360 289.5733 15.49938556439616",
            },
            {
                "asset_id": "AQ-1002",
                "name": "ORBITWHISPER-DEMO-2",
                "line1": "1 40967U 15058A   24001.30000000  .00000054  00000+0  00000+0 0  9996",
                "line2": "2 40967   0.0172  88.2052 0002089 205.2228 262.0058  1.00270765 30287",
            },
        ]
    )
    space_weather = pd.DataFrame(
        [
            {"date": generated_at[:10], "f107": 129.4, "kp_index": 3.0},
        ]
    )
    maritime_notices = pd.DataFrame(
        [
            {
                "notice_id": "NAV-001",
                "region": "South China Sea",
                "risk_score": 0.35,
                "valid_from": generated_at,
            }
        ]
    )
    return PipelineOutput(
        tle=tle,
        space_weather=space_weather,
        maritime_notices=maritime_notices,
        generated_at=generated_at,
    )


def save_pipeline_snapshot(output: PipelineOutput, out_dir: Path) -> None:
    """Persist ETL snapshot files for traceability in CI."""

    out_dir.mkdir(parents=True, exist_ok=True)
    output.tle.to_json(out_dir / "tle.json", orient="records", indent=2)
    output.space_weather.to_json(out_dir / "space_weather.json", orient="records", indent=2)
    output.maritime_notices.to_json(out_dir / "maritime_notices.json", orient="records", indent=2)

