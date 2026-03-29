import numpy as np


def pc_2d_gaussian(x_miss, y_miss, sigma_x, sigma_y, r_c):
    """
    Foster-type approximation in B-plane:
    Pc ≈ (r_c^2 / (2πσxσy)) * exp(-0.5[(x/σx)^2 + (y/σy)^2])
    """
    z = 0.5 * ((x_miss / sigma_x) ** 2 + (y_miss / sigma_y) ** 2)
    return (r_c ** 2 / (2.0 * np.pi * sigma_x * sigma_y)) * np.exp(-z)


def aerodynamic_maneuver_effect(cfg: dict):
    """
    Paper anchor: arXiv:2302.06893 (aerodynamic drag avoidance)
    Reproduced mechanics:
      - drag acceleration change via area-to-mass ratio
      - along-track miss distance gain before TCA
      - resulting collision probability reduction
    """
    rho = cfg.get("rho", 1e-11)          # kg/m^3
    v = cfg.get("relative_speed", 7600.) # m/s
    cd = cfg.get("cd", 2.2)
    A_nom = cfg.get("area_nominal", 1.2)
    A_man = cfg.get("area_maneuver", 3.0)
    mass = cfg.get("mass", 120.)
    t_drag = cfg.get("drag_duration_sec", 12 * 3600)
    t_to_tca = cfg.get("time_to_tca_sec", 24 * 3600)

    a_nom = 0.5 * rho * cd * (A_nom / mass) * v ** 2
    a_man = 0.5 * rho * cd * (A_man / mass) * v ** 2
    delta_a = max(0.0, a_man - a_nom)
    delta_v = delta_a * t_drag
    delta_s = delta_v * t_to_tca

    sigma_x = cfg.get("sigma_x", 50.0)
    sigma_y = cfg.get("sigma_y", 50.0)
    rc = cfg.get("collision_radius", 5.0)
    x0 = cfg.get("x_miss_nominal", 20.0)
    y0 = cfg.get("y_miss_nominal", 5.0)

    pc_before = pc_2d_gaussian(x0, y0, sigma_x, sigma_y, rc)
    pc_after = pc_2d_gaussian(x0 + delta_s, y0, sigma_x, sigma_y, rc)

    reduction = 1.0 - (pc_after / pc_before if pc_before > 0 else 0.0)
    return {
        "delta_s_m": delta_s,
        "Pc_before": pc_before,
        "Pc_after": pc_after,
        "risk_reduction": float(np.clip(reduction, 0.0, 1.0)),
    }
