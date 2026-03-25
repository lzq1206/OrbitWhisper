"""Generate static JSON artifacts for GitHub Pages frontend."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from src.engine.actuarial_model import compute_asset_pricing
from src.engine.collision_math import estimate_collision_events
from src.engine.data_pipeline import build_daily_dataset, save_pipeline_snapshot


def build_daily_report_dict(pipeline=None) -> dict:
    pipeline = pipeline or build_daily_dataset()
    collision_events = estimate_collision_events(pipeline.tle, pipeline.generated_at)
    pricing = compute_asset_pricing(pipeline.tle)

    report = {
        "project": "AstroQuant 3D",
        "generated_at": pipeline.generated_at,
        "data_sources": {
            "tle": "Space-Track/Celestrak placeholder feed",
            "space_weather": "NOAA placeholder feed",
            "maritime": "Maritime warning placeholder feed",
        },
        "high_risk_events": [asdict(event) for event in collision_events if event.miss_distance_km < 5.0],
        "collision_events": [asdict(event) for event in collision_events],
        "asset_pricing": [asdict(item) for item in pricing],
        "orbits": pipeline.tle[["asset_id", "name", "line1", "line2"]].to_dict(orient="records"),
    }
    return report


def generate_daily_outputs(base_dir: Path | None = None) -> Path:
    root = base_dir or Path.cwd()
    public_data_dir = root / "public" / "data"
    pipeline_dir = public_data_dir / "pipeline"
    report_path = public_data_dir / "daily_report.json"
    public_data_dir.mkdir(parents=True, exist_ok=True)
    pipeline = build_daily_dataset()
    save_pipeline_snapshot(pipeline, pipeline_dir)
    report = build_daily_report_dict(pipeline=pipeline)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    output = generate_daily_outputs()
    print(f"Generated {output}")
