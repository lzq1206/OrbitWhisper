"""SGP4-based orbital propagation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from sgp4.api import Satrec, WGS84, jday


class OrbitalPropagator:
    """Propagate spacecraft state vectors from TLE lines."""

    def __init__(self, line1: str, line2: str) -> None:
        self.satrec = Satrec.twoline2rv(line1, line2, WGS84)

    def propagate_window(
        self,
        start_utc: datetime,
        end_utc: datetime,
        step_minutes: int,
    ) -> pd.DataFrame:
        if step_minutes <= 0:
            raise ValueError("step_minutes must be positive")

        if start_utc.tzinfo is None:
            start_utc = start_utc.replace(tzinfo=timezone.utc)
        if end_utc.tzinfo is None:
            end_utc = end_utc.replace(tzinfo=timezone.utc)
        if end_utc < start_utc:
            raise ValueError("end_utc must be greater than or equal to start_utc")

        rows: list[dict[str, float | datetime]] = []
        current = start_utc
        while current <= end_utc:
            jd, fr = jday(
                current.year,
                current.month,
                current.day,
                current.hour,
                current.minute,
                current.second + current.microsecond / 1_000_000,
            )
            error_code, position, velocity = self.satrec.sgp4(jd, fr)
            if error_code != 0:
                raise RuntimeError(f"SGP4 propagation failed at {current.isoformat()} with code {error_code}")

            rows.append(
                {
                    "timestamp": current,
                    "x": position[0],
                    "y": position[1],
                    "z": position[2],
                    "vx": velocity[0],
                    "vy": velocity[1],
                    "vz": velocity[2],
                }
            )
            current += timedelta(minutes=step_minutes)

        return pd.DataFrame(rows)
