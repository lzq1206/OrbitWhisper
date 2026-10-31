import numpy as np


def simulate_orbit_dynamics(cfg: dict):
    """
    Paper anchor: arXiv:2202.07442 (The Economics of Orbit Use)
    Core idea reproduced:
      - endogenous collision risk from satellites/debris stocks
      - autocatalytic debris term (debris-debris collisions)
      - launch incentives decrease with effective collision discount
    """
    T = int(cfg.get("T", 240))
    dt = float(cfg.get("dt", 1.0 / 12.0))

    S = np.zeros(T + 1)
    D = np.zeros(T + 1)
    L = np.zeros(T)
    lam = np.zeros(T)

    S[0] = cfg.get("S0", 6000.0)
    D[0] = cfg.get("D0", 30000.0)

    # parameters
    k_sd = cfg.get("k_sd", 2.0e-9)      # satellite-debris collision kernel
    k_dd = cfg.get("k_dd", 0.8e-9)      # debris-debris collision kernel
    alpha_sd = cfg.get("alpha_sd", 8.0) # debris produced per S-D collision
    alpha_dd = cfg.get("alpha_dd", 4.0) # debris produced per D-D collision
    delta_s = cfg.get("delta_s", 0.10)  # retirement/deorbit rate
    delta_d = cfg.get("delta_d", 0.03)  # natural debris decay

    L0 = cfg.get("launch_base", 1500.0)
    phi = cfg.get("risk_sensitivity", 3.0e-5)
    growth = cfg.get("launch_trend", 0.01)

    for t in range(T):
        lam[t] = k_sd * S[t] * D[t] + k_dd * (D[t] ** 2)
        L[t] = max(0.0, L0 * np.exp(growth * t * dt - phi * lam[t]))

        sat_loss = k_sd * S[t] * D[t]
        dd_coll = k_dd * D[t] ** 2

        dS = (L[t] - delta_s * S[t] - sat_loss) * dt
        dD = (
            alpha_sd * sat_loss
            + alpha_dd * dd_coll
            + delta_s * S[t]
            - delta_d * D[t]
        ) * dt

        S[t + 1] = max(0.0, S[t] + dS)
        D[t + 1] = max(0.0, D[t] + dD)

    return {
        "S": S,
        "D": D,
        "L": L,
        "lambda_collision": lam,
        "time": np.arange(T + 1) * dt,
    }
