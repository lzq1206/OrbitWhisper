"""Interactive FastAPI service for optical orbit determination workflows."""

from __future__ import annotations

import difflib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.astrometry.gauss_iod import run_gauss_pipeline
from src.astrometry.star_tracker import SourceDetection, process_observation_frame

app = FastAPI(title="OrbitWhisper Optical IOD API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

KNOWN_SATELLITES: list[dict[str, Any]] = []
UPLOADED_TLES: list[dict[str, Any]] = []
DB_PATH = Path(__file__).resolve().parents[2] / "data" / "satellites.db"


def _ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS satellite_names (
                temp_id TEXT PRIMARY KEY,
                custom_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _load_known_satellites() -> None:
    if KNOWN_SATELLITES:
        return
    report_path = Path(__file__).resolve().parents[2] / "data" / "daily_report.json"
    if report_path.exists():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        satellites = payload.get("satellites", [])
        for sat in satellites:
            sat_id = sat.get("id", "")
            if sat_id:
                KNOWN_SATELLITES.append({"id": sat_id, "name": sat_id, "source": "daily_report"})


def _parse_tle_text(tle_text: str) -> tuple[str, str, str | None]:
    lines = [line.strip().lstrip("\ufeff") for line in tle_text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError("TLE text must contain at least two non-empty lines")
    for idx in range(len(lines) - 1):
        line1 = lines[idx]
        line2 = lines[idx + 1]
        if line1.startswith("1 ") and line2.startswith("2 "):
            inferred_name = None
            if idx > 0 and not lines[idx - 1].startswith(("1 ", "2 ")):
                inferred_name = lines[idx - 1]
            return line1, line2, inferred_name
    raise ValueError("TLE format invalid: expected line1/line2 with prefixes '1 ' and '2 '")


def _extract_norad_catalog_id(line1: str) -> int | None:
    cat_id = line1[2:7].strip() if len(line1) >= 7 else ""
    return int(cat_id) if cat_id.isdigit() else None


def _build_preview_orbit(name: str, line1: str) -> dict[str, Any]:
    cat_id = _extract_norad_catalog_id(line1)
    # Keep deterministic pseudo-positions for uploaded TLE preview when no propagated track exists yet.
    # 100_000 bounds the hash-derived seed to a stable small range while preserving visual spread.
    seed = cat_id if cat_id is not None else abs(hash(name)) % 100_000
    lat = ((seed % 140) - 70) * 0.8
    lng = ((seed * 7) % 360) - 180
    alt = 420 + (seed % 500)
    return {"asset_id": name, "name": name, "lat": round(lat, 6), "lng": round(lng, 6), "alt": round(float(alt), 6)}


def _parse_timestamps(raw: str | None, n: int) -> list[datetime]:
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="timestamps must be a JSON array of ISO datetime strings") from exc

        if not isinstance(data, list):
            raise HTTPException(status_code=400, detail="timestamps must be a JSON list")
        if len(data) != n:
            raise HTTPException(status_code=400, detail="timestamps length must match the number of uploaded files")

        times: list[datetime] = []
        for idx, ts in enumerate(data):
            try:
                times.append(datetime.fromisoformat(str(ts)))
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"timestamps[{idx}] must be a valid ISO datetime string",
                ) from exc
        return times

    return [datetime.now(timezone.utc) for _ in range(n)]


class TLEUploadRequest(BaseModel):
    tle_text: str = Field(..., min_length=1)
    name: str | None = None


class NameBindingRequest(BaseModel):
    temp_id: str = Field(..., min_length=3)
    custom_name: str = Field(..., min_length=1)


@app.on_event("startup")
def startup() -> None:
    _ensure_db()
    _load_known_satellites()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/upload_image")
async def upload_image(
    files: list[UploadFile] = File(...),
    timestamps: str | None = Form(default=None),
) -> dict[str, Any]:
    if len(files) < 1:
        raise HTTPException(status_code=400, detail="At least one image is required")

    obs_times = _parse_timestamps(timestamps, len(files))
    baseline_sources = None
    extracted_targets: list[dict[str, Any]] = []
    frame_results: list[dict[str, Any]] = []

    for idx, file in enumerate(files):
        content = await file.read()
        frame = process_observation_frame(content, obs_times[idx], baseline_sources=baseline_sources)
        frame_results.append({"filename": file.filename, **frame})

        if idx == 0:
            baseline_sources = [SourceDetection(x=s["x"], y=s["y"], flux=s["flux"]) for s in frame.get("sources", [])]

        target = frame.get("target")
        if target is not None:
            extracted_targets.append(
                {
                    "timestamp": frame["timestamp"],
                    "ra_deg": target["ra_deg"],
                    "dec_deg": target["dec_deg"],
                }
            )

    iod_result = None
    if len(extracted_targets) >= 3:
        iod_result = run_gauss_pipeline(extracted_targets[:3])

    unknown_suggestion = None
    if iod_result is not None:
        unknown_suggestion = f"Astro-X{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    return {
        "frames": frame_results,
        "observation_targets": extracted_targets,
        "iod_result": iod_result,
        "unknown_target_suggestion": unknown_suggestion,
        "unknown_temp_id": f"UNKN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}" if iod_result else None,
    }


