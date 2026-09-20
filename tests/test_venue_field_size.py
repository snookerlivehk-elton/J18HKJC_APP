"""Venue field-size helpers (HV≤12 / ST≤14)."""
from __future__ import annotations

import unittest


class VenueFieldSizeTest(unittest.TestCase):
    def test_caps_and_race_id(self):
        from jjjc_export_common import (
            field_size_issues,
            horse_no_allowed_for_venue,
            max_horse_no_for_venue,
            venue_from_race_id,
        )

        self.assertEqual(max_horse_no_for_venue("HV"), 12)
        self.assertEqual(max_horse_no_for_venue("ST"), 14)
        self.assertEqual(venue_from_race_id("20260909HV01"), "HV")
        self.assertEqual(venue_from_race_id("20260906ST01"), "ST")
        self.assertTrue(horse_no_allowed_for_venue(12, "HV"))
        self.assertFalse(horse_no_allowed_for_venue(13, "HV"))
        self.assertTrue(horse_no_allowed_for_venue(14, "ST"))
        self.assertFalse(horse_no_allowed_for_venue(15, "ST"))

        issues = field_size_issues("HV", [1, 7, 13, 14], race_id="20260909HV01")
        self.assertTrue(any("13" in x or "14" in x for x in issues))
        self.assertEqual(field_size_issues("HV", list(range(1, 13))), [])


if __name__ == "__main__":
    unittest.main()
