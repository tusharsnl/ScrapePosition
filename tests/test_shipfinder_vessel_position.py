import unittest

from shipfinder_vessel_position import _parse_ais_table


class ParseAisTableTests(unittest.TestCase):
    def test_empty_status_does_not_shift_longitude(self):
        fields = _parse_ais_table(
            [
                "Type：\tContainer\tLat：\t51-03.843N",
                "Status：\t\tLon：\t13-21.438E",
            ]
        )

        self.assertEqual(fields["latitude"], "51-03.843N")
        self.assertEqual(fields["status"], "")
        self.assertEqual(fields["longitude"], "13-21.438E")

    def test_parses_two_populated_label_value_pairs(self):
        fields = _parse_ais_table(
            ["MMSI：\t636017569\tHeading：\t259.0Deg"]
        )

        self.assertEqual(fields["mmsi"], "636017569")
        self.assertEqual(fields["heading_deg"], "259.0Deg")


if __name__ == "__main__":
    unittest.main()
