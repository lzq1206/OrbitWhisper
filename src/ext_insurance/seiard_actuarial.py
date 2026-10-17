import numpy as np


def simulate_seiard_nsfd(cfg: dict):
    """
    Paper anchor: arXiv:2508.06580 (SEIARD actuarial integration)
    Uses NSFD-style discrete update for compartment dynamics and insurance quantities.
    """
    T = int(cfg.get("T", 240))
    dt = float(cfg.get("dt", 1.0 / 12.0))

    S = np.zeros(T + 1)
    E = np.zeros(T + 1)
    I = np.zeros(T + 1)
    A = np.zeros(T + 1)
    R = np.zeros(T + 1)
    D = np.zeros(T + 1)

    S[0], E[0], I[0], A[0], R[0], D[0] = cfg.get("init", [99500, 200, 150, 100, 50, 0])

    beta_i = cfg.get("beta_i", 0.55)
    beta_a = cfg.get("beta_a", 0.35)
    kappa = cfg.get("kappa", 0.30)
    p_sym = cfg.get("p_sym", 0.70)
    gamma_i = cfg.get("gamma_i", 0.18)
    gamma_a = cfg.get("gamma_a", 0.20)
    mu_i = cfg.get("mu_i", 0.015)

    claims = np.zeros(T)
    q_i = cfg.get("claim_rate_i", 1.0)
    q_a = cfg.get("claim_rate_a", 0.3)
    q_d = cfg.get("claim_rate_d", 1.0)

    for t in range(T):
        N = max(1.0, S[t] + E[t] + I[t] + A[t] + R[t])
        force = (beta_i * I[t] + beta_a * A[t]) / N

        S[t + 1] = (S[t]) / (1.0 + dt * force)
        E[t + 1] = (E[t] + dt * force * S[t]) / (1.0 + dt * kappa)
        I[t + 1] = (I[t] + dt * p_sym * kappa * E[t + 1]) / (1.0 + dt * (gamma_i + mu_i))
        A[t + 1] = (A[t] + dt * (1 - p_sym) * kappa * E[t + 1]) / (1.0 + dt * gamma_a)
        R[t + 1] = R[t] + dt * (gamma_i * I[t + 1] + gamma_a * A[t + 1])
        D[t + 1] = D[t] + dt * (mu_i * I[t + 1])

        dD = D[t + 1] - D[t]
        claims[t] = q_i * I[t + 1] + q_a * A[t + 1] + q_d * dD

    return {
        "S": S, "E": E, "I": I, "A": A, "R": R, "D": D,
        "claims_index": claims,
        "time": np.arange(T + 1) * dt,
    }
