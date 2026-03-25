import unittest

import numpy as np
import pandas as pd

from src.empirical.vif_tester import VIFTester


class TestVIFTester(unittest.TestCase):
    def test_compute_vif_returns_feature_table(self):
        df = pd.DataFrame(
            {
                "f107": [100, 105, 110, 115, 120, 125],
                "kp_index": [2, 3, 2, 4, 3, 5],
                "altitude_decay": [0.2, 0.25, 0.21, 0.29, 0.27, 0.31],
            }
        )
        tester = VIFTester(threshold=10.0)

        vif_table = tester.compute_vif(df)

        self.assertEqual(set(vif_table.columns), {"feature", "vif"})
        self.assertEqual(set(vif_table["feature"]), {"f107", "kp_index", "altitude_decay"})

    def test_drop_high_vif_removes_collinear_feature(self):
        x = np.arange(1, 21, dtype=float)
        df = pd.DataFrame(
            {
                "solar_flux": x,
                "solar_flux_scaled": 2.0 * x + 0.001,
                "geomagnetic_kp": np.linspace(1.0, 5.0, 20),
            }
        )
        tester = VIFTester(threshold=10.0)

        filtered, report = tester.drop_high_vif(df)

        self.assertLess(filtered.shape[1], df.shape[1])
        self.assertIn("status", report.columns)
        self.assertIn("dropped", set(report["status"]))


if __name__ == "__main__":
    unittest.main()

