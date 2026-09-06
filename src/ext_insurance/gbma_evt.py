import numpy as np


def fit_lognormal(x):
    x = np.asarray(x)
    x = x[x > 0]
    lx = np.log(x)
    mu, sig = lx.mean(), max(1e-6, lx.std(ddof=1))
    return mu, sig


def lognormal_logpdf(x, mu, sig):
    x = np.maximum(x, 1e-12)
    return -np.log(x * sig * np.sqrt(2 * np.pi)) - ((np.log(x) - mu) ** 2) / (2 * sig ** 2)


def fit_gpd_mom(y):
    y = np.asarray(y)
    y = y[y > 0]
    if len(y) < 5:
        return 0.1, max(1e-6, y.mean() if len(y) else 1.0)
    m = y.mean()
    v = y.var(ddof=1)
    if v <= m * m:
        xi = 0.01
    else:
        xi = 0.5 * (1.0 - (m * m / v))
    xi = float(np.clip(xi, -0.2, 0.49))
    beta = float(max(1e-6, m * (1 - xi)))
    return xi, beta


def gpd_logpdf(y, xi, beta):
    y = np.maximum(y, 1e-12)
    if abs(xi) < 1e-8:
        return -np.log(beta) - y / beta
    z = 1 + xi * y / beta
    z = np.maximum(z, 1e-12)
    return -np.log(beta) - (1 / xi + 1) * np.log(z)


def fit_gbma_threshold_model(losses, quantiles=(0.85, 0.9, 0.92, 0.95, 0.97)):
    """
    Paper anchor: arXiv:2504.20216
    Generalized BMA over multiple POT thresholds.
    """
    x = np.asarray(losses, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    n = len(x)
    models = []

    for q in quantiles:
        u = float(np.quantile(x, q))
        bulk = x[x <= u]
        tail = x[x > u] - u
        if len(bulk) < 10 or len(tail) < 10:
            continue

        mu, sig = fit_lognormal(bulk)
        xi, beta = fit_gpd_mom(tail)

        ll_bulk = lognormal_logpdf(bulk, mu, sig).sum()
        ll_tail = gpd_logpdf(tail, xi, beta).sum()
        ll = ll_bulk + ll_tail

        k = 5
        bic = -2 * ll + k * np.log(n)
        models.append({
            "q": q, "u": u, "mu": mu, "sig": sig, "xi": xi, "beta": beta,
            "ll": ll, "bic": bic,
        })

    if not models:
        raise ValueError("No valid threshold model could be fit.")

    bics = np.array([m["bic"] for m in models])
    rel = np.exp(-0.5 * (bics - bics.min()))
    w = rel / rel.sum()
    for i, m in enumerate(models):
        m["weight"] = float(w[i])

    return models


def expected_severity(models, n_mc=200000, seed=42):
    rng = np.random.default_rng(seed)
    out = []
    for m in models:
        u, mu, sig, xi, beta, w = m["u"], m["mu"], m["sig"], m["xi"], m["beta"], m["weight"]
        z = rng.lognormal(mu, sig, n_mc)
        mask = z > u
        if abs(xi) < 1e-8:
            excess = rng.exponential(beta, n_mc)
        else:
            u01 = rng.uniform(size=n_mc)
            excess = beta / xi * ((1 - u01) ** (-xi) - 1)
        z[mask] = u + excess[mask]
        out.append(w * z)
    sample = np.sum(out, axis=0)
    return {
        "mean": float(np.mean(sample)),
        "var95": float(np.quantile(sample, 0.95)),
        "tvar95": float(sample[sample >= np.quantile(sample, 0.95)].mean()),
    }
