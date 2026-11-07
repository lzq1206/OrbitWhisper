import unittest

from src.data.tle_parser import parse_bstar, parse_tle_record


class TestTleParser(unittest.TestCase):
    def test_parse_bstar_valid(self):
        line1 = "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994"
        bstar = parse_bstar(line1)
        self.assertAlmostEqual(bstar, 2.9677e-05, places=10)

    def test_parse_tle_record_extracts_core_features(self):
        payload = {
            "norad_id": 25544,
            "line1": "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994",
            "line2": "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823",
        }

        parsed = parse_tle_record(payload)
        self.assertEqual(parsed["norad_id"], 25544)
        self.assertAlmostEqual(parsed["bstar"], 2.9677e-05, places=10)
        self.assertAlmostEqual(parsed["inclination_deg"], 51.6418, places=4)


if __name__ == "__main__":
    unittest.main()
