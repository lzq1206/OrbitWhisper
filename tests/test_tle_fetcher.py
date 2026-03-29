import unittest
from unittest.mock import Mock

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

    def test_get_latest_tle_by_ids_parses_json_payload(self):
        client = SpaceTrackClient.__new__(SpaceTrackClient)
        client.timeout = 5
        client._login = Mock()
        client.session = Mock()
        response = Mock()
        response.json.return_value = [
            {
                "NORAD_CAT_ID": "25544",
                "TLE_LINE1": "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994",
                "TLE_LINE2": "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823",
            }
        ]
        response.raise_for_status.return_value = None
        client.session.get.return_value = response

        rows = client.get_latest_tle_by_ids([25544])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["norad_id"], 25544)
        self.assertTrue(rows[0]["line1"].startswith("1 "))
        self.assertTrue(rows[0]["line2"].startswith("2 "))

    def test_parse_tle_blocks_parses_multiple_tle_pairs(self):
        raw = (
            "ISS (ZARYA)\n"
            "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994\n"
            "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823\n"
            "HST\n"
            "1 20580U 90037B   24068.52754500  .00001000  00000-0  12345-4 0  9990\n"
            "2 20580  28.4690 181.1200 0002999  40.0000 320.0000 15.09100000350000\n"
        )
        rows = SpaceTrackClient._parse_tle_blocks(raw)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["norad_id"], 25544)
        self.assertEqual(rows[1]["norad_id"], 20580)
        self.assertTrue(rows[0]["line1"].startswith("1 "))
        self.assertTrue(rows[0]["line2"].startswith("2 "))

    def test_get_public_file_tles_by_ids_parses_plain_tle_text(self):
        client = SpaceTrackClient.__new__(SpaceTrackClient)
        client.timeout = 5
        client._login = Mock()
        client.session = Mock()
        response = Mock()
        response.text = (
            "1 25544U 98067A   24068.52754500  .00020000  00000-0  29677-4 0  9994\n"
            "2 25544  51.6418  72.8432 0004908  56.6248  85.7564 15.50000000444823\n"
        )
        response.raise_for_status.return_value = None
        client.session.get.return_value = response

        rows = client.get_public_file_tles_by_ids([25544])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["norad_id"], 25544)
        self.assertTrue(rows[0]["line1"].startswith("1 "))
        self.assertTrue(rows[0]["line2"].startswith("2 "))


if __name__ == "__main__":
    unittest.main()
