"""Conjunction assessment primitives."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def smart_sieve(df_sat1: pd.DataFrame, df_sat2: pd.DataFrame, radial_gate_km: float = 25.0) -> bool:
    """Quick radial-distance filter to prune impossible conjunction pairs."""
    r1 = np.linalg.norm(df_sat1[["x", "y", "z"]].to_numpy(), axis=1)
    r2 = np.linalg.norm(df_sat2[["x", "y", "z"]].to_numpy(), axis=1)
    return bool(np.abs(np.median(r1) - np.median(r2)) <= radial_gate_km)


def find_tca(df_sat1: pd.DataFrame, df_sat2: pd.DataFrame) -> Optional[dict]:
    """Find Time of Closest Approach (TCA) and miss distance in km.

    Returns details when min distance < 5 km, otherwise None.
    """
    merged = pd.merge(
        df_sat1[["timestamp", "x", "y", "z"]],
        df_sat2[["timestamp", "x", "y", "z"]],
        on="timestamp",
        suffixes=("_sat1", "_sat2"),
        how="inner",
    ).sort_values("timestamp")

    if merged.empty:
        return None

    p1 = merged[["x_sat1", "y_sat1", "z_sat1"]].to_numpy(dtype=float)
    p2 = merged[["x_sat2", "y_sat2", "z_sat2"]].to_numpy(dtype=float)
    distances = np.linalg.norm(p1 - p2, axis=1)
    idx = int(np.argmin(distances))
    miss_distance = float(distances[idx])

    if miss_distance >= 5.0:
        return None

    row = merged.iloc[idx]
    return {
        "tca_time": row["timestamp"],
        "sat1_position": [float(row["x_sat1"]), float(row["y_sat1"]), float(row["z_sat1"])],
        "sat2_position": [float(row["x_sat2"]), float(row["y_sat2"]), float(row["z_sat2"])],
        "miss_distance_km": miss_distance,
    }


def compute_poc_2d(relative_position_km: np.ndarray, covariance_2d_km2: np.ndarray, hard_body_radius_km: float) -> float:
    """Approximate 2D PoC under isotropic-Gaussian assumption in encounter plane."""
    if covariance_2d_km2.shape != (2, 2):
        raise ValueError("covariance_2d_km2 must be 2x2")

    sigma2 = float(np.mean(np.diag(covariance_2d_km2)))
    if sigma2 <= 0:
        return 0.0

    d2 = float(np.dot(relative_position_km[:2], relative_position_km[:2]))
    r2 = hard_body_radius_km**2
    return float(np.exp(-d2 / (2.0 * sigma2)) * (1.0 - np.exp(-r2 / (2.0 * sigma2))))
