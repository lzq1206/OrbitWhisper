import unittest

from src.data.tle_fetcher import SpaceTrackClient


class TestSpaceTrackClientParser(unittest.TestCase):
    def test_parse_tle_text_two_line_response(self):
        raw = (
            "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994\n"
            "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823\n"
        )
        parsed = SpaceTrackClient._parse_tle_text(raw)
        self.assertTrue(parsed["line1"].startswith("1 "))
        self.assertTrue(parsed["line2"].startswith("2 "))

    def test_parse_tle_text_three_line_response(self):
        raw = (
            "ISS (ZARYA)\n"
            "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994\n"
            "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823\n"
        )
        parsed = SpaceTrackClient._parse_tle_text(raw)
        self.assertTrue(parsed["line1"].startswith("1 "))
        self.assertTrue(parsed["line2"].startswith("2 "))


if __name__ == "__main__":
    unittest.main()
