"""Variance Inflation Factor (VIF) diagnostics for panel features."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from statsmodels.stats.outliers_influence import variance_inflation_factor


@dataclass
class VIFTester:
    """Run iterative VIF diagnostics and filter redundant variables.

    Statistical note:
    VIF_j = 1 / (1 - R_j^2), where R_j^2 is from regressing feature j on
    all other explanatory variables. A high VIF indicates feature j can be
    almost linearly reconstructed by others, inflating estimator variance
    and destabilizing inference for underwriting risk factor attribution.
    """

    threshold: float = 10.0

    def _prepare_numeric(self, df_features: pd.DataFrame) -> pd.DataFrame:
        numeric = df_features.select_dtypes(include=["number"]).copy()
        if numeric.empty:
            raise ValueError("No numeric features available for VIF diagnostics")
        if numeric.isnull().any().any():
            numeric = numeric.dropna(axis=0, how="any")
        if numeric.shape[0] < 3:
            raise ValueError("Insufficient samples for VIF diagnostics")
        return numeric

    def compute_vif(self, df_features: pd.DataFrame) -> pd.DataFrame:
        """Compute VIF values for all numeric columns."""
        X = self._prepare_numeric(df_features)
        if X.shape[1] == 1:
            return pd.DataFrame([{"feature": X.columns[0], "vif": 1.0}])
        vif_rows = []
        for i, col in enumerate(X.columns):
            try:
                vif_value = float(variance_inflation_factor(X.values, i))
            except (ValueError, ZeroDivisionError):
                vif_value = float("inf")
            vif_rows.append({"feature": col, "vif": vif_value})
        return pd.DataFrame(vif_rows).sort_values("vif", ascending=False).reset_index(drop=True)

    def drop_high_vif(self, df_features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Iteratively remove features with VIF above threshold.

        Returns:
            (filtered_features, vif_report)
        """
        X = self._prepare_numeric(df_features)
        dropped: list[str] = []

        while X.shape[1] > 1:
            vif_table = self.compute_vif(X)
            max_row = vif_table.iloc[0]
            if float(max_row["vif"]) <= self.threshold:
                break
            to_drop = str(max_row["feature"])
            dropped.append(to_drop)
            X = X.drop(columns=[to_drop])

        final_vif = self.compute_vif(X)
        dropped_report = pd.DataFrame({"feature": dropped, "vif": float("nan"), "status": "dropped"})
        kept_report = final_vif.assign(status="kept")
        vif_report = pd.concat([kept_report, dropped_report], ignore_index=True)
        return X, vif_report
