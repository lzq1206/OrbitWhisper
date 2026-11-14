import numpy as np
from typing import Dict


def build_external_factor_series(fetch_results: Dict[str, object], n_steps: int):
    solar = np.ones(n_steps)
    launch = np.ones(n_steps)

    try:
        noaa = fetch_results.get("noaa_swpc")
        if noaa and getattr(noaa, "ok", False) and isinstance(noaa.data, list) and len(noaa.data) > 0:
            vals = []
            for row in noaa.data[-min(100, len(noaa.data)):]:
                v = row.get("kp_index") or row.get("kp") or row.get("Kp")
                try:
                    vals.append(float(v))
                except Exception:
                    pass
            if vals:
                k = float(np.mean(vals))
                solar *= 1.0 + 0.02 * (k - 3.0)
    except Exception:
        pass

    try:
        ll = fetch_results.get("launch_library")
        if ll and getattr(ll, "ok", False) and isinstance(ll.data, dict):
            n = len(ll.data.get("results", []))
            launch *= 1.0 + min(0.20, n / 100.0)
    except Exception:
        pass

    return {
        "solar_factor": solar,
        "launch_factor": launch,
        "combined_factor": np.clip(solar * launch, 0.8, 1.5),
    }
