"""Machine-learning residual corrector for SGP4 propagation errors."""

from __future__ import annotations

from dataclasses import dataclass

import joblib
import pandas as pd
from sklearn.multioutput import MultiOutputRegressor
from xgboost import XGBRegressor


@dataclass
class ResidualPredictor:
    """Multi-output regressor for ΔX/ΔY/ΔZ residuals.

    For time-series data, prefer non-shuffled split (e.g., walk-forward)
    instead of random K-fold to avoid temporal leakage.
    """

    random_state: int = 42

    def __post_init__(self) -> None:
        self.model = MultiOutputRegressor(
            XGBRegressor(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                objective="reg:squarederror",
                random_state=self.random_state,
                n_jobs=1,
            )
        )

    def prepare_features(self, df_tle: pd.DataFrame, df_space_weather: pd.DataFrame) -> pd.DataFrame:
        """Build aligned ML features from TLE and space weather data."""
        tle = df_tle.copy()
        sw = df_space_weather.copy()

        tle["timestamp"] = pd.to_datetime(tle["timestamp"], utc=True)
        sw["timestamp"] = pd.to_datetime(sw["timestamp"], utc=True)

        merged = pd.merge_asof(
            tle.sort_values("timestamp"),
            sw.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
        )

        required = ["bstar", "inclination_deg", "f107", "kp_index"]
        missing = [c for c in required if c not in merged.columns]
        if missing:
            raise ValueError(f"Missing required feature columns: {missing}")

        return merged[required].astype(float)

    def train_model(self, X_train: pd.DataFrame, y_train: pd.DataFrame) -> None:
        self.model.fit(X_train, y_train)

    def predict(self, X_test: pd.DataFrame):
        return self.model.predict(X_test)

    def save_model(self, path: str) -> None:
        joblib.dump(self.model, path)

    def load_model(self, path: str) -> None:
        self.model = joblib.load(path)
