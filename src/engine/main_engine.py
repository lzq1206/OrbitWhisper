"""AstroQuant 后端主入口：串联碰撞与精算并导出前端 JSON。"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.engine.data_pipeline import build_daily_dataset


def _premium_var(prices: list[float]) -> str:
    if not prices:
        return "+0.0%"
    avg_price = sum(prices) / len(prices)
    baseline = 50_000.0
    pct = (avg_price - baseline) / baseline * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


# ── Category color mapping ──────────────────────────────────────────────────
CATEGORY_COLORS = {
    "空间站与特殊兴趣": "#ff6600",
    "气象与地球资源": "#00ccff",
    "通信卫星": "#ffcc00",
    "导航卫星": "#00ff88",
    "科学卫星": "#cc44ff",
    "其他": "#888888",
    "大型星座": "#4488ff",
}


def _build_satellite_payload_real(dataset):
    """Build payload from real CelesTrak satellite data (no collision calc for large sets)."""
    satellites = []
    orbits = []
    high_risk_events = []
    asset_pricing = []
    high_risk_count = 0

    for i, sat in enumerate(dataset.satellites):
        sat_id = str(sat.norad_id)
        color = CATEGORY_COLORS.get(sat.category, "#00ffcc")
        alt_display = sat.alt / 1000.0 if sat.alt > 100 else sat.alt  # Normalize altitude

        satellites.append({
            "id": sat_id,
            "name": sat.name,
            "norad_id": sat.norad_id,
            "category": sat.category,
            "lat": round(sat.lat, 6),
            "lng": round(sat.lng, 6),
            "alt": round(alt_display, 6),
            "radius": 0.5,
            "color": color,
            "is_high_risk": False,
            "pof": 0.0,
            "suggested_premium": 0.0,
        })

        orbits.append({
            "asset_id": sat_id,
            "name": sat.name,
            "norad_id": sat.norad_id,
            "category": sat.category,
            "lat": round(sat.lat, 6),
            "lng": round(sat.lng, 6),
            "alt": round(alt_display, 6),
        })

        # Simplified pricing for real satellites
        pof = max(0.01, 0.35 - (i % 20) * 0.01)
        premium = pof * (50_000_000.0 + (i % 10) * 8_000_000.0) * 0.35 * 1.25
        asset_pricing.append({
            "asset_id": sat_id,
            "name": sat.name,
            "pof_12m": round(pof, 6),
            "expected_loss": round(pof * 50_000_000.0 * 0.35, 2),
            "pure_premium": round(premium, 2),
            "survival_curve": [
                {"timeline_days": day, "survival_prob": round(math.exp(-pof * day / 365.0), 6)}
                for day in (0, 30, 90, 180, 270, 365)
            ],
        })

    # Category statistics
    category_stats = {}
    for sat in dataset.satellites:
        cat = sat.category
        if cat not in category_stats:
            category_stats[cat] = 0
        category_stats[cat] += 1

    return satellites, high_risk_count, orbits, high_risk_events, asset_pricing, category_stats


def _build_satellite_payload_simulated(dataset, pricing_results):
    """Build payload from simulated data (legacy mode with collision analysis)."""
    from src.engine.collision_math import OrbitalPropagator

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
            alt = float(latest["alt"]) / 1000.0

        peer_id = sat_ids[(idx + 1) % len(sat_ids)]
        tca = propagator.calculate_tca(track, tracks[peer_id])
        is_high_risk = tca["risk_level"] == "High Risk"
        if is_high_risk:
            high_risk_count += 1

        price = pricing_map.get(sat_id)
        pof = float(price.pof_12m) if price else 0.0
        premium = float(price.pure_premium) if price else 0.0

        satellites.append({
            "id": sat_id,
            "name": sat_id,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "alt": round(alt, 6),
            "radius": 0.8 if is_high_risk else 0.5,
            "color": "#ff0044" if is_high_risk else "#00ffcc",
            "is_high_risk": is_high_risk,
            "pof": round(pof, 6),
            "suggested_premium": round(premium, 2),
        })

        orbits.append({
            "asset_id": sat_id,
            "name": sat_id,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "alt": round(alt, 6),
        })

        if is_high_risk:
            high_risk_events.append({
                "asset_id": sat_id,
                "counterpart_id": peer_id,
                "tca_utc": tca["tca"].replace(microsecond=0).isoformat() if tca["tca"] is not None else None,
                "miss_distance_km": round(float(tca["min_distance_km"]), 6),
                "poc": round(float(tca["poc"]), 8),
            })

        asset_pricing.append({
            "asset_id": sat_id,
            "pof_12m": round(pof, 6),
            "expected_loss": round(float(price.expected_loss), 2) if price else 0.0,
            "pure_premium": round(premium, 2),
            "survival_curve": [
                {"timeline_days": day, "survival_prob": round(math.exp(-pof * day / 365.0), 6)}
                for day in (0, 30, 90, 180, 270, 365)
            ],
        })

    return satellites, high_risk_count, orbits, high_risk_events, asset_pricing, {}


def run_engine(output_path: Path | None = None) -> Path:
    """执行全流程并输出 JSON 报告。"""

    final_path = output_path or (Path.cwd() / "data" / "daily_report.json")
    latest_tles_path = final_path.parent / "latest_tles.json"
    satellites_path = final_path.parent / "satellites.json"

    dataset = build_daily_dataset(
        count=300,
        real_tles_path=latest_tles_path,
        satellites_path=satellites_path,
    )

    if dataset.use_real_data:
        print(f"Using real satellite data: {len(dataset.satellites)} satellites from CelesTrak")
        satellites, high_risk_count, orbits, high_risk_events, asset_pricing, category_stats = (
            _build_satellite_payload_real(dataset)
        )
    else:
        print("No real satellite data found, using simulated data")
        from src.engine.actuarial_model import compute_asset_pricing
        pricing_results, _ = compute_asset_pricing(dataset.finance)
        satellites, high_risk_count, orbits, high_risk_events, asset_pricing, category_stats = (
            _build_satellite_payload_simulated(dataset, pricing_results)
        )

    status_text = "空间天气平稳"
    if dataset.weather["is_geomagnetic_storm"] >= 1:
        status_text = "地磁暴警报：所有低轨资产阻力飙升"
    elif dataset.use_real_data:
        status_text = f"实时监控中 | {len(satellites)} 颗卫星在轨"

    report = {
        "generated_at": dataset.generated_at,
        "hud_data": {
            "status": status_text,
            "high_risk_count": high_risk_count,
            "total_premium_var": _premium_var([s["suggested_premium"] for s in satellites]),
            "update_time": dataset.generated_at,
            "satellite_count": len(satellites),
            "category_stats": category_stats,
        },
        "satellites": satellites,
        "orbits": orbits,
        "high_risk_events": high_risk_events,
        "asset_pricing": asset_pricing[:100],  # Limit pricing output for large datasets
    }

    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_path


if __name__ == "__main__":
    output = run_engine()
    print(f"已生成报告: {output}")
