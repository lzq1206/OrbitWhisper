"""轨道推进与碰撞评估核心模块。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from sgp4.api import Satrec, jday


@dataclass
class CollisionEvent:
    """碰撞事件输出结构（兼容现有 json_generator）。"""

    asset_id: str
    counterpart_id: str
    tca_utc: str
    miss_distance_km: float
    poc: float


class OrbitalPropagator:
    """基于 SGP4 的轨道推进器，支持 ECI->LLA 与 TCA 计算。"""

    # WGS84 参考椭球参数（单位：km）
    WGS84_A_KM = 6378.137
    WGS84_F = 1.0 / 298.257223563

    def __init__(self, step_minutes: int = 10) -> None:
        self.step_minutes = step_minutes

    @staticmethod
    def _parse_utc(time_input: str | datetime) -> datetime:
        if isinstance(time_input, datetime):
            return time_input.astimezone(timezone.utc)
        return datetime.fromisoformat(time_input.replace("Z", "+00:00")).astimezone(timezone.utc)

    @staticmethod
    def _julian_dt(ts: datetime) -> tuple[float, float]:
        return jday(ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second + ts.microsecond / 1_000_000)

    @staticmethod
    def _gmst_radians(jd_ut1: float) -> float:
        """计算格林尼治平恒星时（GMST）弧度值。"""
        t = (jd_ut1 - 2451545.0) / 36525.0
        gmst_deg = (
            280.46061837
            + 360.98564736629 * (jd_ut1 - 2451545.0)
            + 0.000387933 * (t**2)
            - (t**3) / 38710000.0
        )
        return np.deg2rad(gmst_deg % 360.0)

    @classmethod
    def eci_to_lla(cls, x_eci_km: float, y_eci_km: float, z_eci_km: float, ts: datetime) -> tuple[float, float, float]:
        """ECI 转换为 LLA（经纬高）。

        数学说明（重点）：
        1) ECI->ECEF：地球自转等价为绕 Z 轴旋转 GMST 角。
           [x_ecef, y_ecef, z_ecef]^T = Rz(gmst) * [x_eci, y_eci, z_eci]^T
        2) ECEF->LLA：基于 WGS84 椭球迭代求解大地纬度。
           - 经度 lon = atan2(y, x)
           - 初值纬度 lat0 = atan2(z, p*(1-e^2))，p=sqrt(x^2+y^2)
           - 迭代更新曲率半径 N 与高度 alt，直到纬度收敛
        """

        jd, fr = cls._julian_dt(ts)
        gmst = cls._gmst_radians(jd + fr)

        cos_g = float(np.cos(gmst))
        sin_g = float(np.sin(gmst))

        # ECI -> ECEF 旋转
        x_ecef = x_eci_km * cos_g + y_eci_km * sin_g
        y_ecef = -x_eci_km * sin_g + y_eci_km * cos_g
        z_ecef = z_eci_km

        a = cls.WGS84_A_KM
        f = cls.WGS84_F
        e2 = f * (2.0 - f)

        lon = np.arctan2(y_ecef, x_ecef)
        p = np.hypot(x_ecef, y_ecef)

        # 极区退化处理
        if p < 1e-12:
            lat = np.pi / 2.0 if z_ecef >= 0 else -np.pi / 2.0
            alt = abs(z_ecef) - a * np.sqrt(1.0 - e2)
            return float(np.rad2deg(lat)), float(np.rad2deg(lon)), float(alt)

        # 迭代求解大地纬度
        lat = np.arctan2(z_ecef, p * (1.0 - e2))
        alt = 0.0
        for _ in range(6):
            sin_lat = np.sin(lat)
            n = a / np.sqrt(1.0 - e2 * sin_lat * sin_lat)
            alt = p / np.cos(lat) - n
            lat = np.arctan2(z_ecef, p * (1.0 - e2 * n / (n + alt + 1e-12)))

        return float(np.rad2deg(lat)), float(np.rad2deg(lon)), float(alt)

    def propagate_tle(
        self,
        line1: str,
        line2: str,
        start_time: str | datetime,
        horizon_hours: int = 24,
        step_minutes: int | None = None,
    ) -> pd.DataFrame:
        """推进单颗目标，返回时间序列位置（ECI+LLA）。"""

        sat = Satrec.twoline2rv(line1, line2)
        start = self._parse_utc(start_time)
        step = step_minutes or self.step_minutes

        rows: list[dict[str, Any]] = []
        for minute_offset in range(0, horizon_hours * 60 + 1, step):
            ts = start + timedelta(minutes=minute_offset)
            jd, fr = self._julian_dt(ts)
            err, r, _ = sat.sgp4(jd, fr)
            if err != 0:
                # 跳过无效时刻，避免污染后续向量化计算
                continue

            x_km, y_km, z_km = float(r[0]), float(r[1]), float(r[2])
            lat, lng, alt = self.eci_to_lla(x_km, y_km, z_km, ts)
            rows.append(
                {
                    "timestamp": ts,
                    "x_km": x_km,
                    "y_km": y_km,
                    "z_km": z_km,
                    "lat": lat,
                    "lng": lng,
                    "alt": alt,
                }
            )

        return pd.DataFrame(rows)

    def calculate_tca(self, target_track: pd.DataFrame, debris_track: pd.DataFrame) -> dict[str, Any]:
        """向量化计算最近交会时间（TCA）与最小距离。"""

        if target_track.empty or debris_track.empty:
            return {
                "tca": None,
                "min_distance_km": float("inf"),
                "risk_level": "Unknown",
                "poc": 0.0,
            }

        merged = target_track[["timestamp", "x_km", "y_km", "z_km"]].merge(
            debris_track[["timestamp", "x_km", "y_km", "z_km"]],
            on="timestamp",
            suffixes=("_target", "_debris"),
            how="inner",
        )
        if merged.empty:
            return {
                "tca": None,
                "min_distance_km": float("inf"),
                "risk_level": "Unknown",
                "poc": 0.0,
            }

        target_xyz = merged[["x_km_target", "y_km_target", "z_km_target"]].to_numpy(dtype=float)
        debris_xyz = merged[["x_km_debris", "y_km_debris", "z_km_debris"]].to_numpy(dtype=float)

        # 向量化欧氏距离：||r_t - r_d||_2
        distances_km = np.linalg.norm(target_xyz - debris_xyz, axis=1)
        min_idx = int(np.argmin(distances_km))
        min_distance_km = float(distances_km[min_idx])
        tca = merged.iloc[min_idx]["timestamp"]

        risk_level = "High Risk" if min_distance_km < 5.0 else "Normal"
        # 单调映射：距离越小概率越高（工程近似）
        poc = float(np.clip(np.exp(-min_distance_km / 5.0) * 0.01, 0.0, 0.02))

        return {
            "tca": tca,
            "min_distance_km": min_distance_km,
            "risk_level": risk_level,
            "poc": poc,
        }


def estimate_collision_events(tle_df: pd.DataFrame, generated_at: str) -> list[CollisionEvent]:
    """兼容旧入口：基于轨道推进结果生成碰撞事件。"""

    if tle_df.empty:
        return []

    propagator = OrbitalPropagator(step_minutes=15)
    start = OrbitalPropagator._parse_utc(generated_at)

    tracks: dict[str, pd.DataFrame] = {}
    for _, row in tle_df.iterrows():
        asset_id = str(row.get("asset_id") or row.get("id"))
        tracks[asset_id] = propagator.propagate_tle(
            line1=str(row["line1"]),
            line2=str(row["line2"]),
            start_time=start,
            horizon_hours=24,
            step_minutes=15,
        )

    asset_ids = list(tracks.keys())
    events: list[CollisionEvent] = []
    for idx, asset_id in enumerate(asset_ids):
        counterpart_id = asset_ids[(idx + 1) % len(asset_ids)]
        result = propagator.calculate_tca(tracks[asset_id], tracks[counterpart_id])
        tca = result["tca"]
        tca_utc = tca.replace(microsecond=0).isoformat() if isinstance(tca, datetime) else start.isoformat()
        events.append(
            CollisionEvent(
                asset_id=asset_id,
                counterpart_id=counterpart_id,
                tca_utc=tca_utc,
                miss_distance_km=float(result["min_distance_km"]),
                poc=float(result["poc"]),
            )
        )

    return events
