"""Collision-risk approximation layer for AstroQuant 3D."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd


@dataclass
class CollisionEvent:
    asset_id: str
    counterpart_id: str
    tca_utc: str
    miss_distance_km: float
    poc: float


def estimate_collision_events(tle_df: pd.DataFrame, generated_at: str) -> list[CollisionEvent]:
    """Produce minimal collision events for dashboard rendering.

    This is a deterministic scaffold that can later be upgraded to true SGP4 + ML
    residual fusion while preserving the public output contract.
    """

    if tle_df.empty:
        return []

    start = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    events: list[CollisionEvent] = []
    asset_ids = list(tle_df["asset_id"])
    for idx, asset_id in enumerate(asset_ids):
        counterpart = asset_ids[(idx + 1) % len(asset_ids)]
        miss_distance = 4.2 if idx == 0 else 9.8
        poc = 2.7e-4 if miss_distance < 5.0 else 3.5e-5
        events.append(
            CollisionEvent(
                asset_id=asset_id,
                counterpart_id=counterpart,
                tca_utc=(start + timedelta(hours=6 + idx * 3)).replace(microsecond=0).isoformat(),
                miss_distance_km=miss_distance,
                poc=poc,
            )
        )
    return events

