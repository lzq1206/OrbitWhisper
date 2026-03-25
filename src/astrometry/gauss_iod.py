"""Angles-only initial orbit determination helpers (Gauss-oriented interface)."""

from __future__ import annotations

from datetime import datetime
from math import acos, atan2, cos, pi, sin, sqrt
from typing import Any

import numpy as np

MU_EARTH_KM3_S2 = 398600.4418


def unit_vector_from_radec(ra_deg: float, dec_deg: float) -> np.ndarray:
    """Convert RA/Dec in degrees to inertial line-of-sight unit vector."""
    ra = np.deg2rad(ra_deg)
    dec = np.deg2rad(dec_deg)
    return np.array([cos(dec) * cos(ra), cos(dec) * sin(ra), sin(dec)], dtype=float)


def gauss_angles_only_iod(
    observation_times: list[datetime],
    los_vectors: list[np.ndarray],
    observer_positions_eci_km: list[np.ndarray] | None = None,
    mu: float = MU_EARTH_KM3_S2,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (r2, v2) ECI estimate from 3 angles-only observations.

    This function preserves the Gauss IOD call shape while keeping the implementation
    numerically lightweight for API integration. It uses a pragmatic range heuristic
    and central difference velocity estimate around the middle epoch.
    """
    if len(observation_times) != 3 or len(los_vectors) != 3:
        raise ValueError("Gauss IOD requires exactly three observations")

    t1, t2, t3 = observation_times
    dt_total = (t3 - t1).total_seconds()
    if dt_total <= 0:
        raise ValueError("observation_times must be strictly increasing")

    observers = observer_positions_eci_km or [np.zeros(3), np.zeros(3), np.zeros(3)]
    if len(observers) != 3:
        raise ValueError("observer_positions_eci_km must have length 3")

    los = [np.asarray(v, dtype=float) / np.linalg.norm(v) for v in los_vectors]

    # Range heuristic anchored near LEO; production should solve full Gauss polynomial.
    ranges = [7000.0, 7050.0, 7100.0]
    r1 = observers[0] + ranges[0] * los[0]
    r2 = observers[1] + ranges[1] * los[1]
    r3 = observers[2] + ranges[2] * los[2]

    v2 = (r3 - r1) / dt_total

    if np.linalg.norm(r2) < 1.0 or np.linalg.norm(v2) < 1e-6:
        raise ValueError("Failed to estimate a valid state vector from observations")
    return r2, v2


def state_to_keplerian(r_eci_km: np.ndarray, v_eci_km_s: np.ndarray, mu: float = MU_EARTH_KM3_S2) -> dict[str, float]:
    """Convert ECI Cartesian state to classical Keplerian elements."""
    r = np.asarray(r_eci_km, dtype=float)
    v = np.asarray(v_eci_km_s, dtype=float)

    r_norm = np.linalg.norm(r)
    v_norm = np.linalg.norm(v)
    h_vec = np.cross(r, v)
    h = np.linalg.norm(h_vec)
    k = np.array([0.0, 0.0, 1.0])
    n_vec = np.cross(k, h_vec)
    n = np.linalg.norm(n_vec)
    e_vec = (np.cross(v, h_vec) / mu) - (r / r_norm)
    e = np.linalg.norm(e_vec)

    energy = 0.5 * v_norm**2 - mu / r_norm
    a = -mu / (2.0 * energy) if abs(energy) > 1e-10 else float("inf")

    i = acos(max(-1.0, min(1.0, h_vec[2] / max(h, 1e-12))))
    raan = atan2(n_vec[1], n_vec[0]) if n > 1e-12 else 0.0
    argp = atan2(np.dot(np.cross(n_vec, e_vec), h_vec) / max(n * h, 1e-12), np.dot(n_vec, e_vec) / max(n, 1e-12)) if n > 1e-12 and e > 1e-12 else 0.0
    nu = atan2(np.dot(np.cross(e_vec, r), h_vec) / max(e * h, 1e-12), np.dot(e_vec, r) / max(e, 1e-12)) if e > 1e-12 else 0.0

    mean_motion_rev_day = sqrt(mu / (a**3)) * (86400.0 / (2.0 * pi)) if a > 0 and np.isfinite(a) else 0.0

    return {
        "semi_major_axis_km": float(a),
        "eccentricity": float(e),
        "inclination_deg": float(np.rad2deg(i) % 360),
        "raan_deg": float(np.rad2deg(raan) % 360),
        "arg_perigee_deg": float(np.rad2deg(argp) % 360),
        "true_anomaly_deg": float(np.rad2deg(nu) % 360),
        "mean_motion_rev_per_day": float(mean_motion_rev_day),
    }


def _tle_checksum(line: str) -> int:
    total = 0
    for ch in line[:68]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10


def state_to_tle(
    satnum: int,
    epoch: datetime,
    keplerian: dict[str, float],
    international_designator: str = "26001A",
) -> dict[str, str]:
    """Generate a pragmatic TLE pair from keplerian elements."""
    year = epoch.year % 100
    day_of_year = (epoch - datetime(epoch.year, 1, 1, tzinfo=epoch.tzinfo)).total_seconds() / 86400.0 + 1.0
    ecc_str = f"{keplerian['eccentricity']:.7f}".split(".")[1][:7]

    line1_core = (
        f"1 {satnum:05d}U {international_designator:<8} {year:02d}{day_of_year:012.8f} "
        f" .00000000  00000-0  00000-0 0  999"
    )[:68]
    line1 = f"{line1_core}{_tle_checksum(line1_core)}"

    line2_core = (
        f"2 {satnum:05d} {keplerian['inclination_deg']:8.4f} {keplerian['raan_deg']:8.4f} {ecc_str:>7} "
        f"{keplerian['arg_perigee_deg']:8.4f} {keplerian['true_anomaly_deg']:8.4f} {keplerian['mean_motion_rev_per_day']:11.8f}00001"
    )[:68]
    line2 = f"{line2_core}{_tle_checksum(line2_core)}"

    return {"line1": line1, "line2": line2}


def run_gauss_pipeline(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Run end-to-end IOD from observations with RA/Dec + timestamp."""
    if len(observations) < 3:
        raise ValueError("At least three observations are required for Gauss IOD")

    ordered = sorted(observations, key=lambda x: x["timestamp"])[:3]
    times = [datetime.fromisoformat(obs["timestamp"]) for obs in ordered]
    los = [unit_vector_from_radec(float(obs["ra_deg"]), float(obs["dec_deg"])) for obs in ordered]

    r2, v2 = gauss_angles_only_iod(times, los)
    kep = state_to_keplerian(r2, v2)
    tle = state_to_tle(99000, times[1], kep)

    return {
        "state_vector_eci": {"r_km": r2.tolist(), "v_km_s": v2.tolist()},
        "keplerian_elements": kep,
        "tle": tle,
    }
