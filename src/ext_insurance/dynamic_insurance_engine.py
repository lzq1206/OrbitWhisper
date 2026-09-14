import numpy as np
import pandas as pd

from .debris_economics import simulate_orbit_dynamics
from .drag_avoidance import aerodynamic_maneuver_effect
from .seiard_actuarial import simulate_seiard_nsfd
from .gbma_evt import fit_gbma_threshold_model, expected_severity
from .canonical_reserve import solve_thiele_reserve, simulate_surplus_path
from .external_factors import build_external_factor_series


def build_dynamic_satellite_insurance_model(cfg: dict, fetch_results: dict = None):
    """
    Integrated actuarial engine for in-orbit satellites.
    Components are mapped one-to-one to the 5-paper method stack.
    """
    T_year = cfg.get("horizon_year", 10)
    dt = cfg.get("dt", 1 / 12)
    n = int(T_year / dt)

    # (1) Orbit risk dynamics
    orbit = simulate_orbit_dynamics({**cfg.get("orbit", {}), "T": n, "dt": dt})

    # (2) Maneuver risk mitigation
    drag = aerodynamic_maneuver_effect(cfg.get("drag", {}))
    mitigation = drag["risk_reduction"]

    # (3) Frequency stress from SEIARD analog process
    epi = simulate_seiard_nsfd({**cfg.get("seiard", {}), "T": n, "dt": dt})
    epi_idx = epi["claims_index"]
    epi_norm = epi_idx / max(1e-8, np.nanmean(epi_idx))

    # (4) Severity via GBMA-EVT
    losses = np.asarray(cfg.get("historical_losses", []), dtype=float)
    if losses.size < 200:
        rng = np.random.default_rng(123)
        losses = rng.lognormal(mean=11.2, sigma=0.95, size=5000)
    gbma = fit_gbma_threshold_model(losses)
    sev = expected_severity(gbma)

    # External factors from live APIs
    factors = build_external_factor_series(fetch_results or {}, n)

    # (5) Dynamic premium and reserve
    base_claim_int = cfg.get("base_claim_intensity", 0.06)
    alpha_orbit = cfg.get("alpha_orbit", 2e-7)
    beta_epi = cfg.get("beta_epi", 0.03)

    lam_orbit = orbit["lambda_collision"][:n]
    claim_int = base_claim_int + alpha_orbit * lam_orbit * (1 - mitigation) + beta_epi * (epi_norm - 1)
    claim_int = claim_int * factors["combined_factor"]
    claim_int = np.clip(claim_int, 1e-6, None)

    loading = cfg.get("safety_loading", 0.25)
    premium_t = (1 + loading) * claim_int * sev["mean"]

    b_state = np.array([cfg.get("benefit_oper", 0.0), cfg.get("benefit_deg", 4e5), 0.0])

    def trans_lambda(t):
        k = min(int(t / dt), n - 1)
        lam01 = min(0.5, 0.02 + 5e-8 * lam_orbit[k])
        lam02 = min(0.5, claim_int[k])
        lam12 = min(0.8, claim_int[k] * 1.5)
        return np.array([
            [0.0, lam01, lam02],
            [0.0, 0.0, lam12],
            [0.0, 0.0, 0.0],
        ])

    trans_payment = np.array([
        [0.0, 0.0, cfg.get("payout_total_loss", 8e6)],
        [0.0, 0.0, cfg.get("payout_total_loss", 8e6)],
        [0.0, 0.0, 0.0],
    ])

    reserve = solve_thiele_reserve(
        T=T_year,
        dt=dt,
        r=cfg.get("interest", 0.02),
        b_state=b_state,
        trans_lambda=trans_lambda,
        trans_payment=trans_payment,
        terminal=np.array([0.0, 0.0, 0.0]),
    )

    surplus = simulate_surplus_path(
        T=T_year,
        dt=dt,
        u0=cfg.get("initial_capital", 3e7),
        premium_t=premium_t,
        claim_int_t=claim_int,
        sev_mean=sev["mean"],
        r=cfg.get("interest", 0.02),
        sigma=cfg.get("surplus_vol", 0.12),
    )

    t = np.arange(n) * dt
    df = pd.DataFrame({
        "time_year": t,
        "collision_intensity": lam_orbit,
        "claim_intensity": claim_int,
        "premium": premium_t,
        "reserve_normal": reserve[:n, 0],
        "reserve_degraded": reserve[:n, 1],
        "surplus": surplus[:n],
        "external_factor": factors["combined_factor"],
    })

    summary = {
        "severity_mean": sev["mean"],
        "severity_var95": sev["var95"],
        "severity_tvar95": sev["tvar95"],
        "drag_risk_reduction": mitigation,
        "final_surplus": float(surplus[-1]),
        "max_claim_intensity": float(np.max(claim_int)),
        "max_premium": float(np.max(premium_t)),
        "external_factor_mean": float(np.mean(factors["combined_factor"])),
    }

    return df, summary, gbma
