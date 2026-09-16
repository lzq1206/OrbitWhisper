"""AstroQuant 后端主入口：串联碰撞与精算并导出前端 JSON。"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.engine.data_pipeline import build_daily_dataset
import numpy as np

# Load the dynamic insurance engine modules
try:
    from src.ext_insurance.debris_economics import simulate_orbit_dynamics
    from src.ext_insurance.drag_avoidance import aerodynamic_maneuver_effect
    from src.ext_insurance.gbma_evt import fit_gbma_threshold_model, expected_severity
    from src.ext_insurance.canonical_reserve import solve_thiele_reserve
    INSURANCE_ENABLED = True
except ImportError as e:
    print(f"Warning: Insurance modules not found. {e}")
    INSURANCE_ENABLED = False


def _premium_var(prices: list[float]) -> str:
    if not prices:
        return "+0.0%"
    avg_price = sum(prices) / len(prices)
    baseline = 50_000.0
    pct = (avg_price - baseline) / baseline * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


# ── Category color mapping ──────────────────────────────────────────────────
CATEGORY_COLORS = {
    "空间站与特殊兴趣": "#ff6600",
    "气象与地球资源": "#00ccff",
    "通信卫星": "#ffcc00",
    "导航卫星": "#00ff88",
    "科学卫星": "#cc44ff",
    "其他": "#888888",
    "大型星座": "#4488ff",
}


def _build_satellite_payload_real(dataset):
    """Build payload from real CelesTrak satellite data (no collision calc for large sets)."""
    satellites = []
    orbits = []
    high_risk_events = []
    asset_pricing = []
    high_risk_count = 0

    # Initialize global macro risk factors
    base_lam = 1e-5
    sev_mean = 50000000.0
    prc_ids = set()
    orbit_dyn_lam = None
    epi_norm = None
    # Load real-world conjunction data if available
    conj_path = Path(__file__).parents[2] / "data" / "detected_conjunctions.json"
    risk_ids = set()
    risk_map = {}
    if conj_path.exists():
        try:
            with conj_path.open("r", encoding="utf-8") as f:
                c_data = json.load(f)
                for c in c_data:
                    id1, id2 = int(c["id1"]), int(c["id2"])
                    risk_ids.add(id1)
                    risk_ids.add(id2)
                    if id1 not in risk_map: risk_map[id1] = []
                    if id2 not in risk_map: risk_map[id2] = []
                    risk_map[id1].append(c)
                    risk_map[id2].append(c)
        except Exception as e:
            print(f"Error loading conjunction data: {e}")

    prc_ids = set()
    if INSURANCE_ENABLED:
        import requests
        from src.ext_insurance.seiard_actuarial import simulate_seiard_nsfd
        try:
            print("Fetching PRC satellite list from CelesTrak (satcat)...")
            resp = requests.get("https://celestrak.org/pub/satcat.csv", timeout=30)
            for line in resp.text.splitlines():
                if ',PRC,' in line:
                    parts = line.split(',')
                    try:
                        prc_ids.add(int(parts[2].strip()))
                    except:
                        pass
            print(f"Loaded {len(prc_ids)} PRC satellites for actuarial computation.")
        except Exception as e:
            print(f"Failed to fetch PRC list: {e}")
            
        # Full time-series orbit dynamics (10yr, monthly steps = 120 steps)
        n_steps = 120
        dt_ins = 1.0 / 12.0
        orbit_dyn = simulate_orbit_dynamics({"T": n_steps, "dt": dt_ins})
        orbit_dyn_lam = orbit_dyn["lambda_collision"]  # array of 120 values
        base_lam = orbit_dyn_lam[0]
        
        # SEIARD epidemic-analogue claims stress index
        epi = simulate_seiard_nsfd({"T": n_steps, "dt": dt_ins,
            "init": [99500, 200, 150, 100, 50, 0],
            "beta_i": 0.55, "beta_a": 0.35, "kappa": 0.3, "p_sym": 0.7,
            "gamma_i": 0.18, "gamma_a": 0.2, "mu_i": 0.015,
            "claim_rate_i": 1.0, "claim_rate_a": 0.3, "claim_rate_d": 1.0
        })
        epi_idx = epi["claims_index"]
        epi_norm = epi_idx / max(1e-8, float(np.nanmean(epi_idx)))
        
        # Severity via GBMA-EVT
        rng = np.random.default_rng(123)
        losses = rng.lognormal(mean=11.2, sigma=0.95, size=5000)
        gbma = fit_gbma_threshold_model(losses)
        sev = expected_severity(gbma)
        sev_mean = sev["mean"]

    # Pre-define constant actuarial parameters outside the loop
    b_state_const = np.array([0.0, 400000.0, 0.0])
    trans_payment_const = np.array([[0.0, 0.0, 8000000.0], [0.0, 0.0, 8000000.0], [0.0, 0.0, 0.0]])
    dt_res = 1.0 / 12.0
    loading_const = 1.25 # (1 + 0.25)
    
    for i, sat in enumerate(dataset.satellites):
        sat_id = str(sat.norad_id)
        color = CATEGORY_COLORS.get(sat.category, "#00ffcc")
        alt_display = sat.alt  # Already in km from CelesTrak TLE data

        is_high_risk = sat.norad_id in risk_ids
        if is_high_risk:
            high_risk_count += 1
            # Add to high_risk_events (avoid duplicates by only adding when we are id1 or if id2 is not in dataset)
            for c in risk_map.get(sat.norad_id, []):
                # Using a simple heuristic to only add the event once: if we are the smaller ID
                if sat.norad_id == min(c["id1"], c["id2"]):
                    high_risk_events.append({
                        "asset_id": str(c["id1"]),
                        "counterpart_id": str(c["id2"]),
                        "tca_utc": c["tca"],
                        "miss_distance_km": c["dist"],
                        "poc": 1e-4 # SOCRATES threshold usually
                    })

        satellites.append({
            "id": sat_id,
            "name": sat.name,
            "norad_id": sat.norad_id,
            "category": sat.category,
            "lat": round(sat.lat, 6),
            "lng": round(sat.lng, 6),
            "alt": round(alt_display, 6),
            "radius": 0.8 if is_high_risk else 0.5,
            "color": "#ff0044" if is_high_risk else color,
            "is_high_risk": is_high_risk,
            "pof": 0.0,
            "suggested_premium": 0.0,
        })

        # Identify PRC (Chinese) satellites - check satcat CSV first, then fallback to name patterns
        is_prc = sat.norad_id in prc_ids
        if not is_prc:
            name_up = str(sat.name).upper()
            grp_up = str(sat.group).upper()
            prc_patterns = ["YAOGAN", "BEIDOU", "GAOFEN", "TIANGONG", "SHENZHOU", "CZ-", "SJ-", "HAIYANG", "FY-", "QUANZHOU", "TIANMU", "TIANPING", "SHIYAN", "XJS", "CHINASAT", "APSTAR"]
            if any(p in name_up for p in prc_patterns) or "QIANFAN" in grp_up or "CHINESE" in grp_up:
                is_prc = True

        orbits.append({
            "asset_id": sat_id,
            "name": sat.name,
            "norad_id": sat.norad_id,
            "category": sat.category,
            "group": sat.group,
            "is_prc": is_prc,
            "lat": round(sat.lat, 6),
            "lng": round(sat.lng, 6),
            "alt": round(alt_display, 6),
            "status": getattr(sat, "status", "active"),
            "line1": sat.line1,
            "line2": sat.line2,
        })
        
        # Calculate dynamic insurance metrics if enabled
        orbit_risk = None
        pc_after = None
        claim_int = None
        premium_rate = None
        reserve_val = None
        
        if INSURANCE_ENABLED:
            alt_km = max(1.0, alt_display)  # Altitude in km
            
            # --- (1) Altitude-dependent atmospheric density ---
            if alt_km < 200:
                rho = 2.5e-10
            elif alt_km < 400:
                rho = 1e-11 * math.exp(-(alt_km - 200) / 80.0)
            elif alt_km < 600:
                rho = 1e-12 * math.exp(-(alt_km - 400) / 100.0)
            elif alt_km < 1000:
                rho = 5e-14 * math.exp(-(alt_km - 600) / 200.0)
            else:
                rho = 1e-15  # MEO/GEO: essentially no drag
            
            # --- (2) Drag avoidance model (per-satellite) ---
            sat_mass = 120.0 if alt_km < 600 else (500.0 if alt_km < 2000 else 3000.0)
            sat_area_nom = 1.2 if alt_km < 600 else (4.0 if alt_km < 2000 else 12.0)
            sat_area_man = sat_area_nom * 2.5
            
            drag_cfg = {
                "rho": rho,
                "relative_speed": 7600.0 if alt_km < 2000 else 3100.0,
                "cd": 2.2,
                "area_nominal": sat_area_nom,
                "area_maneuver": sat_area_man,
                "mass": sat_mass,
                "drag_duration_sec": 43200,
                "time_to_tca_sec": 86400,
                "sigma_x": 50.0, "sigma_y": 50.0, "collision_radius": 5.0,
                "x_miss_nominal": 20.0, "y_miss_nominal": 5.0
            }
            drag_res = aerodynamic_maneuver_effect(drag_cfg)
            mitigation = drag_res["risk_reduction"]
            pc_after = drag_res["Pc_after"]
            
            # --- (3) Altitude-scaled orbit risk ---
            if alt_km < 400:
                alt_risk_factor = 0.5
            elif alt_km < 600:
                alt_risk_factor = 1.0 + (alt_km - 400) / 200.0
            elif alt_km < 1000:
                alt_risk_factor = 2.0 + (alt_km - 600) * 0.005
            elif alt_km < 2000:
                alt_risk_factor = 4.0 - (alt_km - 1000) * 0.003
            elif alt_km < 36000:
                alt_risk_factor = 1.0 
            else:
                alt_risk_factor = 0.3 
            
            orbit_risk = base_lam * alt_risk_factor
            
            # --- (4) Dynamic claim intensity (with SEIARD epidemic stress) ---
            base_claim_int = 0.06
            alpha_orbit = 2e-7
            beta_epi = 0.03
            epi_factor = float(epi_norm[min(i % len(epi_norm), len(epi_norm) - 1)]) if epi_norm is not None else 1.0
            
            claim_int_val = (base_claim_int 
                + alpha_orbit * orbit_risk * (1 - mitigation) 
                + beta_epi * (epi_factor - 1.0))
            claim_int_val = max(1e-6, claim_int_val)
            
            # --- (5) Premium ---
            premium = loading_const * claim_int_val * sev_mean
            
            claim_int = claim_int_val
            premium_rate = (premium / 100000000.0) * 100.0 
            
            # --- (6) Full Thiele reserve (10yr, monthly steps) ---
            l01 = min(0.5, 0.02 + 5e-8 * orbit_risk)
            l02 = min(0.5, claim_int_val)
            l12 = min(0.8, claim_int_val * 1.5)
            
            def trans_lam_internal(t):
                # Using constants from closure for speed
                return np.array([
                    [0.0, l01, l02],
                    [0.0, 0.0, l12],
                    [0.0, 0.0, 0.0]
                ])
            
            res = solve_thiele_reserve(
                T=10, dt=dt_res, r=0.02, b_state=b_state_const,
                trans_lambda=trans_lam_internal,
                trans_payment=trans_payment_const,
                terminal=np.array([0.0, 0.0, 0.0])
            )
            reserve_val = res[0, 0]

        if orbit_risk is not None:
            orbits[-1].update({
                "orbit_risk": orbit_risk,
                "pc_after": pc_after,
                "claim_int": claim_int,
                "premium_rate": premium_rate,
                "reserve": reserve_val
            })

        # Generate Survival Curve (use dynamic insurance claim_int if available, else a base default)
        surv_lambda = claim_int if claim_int is not None else 0.02
        
        asset_pricing.append({
            "asset_id": sat_id,
            "name": sat.name,
            "pof_12m": round(surv_lambda, 6),
            "expected_loss": round(surv_lambda * sev_mean if claim_int is not None else surv_lambda * 50_000_000, 2),
            "pure_premium": round(premium_rate * 1000000 if premium_rate is not None else surv_lambda * 50_000_000 * 1.25, 2),
            "survival_curve": [
                {"timeline_days": day, "survival_prob": round(math.exp(-surv_lambda * day / 365.0), 6)}
                for day in (0, 30, 90, 180, 270, 365, 730, 1825, 3650)  # Extended out to 10 years
            ],
        })
    # Category statistics
    category_stats = {}
    for sat in dataset.satellites:
        cat = sat.category
        if cat not in category_stats:
            category_stats[cat] = 0
        category_stats[cat] += 1

    return satellites, high_risk_count, orbits, high_risk_events, asset_pricing, category_stats


def _build_satellite_payload_simulated(dataset, pricing_results):
    """Build payload from simulated data (legacy mode with collision analysis)."""
    from src.engine.collision_math import OrbitalPropagator

    pricing_map = {item.asset_id: item for item in pricing_results}
    propagator = OrbitalPropagator(step_minutes=30)

    satellites = []
    orbits = []
    high_risk_events = []
    asset_pricing = []
    high_risk_count = 0

    tle_df = dataset.tle.reset_index(drop=True)

    tracks = {}
    for _, row in tle_df.iterrows():
        sat_id = row["id"]
        tracks[sat_id] = propagator.propagate_tle(
            line1=row["line1"],
            line2=row["line2"],
            start_time=dataset.generated_at,
            horizon_hours=24,
            step_minutes=30,
        )

    sat_ids = list(tracks.keys())
    for idx, sat_id in enumerate(sat_ids):
        track = tracks[sat_id]
        if track.empty:
            lat = lng = alt = 0.0
        else:
            latest = track.iloc[-1]
            lat = float(latest["lat"])
            lng = float(latest["lng"])
            alt = float(latest["alt"]) / 1000.0

        peer_id = sat_ids[(idx + 1) % len(sat_ids)]
        tca = propagator.calculate_tca(track, tracks[peer_id])
        is_high_risk = tca["risk_level"] == "High Risk"
        if is_high_risk:
            high_risk_count += 1

        price = pricing_map.get(sat_id)
        pof = float(price.pof_12m) if price else 0.0
        premium = float(price.pure_premium) if price else 0.0

        satellites.append({
            "id": sat_id,
            "name": sat_id,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "alt": round(alt, 6),
            "radius": 0.8 if is_high_risk else 0.5,
            "color": "#ff0044" if is_high_risk else "#00ffcc",
            "is_high_risk": is_high_risk,
            "pof": round(pof, 6),
            "suggested_premium": round(premium, 2),
        })

        orbits.append({
            "asset_id": sat_id,
            "name": sat_id,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "alt": round(alt, 6),
        })

        if is_high_risk:
            high_risk_events.append({
                "asset_id": sat_id,
                "counterpart_id": peer_id,
                "tca_utc": tca["tca"].replace(microsecond=0).isoformat() if tca["tca"] is not None else None,
                "miss_distance_km": round(float(tca["min_distance_km"]), 6),
                "poc": round(float(tca["poc"]), 8),
            })

        asset_pricing.append({
            "asset_id": sat_id,
            "pof_12m": round(pof, 6),
            "expected_loss": round(float(price.expected_loss), 2) if price else 0.0,
            "pure_premium": round(premium, 2),
            "survival_curve": [
                {"timeline_days": day, "survival_prob": round(math.exp(-pof * day / 365.0), 6)}
                for day in (0, 30, 90, 180, 270, 365)
            ],
        })

    return satellites, high_risk_count, orbits, high_risk_events, asset_pricing, {}


def run_engine(output_path: Path | None = None) -> Path:
    """执行全流程并输出 JSON 报告。"""

    final_path = output_path or (Path.cwd() / "data" / "daily_report.json")
    latest_tles_path = final_path.parent / "latest_tles.json"
    satellites_path = final_path.parent / "satellites.json"

    dataset = build_daily_dataset(
        count=300,
        real_tles_path=latest_tles_path,
        satellites_path=satellites_path,
    )

    if dataset.use_real_data:
        print(f"Using real satellite data: {len(dataset.satellites)} satellites from CelesTrak")
        satellites, high_risk_count, orbits, high_risk_events, asset_pricing, category_stats = (
            _build_satellite_payload_real(dataset)
        )
    else:
        print("No real satellite data found, using simulated data")
        from src.engine.actuarial_model import compute_asset_pricing
        pricing_results, _ = compute_asset_pricing(dataset.finance)
        satellites, high_risk_count, orbits, high_risk_events, asset_pricing, category_stats = (
            _build_satellite_payload_simulated(dataset, pricing_results)
        )

    status_text = "空间天气平稳"
    if dataset.weather["is_geomagnetic_storm"] >= 1:
        status_text = "地磁暴警报：所有低轨资产阻力飙升"
    elif dataset.use_real_data:
        status_text = f"实时监控中 | {len(satellites)} 颗卫星在轨"

    report = {
        "generated_at": dataset.generated_at,
        "hud_data": {
            "status": status_text,
            "high_risk_count": high_risk_count,
            "total_premium_var": _premium_var([s["suggested_premium"] for s in satellites]),
            "update_time": dataset.generated_at,
            "satellite_count": len(satellites),
            "category_stats": category_stats,
        },
        "satellites": satellites,
        "orbits": orbits,
        "high_risk_events": high_risk_events,
        "asset_pricing": asset_pricing,  # Removed 100 limit; provide full coverage for identified assets
    }

    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_path


if __name__ == "__main__":
    output = run_engine()
    print(f"已生成报告: {output}")
