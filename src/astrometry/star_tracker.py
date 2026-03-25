"""Star extraction and pixel-to-RA/Dec conversion helpers.

核心逻辑框架（伪代码级）：
1) 读取上传图片并做背景统计（中位数 + MAD/sigma_clipped_stats）。
2) 使用 DAOStarFinder 检测点源，得到像素坐标 (x, y) 与亮度。
3) 将像素星点与参考星表（Gaia/Tycho）匹配，解算线性近似 WCS（plate solving）。
4) 用 WCS 把目标像素坐标转换成赤经/赤纬 (RA/Dec)。
5) 对比相邻时刻点源，筛出相对背景恒星发生显著位移的候选目标。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image

try:
    from astropy.stats import sigma_clipped_stats
    from astropy.wcs import WCS
    from photutils.detection import DAOStarFinder
except Exception:  # pragma: no cover - optional runtime dependency
    sigma_clipped_stats = None
    WCS = None
    DAOStarFinder = None


@dataclass(slots=True)
class SourceDetection:
    """A detected point source in image pixel coordinates."""

    x: float
    y: float
    flux: float


def _load_image_gray(image_bytes: bytes) -> np.ndarray:
    with Image.open(BytesIO(image_bytes)) as img:
        gray = img.convert("L")
        return np.asarray(gray, dtype=float)


def extract_point_sources(
    image_bytes: bytes,
    fwhm: float = 3.0,
    threshold_sigma: float = 5.0,
) -> list[SourceDetection]:
    """Extract point-like sources from image using DAOStarFinder when available.

    Falls back to a simple threshold-based detector if photutils/astropy is unavailable.
    """
    data = _load_image_gray(image_bytes)
    if data.size == 0:
        return []

    if DAOStarFinder is not None and sigma_clipped_stats is not None:
        mean, median, std = sigma_clipped_stats(data, sigma=3.0)
        finder = DAOStarFinder(fwhm=fwhm, threshold=threshold_sigma * max(std, 1e-6))
        table = finder(data - median)
        if table is None:
            return []
        return [
            SourceDetection(x=float(row["xcentroid"]), y=float(row["ycentroid"]), flux=float(row["flux"]))
            for row in table
        ]

    threshold = float(np.mean(data) + threshold_sigma * np.std(data))
    ys, xs = np.where(data >= threshold)
    return [SourceDetection(x=float(x), y=float(y), flux=float(data[y, x])) for y, x in zip(ys, xs)]


def solve_wcs_from_reference(
    image_shape: tuple[int, int],
    reference_center_radec: tuple[float, float] | None = None,
    pixel_scale_deg: float = 0.00028,
) -> Any:
    """Build a pragmatic TAN WCS model.

    In production, replace with catalog matching (e.g., astroquery Gaia) and robust fit.
    """
    if WCS is None:
        return None

    ra0, dec0 = reference_center_radec or (0.0, 0.0)
    h, w = image_shape
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [w / 2.0, h / 2.0]
    wcs.wcs.cd = np.array([[-pixel_scale_deg, 0.0], [0.0, pixel_scale_deg]])
    wcs.wcs.crval = [ra0, dec0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def pixel_to_radec(wcs: Any, x: float, y: float) -> tuple[float, float]:
    """Convert a pixel coordinate to RA/Dec using WCS."""
    if wcs is None:
        return x, y
    ra, dec = wcs.wcs_pix2world([[x, y]], 0)[0]
    return float(ra), float(dec)


def find_moving_target(
    current_sources: list[SourceDetection],
    baseline_sources: list[SourceDetection],
    min_pixel_shift: float = 4.0,
) -> SourceDetection | None:
    """Find source not matching background stars within min_pixel_shift."""
    if not current_sources:
        return None
    if not baseline_sources:
        return max(current_sources, key=lambda s: s.flux)

    for source in sorted(current_sources, key=lambda s: s.flux, reverse=True):
        nearest = min(
            ((source.x - ref.x) ** 2 + (source.y - ref.y) ** 2) ** 0.5 for ref in baseline_sources
        )
        if nearest >= min_pixel_shift:
            return source
    return None


def process_observation_frame(
    image_bytes: bytes,
    timestamp: datetime,
    baseline_sources: list[SourceDetection] | None = None,
    reference_center_radec: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Process one observation frame and extract candidate target RA/Dec."""
    sources = extract_point_sources(image_bytes)
    array = _load_image_gray(image_bytes)
    wcs = solve_wcs_from_reference(array.shape, reference_center_radec=reference_center_radec)
    moving = find_moving_target(sources, baseline_sources or [])

    target = None
    if moving is not None:
        ra, dec = pixel_to_radec(wcs, moving.x, moving.y)
        target = {
            "pixel": {"x": moving.x, "y": moving.y},
            "ra_deg": ra,
            "dec_deg": dec,
            "flux": moving.flux,
        }

    return {
        "timestamp": timestamp.isoformat(),
        "num_sources": len(sources),
        "sources": [{"x": s.x, "y": s.y, "flux": s.flux} for s in sources[:200]],
        "target": target,
    }
