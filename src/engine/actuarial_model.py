"""Actuarial pricing scaffolding for AstroQuant 3D."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.models.cox_survival import OrbitCoxSurvivalModel


@dataclass
class AssetPricingResult:
    asset_id: str
    pof_12m: float
    expected_loss: float
    pure_premium: float
    survival_curve: list[dict[str, float]]
    panel_effects_note: str


def _build_training_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "duration_days": [120, 240, 180, 365, 300, 90, 210, 330],
            "event_observed": [1, 0, 1, 0, 0, 1, 0, 1],
            "f107": [95, 102, 108, 90, 99, 112, 101, 115],
            "kp_index": [2, 3, 4, 2, 3, 5, 2, 4],
            "altitude_decay_rate": [0.05, 0.03, 0.07, 0.02, 0.04, 0.08, 0.03, 0.06],
            "manufacturer": ["A", "A", "B", "B", "A", "C", "C", "B"],
            "bus_type": ["X", "Y", "X", "Y", "X", "Z", "Z", "Y"],
        }
    )


def _build_scoring_set(tle_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in tle_df.iterrows():
        if row["asset_id"].endswith("1"):
            rows.append({"f107": 110, "kp_index": 4, "altitude_decay_rate": 0.07, "manufacturer": "B", "bus_type": "Y"})
        else:
            rows.append({"f107": 102, "kp_index": 3, "altitude_decay_rate": 0.04, "manufacturer": "A", "bus_type": "X"})
    return pd.DataFrame(rows)


def compute_asset_pricing(tle_df: pd.DataFrame) -> list[AssetPricingResult]:
    """Fit Cox model and produce per-asset actuarial pricing metrics.

    Fixed effects for panel data are encoded through manufacturer/bus one-hot
    variables during model fitting.
    """

    if tle_df.empty:
        return []

    model = OrbitCoxSurvivalModel()
    panel = _build_training_panel()
    feature_cols = ["f107", "kp_index", "altitude_decay_rate"]
    fixed_effect_cols = ["manufacturer", "bus_type"]
    model.fit(panel, feature_cols=feature_cols, fixed_effect_cols=fixed_effect_cols)

    scoring = _build_scoring_set(tle_df)
    scored_design = model._build_design_matrix(
        pd.concat(
            [
                pd.DataFrame({"duration_days": [365] * len(scoring), "event_observed": [0] * len(scoring)}),
                scoring,
            ],
            axis=1,
        ),
        feature_cols=feature_cols,
        fixed_effect_cols=fixed_effect_cols,
    )
    scored_features = scored_design.drop(columns=["duration_days", "event_observed"])
    pof = model.predict_pof_12m(scored_features)
    survival = model.predict_survival_curve(scored_features, horizon_days=365, steps=12)

    results: list[AssetPricingResult] = []
    for idx, asset_id in enumerate(tle_df["asset_id"].tolist()):
        pof_i = float(pof.iloc[idx])
        expected_loss = model.expected_loss(pof_i, exposure_amount=120_000_000.0, lgf=0.55)
        pure_premium = model.pure_premium(pof_i, exposure_amount=120_000_000.0, lgf=0.55, loading=0.18)
        survival_curve = [
            {"timeline_days": float(timeline), "survival_prob": float(survival.iloc[t_idx, idx])}
            for t_idx, timeline in enumerate(survival.index.tolist())
        ]
        results.append(
            AssetPricingResult(
                asset_id=asset_id,
                pof_12m=pof_i,
                expected_loss=expected_loss,
                pure_premium=pure_premium,
                survival_curve=survival_curve,
                panel_effects_note="Fixed effects handled via one-hot dummies for manufacturer and bus_type.",
            )
        )
    return results

