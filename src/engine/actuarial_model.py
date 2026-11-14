"""轨道资产精算定价模块：VIF + Cox 生存分析 + 动态保费。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from lifelines import CoxPHFitter


@dataclass
class AssetPricingResult:
    """单颗卫星的定价输出。"""

    asset_id: str
    pof_12m: float
    expected_loss: float
    pure_premium: float


class SpaceActuary:
    """航天保险精算器。"""

    def __init__(self, duration_col: str = "duration_days", event_col: str = "event_observed", penalizer: float = 0.1) -> None:
        self.duration_col = duration_col
        self.event_col = event_col
        self.model = CoxPHFitter(penalizer=penalizer)
        self._feature_columns: list[str] = []

    def check_collinearity(self, df: pd.DataFrame, threshold: float = 10.0) -> tuple[pd.DataFrame, pd.DataFrame]:
        """执行 VIF 检验并自动剔除高共线变量。

        说明：
        - 对所有数值特征计算 VIF（方差膨胀因子）
        - 迭代删除当前 VIF 最大且 > threshold 的变量
        - 返回：过滤后的特征矩阵 + 全量报告（kept/dropped）
        """

        from statsmodels.stats.outliers_influence import variance_inflation_factor

        numeric = df.select_dtypes(include=["number"]).copy()
        if numeric.empty:
            raise ValueError("VIF 检验需要至少一个数值特征")
        numeric = numeric.dropna(axis=0, how="any")
        if numeric.shape[0] < 3:
            raise ValueError("样本数不足，无法稳定估计 VIF")

        dropped: list[dict[str, Any]] = []

        def _vif_table(x: pd.DataFrame) -> pd.DataFrame:
            if x.shape[1] == 1:
                return pd.DataFrame([{"feature": x.columns[0], "vif": 1.0}])
            rows = []
            for i, col in enumerate(x.columns):
                try:
                    vif_val = float(variance_inflation_factor(x.values, i))
                except (ValueError, ZeroDivisionError):
                    vif_val = float("inf")
                rows.append({"feature": col, "vif": vif_val})
            return pd.DataFrame(rows).sort_values("vif", ascending=False).reset_index(drop=True)

        filtered = numeric.copy()
        while filtered.shape[1] > 1:
            vif_table = _vif_table(filtered)
            top = vif_table.iloc[0]
            if float(top["vif"]) <= threshold:
                break
            feature = str(top["feature"])
            dropped.append({"feature": feature, "vif": float(top["vif"]), "status": "dropped"})
            filtered = filtered.drop(columns=[feature])

        kept_table = _vif_table(filtered).assign(status="kept")
        report = pd.concat([kept_table, pd.DataFrame(dropped)], ignore_index=True)
        report = report.sort_values(["status", "vif"], ascending=[True, False]).reset_index(drop=True)
        return filtered, report

    def fit_survival_model(self, df: pd.DataFrame, feature_cols: list[str]) -> None:
        """拟合 Cox 生存模型，估计失效风险。"""

        required = [self.duration_col, self.event_col, *feature_cols]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"缺少生存模型必要字段: {missing}")

        fit_df = df[required].dropna(axis=0, how="any").copy()
        if fit_df.empty:
            raise ValueError("生存模型训练数据为空")
        self.model.fit(fit_df, duration_col=self.duration_col, event_col=self.event_col)
        self._feature_columns = feature_cols.copy()

    def predict_pof(self, feature_df: pd.DataFrame, horizon_days: int = 365) -> pd.Series:
        """计算基础失效概率 PoF = 1 - S(t)。"""

        if not self._feature_columns:
            raise RuntimeError("请先调用 fit_survival_model")
        aligned = feature_df.reindex(columns=self._feature_columns, fill_value=0.0).astype(float)
        survival = self.model.predict_survival_function(aligned, times=[horizon_days])
        s_t = survival.iloc[-1, :]
        return 1.0 - s_t

    @staticmethod
    def calculate_premium(pof: float, exposure_amount: float, lgf: float) -> float:
        """纯保费公式：EL = PoF × EA × LGF。"""

        if not 0.0 <= pof <= 1.0:
            raise ValueError("pof 必须在 [0,1] 区间")
        if exposure_amount < 0:
            raise ValueError("exposure_amount 必须非负")
        if not 0.0 <= lgf <= 1.0:
            raise ValueError("lgf 必须在 [0,1] 区间")
        return float(pof * exposure_amount * lgf)


def _prepare_actuarial_features(fin_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    base_numeric = fin_df[["f107", "kp_index", "solar_wind_index", "asset_age_years", "health_score"]].copy()

    actuary = SpaceActuary()
    vif_filtered, vif_report = actuary.check_collinearity(base_numeric, threshold=10.0)

    model_df = pd.concat(
        [
            fin_df[["duration_days", "event_observed"]].reset_index(drop=True),
            vif_filtered.reset_index(drop=True),
        ],
        axis=1,
    )
    feature_cols = vif_filtered.columns.tolist()
    return model_df, feature_cols, vif_report


def compute_asset_pricing(finance_df: pd.DataFrame) -> tuple[list[AssetPricingResult], pd.DataFrame]:
    """批量计算卫星资产定价。"""

    if finance_df.empty:
        return [], pd.DataFrame(columns=["feature", "vif", "status"])

    model_df, feature_cols, vif_report = _prepare_actuarial_features(finance_df)

    actuary = SpaceActuary()
    actuary.fit_survival_model(model_df, feature_cols)

    scored_features = model_df[feature_cols].copy()
    pof_series = actuary.predict_pof(scored_features, horizon_days=365)

    results: list[AssetPricingResult] = []
    for idx, row in finance_df.reset_index(drop=True).iterrows():
        pof = float(pof_series.iloc[idx])
        premium = SpaceActuary.calculate_premium(
            pof=pof,
            exposure_amount=float(row["exposure_amount"]),
            lgf=float(row["lgf"]),
        )
        results.append(
            AssetPricingResult(
                asset_id=str(row["id"]),
                pof_12m=pof,
                expected_loss=premium,
                pure_premium=premium,
            )
        )

    return results, vif_report
