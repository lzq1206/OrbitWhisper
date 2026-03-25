import unittest

import pandas as pd

from src.models.cox_survival import OrbitCoxSurvivalModel


class TestOrbitCoxSurvivalModel(unittest.TestCase):
    def test_fit_and_predict_pof_12m(self):
        panel = pd.DataFrame(
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
        model = OrbitCoxSurvivalModel()
        model.fit(
            panel,
            feature_cols=["f107", "kp_index", "altitude_decay_rate"],
            fixed_effect_cols=["manufacturer", "bus_type"],
        )

        scored = pd.DataFrame(
            [
                {
                    "f107": 110,
                    "kp_index": 4,
                    "altitude_decay_rate": 0.07,
                    "manufacturer_A": 0,
                    "manufacturer_B": 1,
                    "manufacturer_C": 0,
                    "bus_type_X": 0,
                    "bus_type_Y": 1,
                    "bus_type_Z": 0,
                }
            ]
        )
        pof = model.predict_pof_12m(scored)

        self.assertEqual(len(pof), 1)
        self.assertGreaterEqual(float(pof.iloc[0]), 0.0)
        self.assertLessEqual(float(pof.iloc[0]), 1.0)

    def test_expected_loss_and_pure_premium(self):
        el = OrbitCoxSurvivalModel.expected_loss(0.2, 100_000_000.0, 0.6)
        premium = OrbitCoxSurvivalModel.pure_premium(0.2, 100_000_000.0, 0.6, loading=0.15)

        self.assertAlmostEqual(el, 12_000_000.0)
        self.assertAlmostEqual(premium, 13_800_000.0)


if __name__ == "__main__":
    unittest.main()
