#!/usr/bin/env python3
"""Fetch satellite orbital elements from CelesTrak and compute current positions.

Data sources:
  - https://celestrak.org/NORAD/elements/
  - https://rhodesmill.org/skyfield/earth-satellites.html#downloading-satellite-elements

Outputs data/satellites.json containing all satellites grouped by category.
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from sgp4.api import Satrec, WGS72
from sgp4.api import jday
from sgp4 import exporter

# ── CelesTrak GROUP definitions, organized by category ──────────────────────

SATELLITE_GROUPS: dict[str, list[str]] = {
    "空间站与特殊兴趣": [
        "stations",
        "visual",
        "last-30-days",
    ],
    "气象与地球资源": [
        "weather",
        "noaa",
        "goes",
        "resource",
        "sarsat",
        "dmc",
        "tdrss",
        "argos",
        "planet",
        "spire",
    ],
    "通信卫星": [
        "geo",
        "intelsat",
        "ses",
        "iridium-NEXT",
        "orbcomm",
        "globalstar",
        "amateur",
        "x-comm",
        "other-comm",
    ],
    "导航卫星": [
        "gnss",
        "gps-ops",
        "glo-ops",
        "galileo",
        "beidou",
        "sbas",
        "nnss",
        "musson",
    ],
    "科学卫星": [
        "science",
        "geodetic",
        "engineering",
        "education",
    ],
    "其他": [
        "military",
        "radar",
        "cubesat",
        "other",
    ],
}

# Optional large constellations (disabled by default to keep size manageable)
OPTIONAL_LARGE_GROUPS: dict[str, list[str]] = {
    "大型星座": [
        "starlink",
        "oneweb",
        "qianfan",
    ],
}

GP_CSV_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=csv"
GP_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"

# ── SGP4 position computation ───────────────────────────────────────────────

def _sgp4_position_from_satrec(satrec: Satrec, dt: datetime) -> tuple[float, float, float] | None:
    """Compute satellite lat/lng/alt (km) from a Satrec object at the given datetime.

    Returns None on propagation error.
    """
    jd, fr = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond / 1e6)
    e, r, v = satrec.sgp4(jd, fr)
    if e != 0:
        return None

    x, y, z = r
    dist = math.sqrt(x * x + y * y + z * z)
    if dist < 1.0:
        return None

    # Compute sub-satellite point (simplified TEME->ECEF using GMST rotation)
    gmst = _greenwich_sidereal_time(jd, fr)
    lng = math.degrees(math.atan2(y, x)) - gmst
    lng = ((lng + 180) % 360) - 180

    lat = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))

    earth_radius = 6378.137  # km
    alt = dist - earth_radius

    return (round(lat, 6), round(lng, 6), round(alt, 3))


def _greenwich_sidereal_time(jd: float, fr: float) -> float:
    """Compute Greenwich Mean Sidereal Time in degrees."""
    t = (jd + fr - 2451545.0) / 36525.0
    gmst_sec = (
        67310.54841
        + (876600.0 * 3600 + 8640184.812866) * t
        + 0.093104 * t * t
        - 6.2e-6 * t * t * t
    )
    return (gmst_sec / 240.0) % 360.0


# ── Fetch and process ───────────────────────────────────────────────────────

def fetch_group_tle(session: requests.Session, group: str, timeout: int = 30) -> list[dict[str, str]]:
    """Fetch a single CelesTrak GP group in 3LE (TLE) format.

    Returns list of dicts with keys: name, line1, line2
    """
    url = GP_TLE_URL.format(group=group)
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  WARNING: Failed to fetch group '{group}': {exc}", file=sys.stderr)
        return []

    text = resp.text.strip()
    if not text or text.startswith("No GP"):
        return []

    lines = text.splitlines()
    results = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        # 3LE format: name line, then line1, then line2
        if i + 2 < len(lines) and lines[i + 1].rstrip().startswith("1 ") and lines[i + 2].rstrip().startswith("2 "):
            name = line.strip()
            line1 = lines[i + 1].rstrip()
            line2 = lines[i + 2].rstrip()
            results.append({"name": name, "line1": line1, "line2": line2})
            i += 3
        elif line.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].rstrip().startswith("2 "):
            line1 = line
            line2 = lines[i + 1].rstrip()
            results.append({"name": "", "line1": line1, "line2": line2})
            i += 2
        else:
            i += 1

    return results


def process_tle_satellite(tle_record: dict[str, str], category: str, now: datetime, is_decayed: bool = False) -> dict[str, Any] | None:
    """Process a single satellite TLE record into our output format."""
    name = tle_record.get("name", "UNKNOWN").strip()
    line1 = tle_record.get("line1", "").strip()
    line2 = tle_record.get("line2", "").strip()

    if not line1.startswith("1 ") or not line2.startswith("2 "):
        return None

    try:
        norad_id = int(line1[2:7].strip())
    except (ValueError, IndexError):
        return None

    if norad_id <= 0:
        return None

    try:
        satrec = Satrec.twoline2rv(line1, line2, WGS72)
    except Exception:
        return None

    status = "active"
    pos = None if is_decayed else _sgp4_position_from_satrec(satrec, now)
    
    # Fallback for decayed satellites (error computing current pos, or alt <= 0, or explicitly decayed)
    if is_decayed or pos is None or pos[2] <= 0:
        year = satrec.epochyr + 2000 if satrec.epochyr < 57 else satrec.epochyr + 1900
        epoch_dt = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=satrec.epochdays - 1)
        pos_epoch = _sgp4_position_from_satrec(satrec, epoch_dt)
        status = "decayed"
        if pos_epoch is not None:
            lat, lng, _ = pos_epoch
            pos = (lat, lng, 0.0)
        else:
            lat = math.degrees(math.asin(math.sin(satrec.incco) * math.sin(satrec.mo + satrec.argpo)))
            lng = math.degrees(satrec.nodeo)
            lng = ((lng + 180) % 360) - 180
            pos = (round(lat, 6), round(lng, 6), 0.0)
    elif pos[2] < 240.0:
        status = "reentering"

    lat, lng, alt = pos

    return {
        "norad_id": norad_id,
        "name": name if name else f"SAT-{norad_id}",
        "category": category,
        "status": status,
        "lat": lat,
        "lng": lng,
        "alt": round(alt, 3),
        "line1": line1,
        "line2": line2,
    }


def fetch_all_satellites(include_large: bool = False, existing_file_path: str = None) -> dict[str, Any]:
    """Fetch all categorized satellite data from CelesTrak.

    Uses TLE/3LE format which is directly parseable by sgp4 without conversion.

    Args:
        include_large: If True, also fetch large constellations (Starlink, OneWeb, etc.)
        existing_file_path: Path to existing JSON to merge new records into, avoiding deletion.

    Returns:
        Dictionary with metadata and satellite records.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": "OrbitWhisper/1.0 (satellite data fetcher)"})

    now = datetime.now(timezone.utc)
    all_satellites: dict[int, dict[str, Any]] = {}  # keyed by norad_id for dedup
    category_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}

    if existing_file_path:
        try:
            with open(existing_file_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                for sat in old_data.get("satellites", []):
                    nid = sat.get("norad_id")
                    if nid:
                        all_satellites[nid] = sat
            print(f"Loaded {len(all_satellites)} existing satellites.")
        except Exception as e:
            print(f"Could not load existing file, starting fresh. ({e})")

    groups_to_fetch = dict(SATELLITE_GROUPS)
    if include_large:
        groups_to_fetch.update(OPTIONAL_LARGE_GROUPS)

    total_groups = sum(len(gs) for gs in groups_to_fetch.values())
    fetched = 0

    # Pre-fetch last-30-days explicitly to know exactly what's decayed
    print("[0] Pre-fetching known decayed list...", end=" ")
    sys.stdout.flush()
    decayed_ids = set()
    decayed_records = fetch_group_tle(session, "last-30-days")
    for r in decayed_records:
        line1 = r.get("line1", "")
        if len(line1) > 7:
            try:
                decayed_ids.add(int(line1[2:7].strip()))
            except ValueError:
                pass
    print(f"found {len(decayed_ids)}")

    for category, groups in groups_to_fetch.items():
        cat_count = 0
        for group in groups:
            fetched += 1
            print(f"[{fetched}/{total_groups}] Fetching '{group}' ({category})...", end=" ")
            sys.stdout.flush()

            records = fetch_group_tle(session, group)
            new_count = 0

            for tle_record in records:
                nid_str = tle_record.get("line1", "")[2:7] if len(tle_record.get("line1", "")) > 7 else "0"
                try:
                    nid = int(nid_str.strip())
                except ValueError:
                    continue
                is_decayed = nid in decayed_ids
                
                sat = process_tle_satellite(tle_record, category, now, is_decayed)
                if sat is None:
                    continue
                nid = sat["norad_id"]
                if nid not in all_satellites:
                    new_count += 1
                all_satellites[nid] = sat
                cat_count += 1

            group_counts[group] = len(records)
            print(f"got {len(records)} records, {new_count} new unique")

            # Be polite to CelesTrak servers
            time.sleep(0.5)

    # Re-tally exact category counts from the final dict to account for merged legacy data
    category_counts = {}
    for sat in all_satellites.values():
        cat = sat.get("category", "其他")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Sort by NORAD ID
    satellite_list = sorted(all_satellites.values(), key=lambda s: s["norad_id"])

    result = {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "source": "celestrak",
        "total_satellites": len(satellite_list),
        "category_counts": category_counts,
        "group_counts": group_counts,
        "satellites": satellite_list,
    }

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch satellite data from CelesTrak")
    parser.add_argument("--include-large", action="store_true",
                        help="Include large constellations (Starlink, OneWeb, etc.)")
    parser.add_argument("--output", "-o", default="data/satellites.json",
                        help="Output file path (default: data/satellites.json)")
    args = parser.parse_args()

    print("=" * 60)
    print("OrbitWhisper: CelesTrak Satellite Data Fetcher")
    print("=" * 60)

    output_path = Path(args.output)
    result = fetch_all_satellites(
        include_large=args.include_large, 
        existing_file_path=str(output_path) if output_path.exists() else None
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print(f"Total unique satellites: {result['total_satellites']}")
    print("\nCategory breakdown:")
    for cat, count in result["category_counts"].items():
        print(f"  {cat}: {count}")
    print(f"\nOutput written to: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
