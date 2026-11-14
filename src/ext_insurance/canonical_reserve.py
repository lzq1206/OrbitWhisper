import numpy as np


def solve_thiele_reserve(T, dt, r, b_state, trans_lambda, trans_payment=None, terminal=None):
    """
    Paper anchor: arXiv:2411.12522
    Canonical stochastic Thiele structure (deterministic intensity implementation).
    Backward Euler on state-wise reserve equation.
    """
    b_state = np.asarray(b_state, dtype=float)
    n_state = len(b_state)
    n_step = int(T / dt)

    if trans_payment is None:
        trans_payment = np.zeros((n_state, n_state))
    if terminal is None:
        terminal = np.zeros(n_state)

    V = np.zeros((n_step + 1, n_state))
    V[n_step, :] = terminal

    for k in range(n_step - 1, -1, -1):
        lam = trans_lambda(k * dt)  # matrix [i,j]
        cur = V[k + 1].copy()
        next_v = np.zeros(n_state)

        for i in range(n_state):
            jump = 0.0
            for j in range(n_state):
                if j == i:
                    continue
                jump += lam[i, j] * (trans_payment[i, j] + cur[j] - cur[i])
            dv = r * cur[i] - b_state[i] - jump
            next_v[i] = max(0.0, cur[i] - dt * dv)

        V[k, :] = next_v

    return V


def simulate_surplus_path(T, dt, u0, premium_t, claim_int_t, sev_mean, r=0.02, sigma=0.10, seed=7):
    """Canonical insurance surplus with diffusion and jump claims."""
    rng = np.random.default_rng(seed)
    n = int(T / dt)
    U = np.zeros(n + 1)
    U[0] = u0

    for k in range(n):
        lam = max(0.0, claim_int_t[k])
        n_claim = rng.poisson(lam * dt)
        claim = n_claim * max(0.0, rng.lognormal(np.log(max(1e-8, sev_mean)) - 0.5, 1.0))
        dW = rng.normal(0.0, np.sqrt(dt))
        drift = (premium_t[k] - lam * sev_mean + r * U[k]) * dt
        diff = sigma * U[k] * dW
        U[k + 1] = U[k] + drift + diff - claim

    return U
