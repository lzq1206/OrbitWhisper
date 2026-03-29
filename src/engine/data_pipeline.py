"""数据管道：优先使用 CelesTrak 真实卫星数据，回退到模拟数据。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

NOAA_F107_URL = "https://services.swpc.noaa.gov/products/summary/10cm-flux.json"
NOAA_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"

# Fallback TLEs when no real data available
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
class SatelliteRecord:
    """Record for a single satellite with TLE and metadata."""
    id: str
    name: str
    norad_id: int
    category: str
    status: str
    line1: str
    line2: str
    lat: float
    lng: float
    alt: float  # in km
    epoch: str = ""


@dataclass
class PipelineOutput:
    tle: pd.DataFrame
    finance: pd.DataFrame
    generated_at: str
    weather: dict[str, float]
    satellites: list[SatelliteRecord] = field(default_factory=list)
    use_real_data: bool = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_real_satellites(path: Path) -> list[SatelliteRecord]:
    """Load real satellite data from data/satellites.json."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    items = payload.get("satellites", []) if isinstance(payload, dict) else []
    records: list[SatelliteRecord] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        norad_id = item.get("norad_id", 0)
        name = item.get("name", f"SAT-{norad_id}")
        category = item.get("category", "其他")
        status = item.get("status", "active")
        line1 = str(item.get("line1", "")).strip()
        line2 = str(item.get("line2", "")).strip()
        lat = float(item.get("lat", 0))
        lng = float(item.get("lng", 0))
        alt = float(item.get("alt", 550))
        epoch = item.get("epoch", "")

        if not line1.startswith("1 ") or not line2.startswith("2 "):
            continue

        records.append(SatelliteRecord(
            id=str(norad_id),
            name=name,
            norad_id=norad_id,
            category=category,
            status=status,
            line1=line1,
            line2=line2,
            lat=lat,
            lng=lng,
            alt=alt,
            epoch=epoch,
        ))

    return records


def _load_legacy_tles(path: Path | None) -> list[tuple[str, str]]:
    """Load TLEs from legacy latest_tles.json format."""
    if path is None or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    items = payload.get("tles", []) if isinstance(payload, dict) else []
    parsed: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        line1 = str(item.get("line1", "")).strip()
        line2 = str(item.get("line2", "")).strip()
        if line1.startswith("1 ") and line2.startswith("2 "):
            parsed.append((line1, line2))
    return parsed


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fetch_space_weather() -> dict[str, float]:
    """Fetch NOAA F10.7/Kp values and return normalized weather features."""
    f107 = 90.0
    kp = 2.0

    try:
        resp = requests.get(NOAA_F107_URL, timeout=3)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            f107 = _safe_float(payload.get("flux"), f107)
    except (requests.RequestException, ValueError):
        pass

    try:
        resp = requests.get(NOAA_KP_URL, timeout=3)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, list) and len(payload) > 1:
            last_entry = payload[-1]
            if isinstance(last_entry, list) and len(last_entry) >= 2:
                kp = _safe_float(last_entry[1], kp)
    except (requests.RequestException, ValueError):
        pass

    return {
        "f107": f107,
        "kp_index": kp,
        "is_geomagnetic_storm": 1.0 if kp >= 5.0 else 0.0,
    }


def build_daily_dataset(
    count: int = 300,
    real_tles_path: Path | None = None,
    satellites_path: Path | None = None,
) -> PipelineOutput:
    """构建每日数据集。优先使用 satellites.json 真实数据。"""

    if count <= 0:
        raise ValueError("count 必须大于 0")

    generated_at = _utc_now_iso()
    weather = _fetch_space_weather()

    # Try loading real satellite data first
    real_satellites: list[SatelliteRecord] = []
    if satellites_path is not None:
        real_satellites = _load_real_satellites(satellites_path)
    if not real_satellites:
        # Auto-detect satellites.json in data/ dir
        auto_path = Path("data/satellites.json")
        if auto_path.exists():
            real_satellites = _load_real_satellites(auto_path)

    use_real_data = len(real_satellites) > 0

    tle_rows = []
    fin_rows = []

    if use_real_data:
        # Use real satellite data
        for i, sat in enumerate(real_satellites):
            solar_base = weather["f107"] + (i % 25) * 0.25
            kp_base = weather["kp_index"] + (i % 8) * 0.1
            age_years = 0.5 + (i % 12) * 0.4
            health = max(0.1, 0.98 - (i % 20) * 0.02)

            tle_rows.append({
                "id": sat.id,
                "name": sat.name,
                "norad_id": sat.norad_id,
                "category": sat.category,
                "status": sat.status,
                "line1": sat.line1,
                "line2": sat.line2,
                "lat": sat.lat,
                "lng": sat.lng,
                "alt": sat.alt,
            })

            fin_rows.append({
                "id": sat.id,
                "duration_days": 90 + (i % 240),
                "event_observed": 1 if (i % 11 == 0 or health < 0.45) else 0,
                "f107": solar_base,
                "kp_index": kp_base,
                "solar_wind_index": solar_base * 0.92 + 3.0,
                "asset_age_years": age_years,
                "health_score": health,
                "exposure_amount": 50_000_000.0 + (i % 10) * 8_000_000.0,
                "lgf": 0.35 + (i % 6) * 0.07,
            })
    else:
        # Fallback to simulated data
        real_tles = _load_legacy_tles(real_tles_path)

        for i in range(count):
            sat_id = f"SAT-{i + 1:03d}"
            tle_pool = real_tles or BASE_TLES
            line1, line2 = tle_pool[i % len(tle_pool)]

            solar_base = weather["f107"] + (i % 25) * 0.25
            kp_base = weather["kp_index"] + (i % 8) * 0.1
            age_years = 0.5 + (i % 12) * 0.4
            health = max(0.1, 0.98 - (i % 20) * 0.02)

            tle_rows.append({"id": sat_id, "line1": line1, "line2": line2})
            fin_rows.append({
                "id": sat_id,
                "duration_days": 90 + (i % 240),
                "event_observed": 1 if (i % 11 == 0 or health < 0.45) else 0,
                "f107": solar_base,
                "kp_index": kp_base,
                "solar_wind_index": solar_base * 0.92 + 3.0,
                "asset_age_years": age_years,
                "health_score": health,
                "exposure_amount": 50_000_000.0 + (i % 10) * 8_000_000.0,
                "lgf": 0.35 + (i % 6) * 0.07,
            })

    tle_df = pd.DataFrame(tle_rows)
    finance_df = pd.DataFrame(fin_rows)

    return PipelineOutput(
        tle=tle_df,
        finance=finance_df,
        generated_at=generated_at,
        weather=weather,
        satellites=real_satellites,
        use_real_data=use_real_data,
    )


def save_pipeline_snapshot(output: PipelineOutput, out_dir: Path) -> None:
    """保存每日数据快照，便于 CI 或回溯分析。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    output.tle.to_json(out_dir / "tle.json", orient="records", indent=2)
    output.finance.to_json(out_dir / "finance.json", orient="records", indent=2)
