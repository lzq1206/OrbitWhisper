"""AstroQuant 后端主入口：串联碰撞与精算并导出前端 JSON。"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    # 兼容直接执行：python src/engine/main_engine.py
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.engine.actuarial_model import compute_asset_pricing
from src.engine.collision_math import OrbitalPropagator
from src.engine.data_pipeline import build_daily_dataset


def _premium_var(prices: list[float]) -> str:
    if not prices:
        return "+0.0%"
    avg_price = sum(prices) / len(prices)
    baseline = 50_000.0
    pct = (avg_price - baseline) / baseline * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _build_satellite_payload(dataset, pricing_results):
    pricing_map = {item.asset_id: item for item in pricing_results}
    propagator = OrbitalPropagator(step_minutes=30)

    satellites = []
    orbits = []
    high_risk_events = []
    asset_pricing = []
    high_risk_count = 0

    tle_df = dataset.tle.reset_index(drop=True)

    tracks = {}
    for _, row in tle_df.iterrows():
        sat_id = row["id"]
        tracks[sat_id] = propagator.propagate_tle(
            line1=row["line1"],
            line2=row["line2"],
            start_time=dataset.generated_at,
            horizon_hours=24,
            step_minutes=30,
        )

    sat_ids = list(tracks.keys())
    for idx, sat_id in enumerate(sat_ids):
        track = tracks[sat_id]
        if track.empty:
            lat = lng = alt = 0.0
        else:
            latest = track.iloc[-1]
            lat = float(latest["lat"])
            lng = float(latest["lng"])
            alt = float(latest["alt"]) / 1000.0  # km -> 千公里，匹配前端缩放

        peer_id = sat_ids[(idx + 1) % len(sat_ids)]
        tca = propagator.calculate_tca(track, tracks[peer_id])
        is_high_risk = tca["risk_level"] == "High Risk"
        if is_high_risk:
            high_risk_count += 1

        price = pricing_map.get(sat_id)
        pof = float(price.pof_12m) if price else 0.0
        premium = float(price.pure_premium) if price else 0.0

        satellites.append(
            {
                "id": sat_id,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "alt": round(alt, 6),
                "radius": 0.8 if is_high_risk else 0.5,
                "color": "#ff0044" if is_high_risk else "#00ffcc",
                "pof": round(pof, 6),
                "suggested_premium": round(premium, 2),
            }
        )

        orbits.append(
            {
                "asset_id": sat_id,
                "name": sat_id,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "alt": round(alt, 6),
            }
        )

        if is_high_risk:
            high_risk_events.append(
                {
                    "asset_id": sat_id,
                    "counterpart_id": peer_id,
                    "tca_utc": tca["tca"].replace(microsecond=0).isoformat() if tca["tca"] is not None else None,
                    "miss_distance_km": round(float(tca["min_distance_km"]), 6),
                    "poc": round(float(tca["poc"]), 8),
                }
            )

        asset_pricing.append(
            {
                "asset_id": sat_id,
                "pof_12m": round(pof, 6),
                "expected_loss": round(float(price.expected_loss), 2) if price else 0.0,
                "pure_premium": round(premium, 2),
                "survival_curve": [
                    {"timeline_days": day, "survival_prob": round(math.exp(-pof * day / 365.0), 6)}
                    for day in (0, 30, 90, 180, 270, 365)
                ],
            }
        )

    return satellites, high_risk_count, orbits, high_risk_events, asset_pricing


def run_engine(output_path: Path | None = None) -> Path:
    """执行全流程并输出 JSON 报告。"""

    final_path = output_path or (Path.cwd() / "data" / "daily_report.json")
    latest_tles_path = final_path.parent / "latest_tles.json"

    dataset = build_daily_dataset(count=300, real_tles_path=latest_tles_path)
    pricing_results, _ = compute_asset_pricing(dataset.finance)
    satellites, high_risk_count, orbits, high_risk_events, asset_pricing = _build_satellite_payload(dataset, pricing_results)

    report = {
        "generated_at": dataset.generated_at,
        "hud_data": {
            "status": "地磁暴警报：所有低轨资产阻力飙升" if dataset.weather["is_geomagnetic_storm"] >= 1 else "空间天气平稳",
            "high_risk_count": high_risk_count,
            "total_premium_var": _premium_var([s["suggested_premium"] for s in satellites]),
            "update_time": dataset.generated_at,
        },
        "satellites": satellites,
        "orbits": orbits,
        "high_risk_events": high_risk_events,
        "asset_pricing": asset_pricing,
    }

    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_path


if __name__ == "__main__":
    output = run_engine()
    print(f"已生成报告: {output}")
