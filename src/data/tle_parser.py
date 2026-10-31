"""Helpers to parse and normalize TLE-derived features."""

from __future__ import annotations

from typing import Any


def parse_bstar(line1: str) -> float:
    """Parse BSTAR drag term from TLE line 1.

    TLE packs BSTAR as mantissa/exponent without an explicit decimal point,
    e.g. ' 29677-4' -> 0.29677e-4.
    """
    token = line1[53:61].strip()
    if len(token) < 7:
        raise ValueError("Invalid BSTAR token")
    mantissa = float(f"0.{token[:-2].replace('+', '').replace('-', '')}")
    if token.startswith("-"):
        mantissa *= -1
    exponent = int(token[-2:])
    return mantissa * (10**exponent)


def parse_tle_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw TLE payload for feature engineering."""
    line1 = raw["line1"]
    line2 = raw["line2"]
    return {
        **raw,
        "bstar": parse_bstar(line1),
        "inclination_deg": float(line2[8:16]),
    }
