"""Cox survival model and actuarial pure-premium utilities."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter


@dataclass
class OrbitCoxSurvivalModel:
    """Survival-analysis model for in-orbit asset failure probability.

    The model estimates hazard as:
        h(t|x) = h0(t) * exp(beta^T x + alpha_mfr + gamma_bus)
    where manufacturer/bus fixed-effects are captured by one-hot indicators.
    """

    duration_col: str = "duration_days"
    event_col: str = "event_observed"
    penalizer: float = 0.05

    def __post_init__(self) -> None:
        self.model = CoxPHFitter(penalizer=self.penalizer)
        self._training_columns: list[str] = []

    def _build_design_matrix(
        self,
        df: pd.DataFrame,
        feature_cols: list[str],
        fixed_effect_cols: list[str] | None = None,
    ) -> pd.DataFrame:
        missing = [c for c in [self.duration_col, self.event_col, *feature_cols] if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns for Cox model: {missing}")

        design = df[[self.duration_col, self.event_col, *feature_cols]].copy()
        fixed_effect_cols = fixed_effect_cols or []
        for col in fixed_effect_cols:
            if col not in df.columns:
                raise ValueError(f"Missing fixed-effect column: {col}")
            dummies = pd.get_dummies(df[col], prefix=col, drop_first=True, dtype=float)
            design = pd.concat([design, dummies], axis=1)

        return design.dropna(axis=0, how="any")

    def fit(
        self,
        df_panel: pd.DataFrame,
        feature_cols: list[str],
        fixed_effect_cols: list[str] | None = None,
    ) -> None:
        """Fit Cox proportional hazards model from panel-style satellite data."""
        design = self._build_design_matrix(df_panel, feature_cols, fixed_effect_cols)
        self.model.fit(design, duration_col=self.duration_col, event_col=self.event_col)
        self._training_columns = [c for c in design.columns if c not in [self.duration_col, self.event_col]]

    def predict_survival_curve(
        self,
        satellite_features: pd.DataFrame,
        horizon_days: int = 365,
        steps: int = 12,
    ) -> pd.DataFrame:
        """Predict forward survival curve for a satellite over future horizon.

        Returns a dataframe indexed by timeline(days) with one column per row in
        satellite_features.
        """
        if not self._training_columns:
            raise RuntimeError("Model must be fitted before prediction")
        if satellite_features.empty:
            raise ValueError("satellite_features cannot be empty")

        aligned = satellite_features.reindex(columns=self._training_columns, fill_value=0.0).astype(float)
        timeline = np.linspace(0, horizon_days, steps + 1).astype(int)
        survival = self.model.predict_survival_function(aligned, times=timeline)
        survival.index.name = "timeline_days"
        return survival

    def predict_pof_12m(self, satellite_features: pd.DataFrame) -> pd.Series:
        """Predict 12-month Probability of Failure: PoF = 1 - S(12m)."""
        survival = self.predict_survival_curve(satellite_features, horizon_days=365, steps=12)
        s_12m = survival.iloc[-1, :]
        return 1.0 - s_12m

    @staticmethod
    def expected_loss(pof: float, exposure_amount: float, lgf: float) -> float:
        """Compute actuarial expected loss EL = PoF * EA * LGF."""
        if not 0.0 <= pof <= 1.0:
            raise ValueError("pof must be in [0, 1]")
        if not 0.0 <= lgf <= 1.0:
            raise ValueError("lgf must be in [0, 1]")
        if exposure_amount < 0:
            raise ValueError("exposure_amount must be non-negative")
        return float(pof * exposure_amount * lgf)

    @staticmethod
    def pure_premium(pof: float, exposure_amount: float, lgf: float, loading: float = 0.0) -> float:
        """Compute pure premium with optional proportional loading."""
        if loading < 0:
            raise ValueError("loading must be non-negative")
        el = OrbitCoxSurvivalModel.expected_loss(pof, exposure_amount, lgf)
        return float(el * (1.0 + loading))