@app.post("/api/upload_tle")
def upload_tle(payload: TLEUploadRequest) -> dict[str, Any]:
    line1, line2, inferred_name = _parse_tle_text(payload.tle_text)
    uploaded_cat_id = _extract_norad_catalog_id(line1)
    for existing in UPLOADED_TLES:
        existing_cat_id = _extract_norad_catalog_id(str(existing.get("line1", "")))
        if existing.get("line1") == line1 and existing.get("line2") == line2:
            existing_name = str(existing.get("name", ""))
            return {
                "message": "TLE already exists",
                "duplicate": True,
                "satellite": existing,
                "orbit": _build_preview_orbit(existing_name, str(existing.get("line1", ""))),
            }
        if uploaded_cat_id is not None and existing_cat_id == uploaded_cat_id:
            existing["line1"] = line1
            existing["line2"] = line2
            existing["created_at"] = datetime.now(timezone.utc).isoformat()
            existing_name = str(existing.get("name", ""))
            return {
                "message": "TLE updated",
                "duplicate": False,
                "updated": True,
                "satellite": existing,
                "orbit": _build_preview_orbit(existing_name, line1),
            }
    record = {
        "name": payload.name or inferred_name or f"TLE-{len(UPLOADED_TLES) + 1}",
        "line1": line1,
        "line2": line2,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    UPLOADED_TLES.append(record)
    KNOWN_SATELLITES.append({"id": record["name"], "name": record["name"], "source": "uploaded_tle"})
    return {"message": "TLE uploaded", "duplicate": False, "satellite": record, "orbit": _build_preview_orbit(record["name"], line1)}


@app.get("/api/satellites/search")
def search_satellites(q: str) -> dict[str, Any]:
    query = q.strip().lower()
    if not query:
        return {"query": q, "results": []}

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT temp_id, custom_name, created_at FROM satellite_names WHERE lower(temp_id) LIKE ? OR lower(custom_name) LIKE ?",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()

    db_results = [
        {"id": row[0], "name": row[1], "source": "custom_name", "created_at": row[2]}
        for row in rows
    ]

    ranked_known = []
    for sat in KNOWN_SATELLITES + UPLOADED_TLES:
        name = sat.get("name", sat.get("id", ""))
        if not name:
            continue
        score = difflib.SequenceMatcher(a=query, b=name.lower()).ratio()
        if query in name.lower() or score >= 0.4:
            ranked_known.append({"id": sat.get("id", name), "name": name, "source": sat.get("source", "known"), "score": round(score, 3)})

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in db_results + ranked_known:
        unique[(item["id"], item["name"])] = item

    results = sorted(unique.values(), key=lambda x: x.get("score", 1.0), reverse=True)[:20]
    return {"query": q, "results": results}


@app.post("/api/satellites/name")
def bind_satellite_name(payload: NameBindingRequest) -> dict[str, Any]:
    _ensure_db()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO satellite_names (temp_id, custom_name, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(temp_id) DO UPDATE SET custom_name=excluded.custom_name, created_at=excluded.created_at",
            (payload.temp_id, payload.custom_name, now),
        )
        conn.commit()

    KNOWN_SATELLITES.append({"id": payload.temp_id, "name": payload.custom_name, "source": "custom_name"})
    return {"message": "Name binding saved", "temp_id": payload.temp_id, "custom_name": payload.custom_name}


def _reset_state_for_tests(db_path: Path | None = None) -> None:
    """Reset in-memory state for deterministic tests."""
    global DB_PATH
    KNOWN_SATELLITES.clear()
    UPLOADED_TLES.clear()
    if db_path is not None:
        DB_PATH = db_path
    _ensure_db()
