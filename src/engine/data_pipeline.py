"""模拟数据管道：构建 300 颗卫星的轨道与精算输入数据。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


BASE_TLES = [
    (
        "1 25544U 98067A   24001.10000000  .00014266  00000+0  26094-3 0  9994",
        "2 25544  51.6416  13.3500 0005001 130.5360 289.5733 15.49938556439616",
    ),
    (
        "1 40967U 15058A   24001.30000000  .00000054  00000+0  00000+0 0  9996",
        "2 40967   0.0172  88.2052 0002089 205.2228 262.0058  1.00270765 30287",
    ),
]


@dataclass
class PipelineOutput:
    tle: pd.DataFrame
    finance: pd.DataFrame
    generated_at: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_daily_dataset(count: int = 300) -> PipelineOutput:
    """生成模拟输入数据。"""

    if count <= 0:
        raise ValueError("count 必须大于 0")

    generated_at = _utc_now_iso()

    tle_rows = []
    fin_rows = []
    for i in range(count):
        sat_id = f"SAT-{i + 1:03d}"
        line1, line2 = BASE_TLES[i % len(BASE_TLES)]

        # 轻微扰动，确保样本多样性
        solar_base = 95.0 + (i % 25) * 0.9
        kp_base = 1.5 + (i % 8) * 0.4
        age_years = 0.5 + (i % 12) * 0.4
        health = max(0.1, 0.98 - (i % 20) * 0.02)

        tle_rows.append({"id": sat_id, "line1": line1, "line2": line2})
        fin_rows.append(
            {
                "id": sat_id,
                "duration_days": 90 + (i % 240),
                "event_observed": 1 if (i % 11 == 0 or health < 0.45) else 0,
                "f107": solar_base,
                "kp_index": kp_base,
                "solar_wind_index": solar_base * 0.92 + 3.0,  # 人为构造共线因子
                "asset_age_years": age_years,
                "health_score": health,
                "exposure_amount": 50_000_000.0 + (i % 10) * 8_000_000.0,
                "lgf": 0.35 + (i % 6) * 0.07,
            }
        )

    tle_df = pd.DataFrame(tle_rows)
    finance_df = pd.DataFrame(fin_rows)

    return PipelineOutput(tle=tle_df, finance=finance_df, generated_at=generated_at)


def save_pipeline_snapshot(output: PipelineOutput, out_dir: Path) -> None:
    """保存每日数据快照，便于 CI 或回溯分析。"""

    out_dir.mkdir(parents=True, exist_ok=True)
    output.tle.to_json(out_dir / "tle.json", orient="records", indent=2)
    output.finance.to_json(out_dir / "finance.json", orient="records", indent=2)
