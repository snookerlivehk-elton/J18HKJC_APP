"""Reject blank / incomplete factor entity names."""
from __future__ import annotations

import unittest

import pandas as pd


class ValidFactorEntityTest(unittest.TestCase):
    def test_valid_factor_entity_helpers(self):
        from bucket_utils import (
            horse_jockey_name,
            synergy_name,
            valid_factor_entity,
        )

        self.assertFalse(valid_factor_entity(""))
        self.assertFalse(valid_factor_entity(None))
        self.assertFalse(valid_factor_entity("   "))
        self.assertTrue(valid_factor_entity("艾道拿"))
        self.assertFalse(valid_factor_entity(synergy_name("", "巫偉傑")))
        self.assertTrue(synergy_name("", "巫偉傑").lstrip().startswith("&"))
        self.assertFalse(valid_factor_entity(" & 巫偉傑"))
        self.assertFalse(valid_factor_entity(horse_jockey_name("K478", "")))
        self.assertTrue(horse_jockey_name("K478", "").startswith("K478"))
        self.assertFalse(valid_factor_entity("K478 & "))
        self.assertTrue(valid_factor_entity(synergy_name("布文", "巫偉傑")))
        self.assertTrue(valid_factor_entity(horse_jockey_name("K478", "潘頓")))

    def test_calculate_entity_factor_drops_blank_jockey(self):
        from datetime import datetime

        from factor_calculator import FactorCalculator

        calc = FactorCalculator.__new__(FactorCalculator)
        object.__setattr__(calc, "target_date", pd.Timestamp(datetime(2026, 9, 20)))
        # minimal frame: two rows same bucket, one blank jockey
        df = pd.DataFrame(
            {
                "bucket_id": ["HV_MILE", "HV_MILE", "HV_MILE"],
                "band_bucket_id": ["HV_MILE", "HV_MILE", "HV_MILE"],
                "jockey_name": ["艾道拿", "", "潘頓"],
                "trainer_name": ["蔡約翰", "巫偉傑", "呂健威"],
                "raw_score": [1.0, 1.0, 0.5],
                "weighted_score": [1.0, 1.0, 0.5],
                "weighted_runs": [1.0, 1.0, 1.0],
                "finish_order_num": [1, 2, 3],
                "racing_date": pd.to_datetime(
                    ["2026-09-01", "2026-09-02", "2026-09-03"]
                ),
            }
        )
        out = calc.calculate_entity_factor(
            df, "jockey_name", [1.0], 5.0, use_distance_band=True
        )
        self.assertFalse(out.empty)
        names = set(out["jockey_name"].astype(str).tolist())
        self.assertNotIn("", names)
        self.assertIn("艾道拿", names)
        self.assertIn("潘頓", names)

        df["synergy_name"] = df.apply(
            lambda r: f"{r['jockey_name']} & {r['trainer_name']}".strip()
            if r["jockey_name"]
            else f"& {r['trainer_name']}",
            axis=1,
        )
        # fix: use real synergy_name
        from bucket_utils import synergy_name

        df["synergy_name"] = [
            synergy_name(j, t) for j, t in zip(df["jockey_name"], df["trainer_name"])
        ]
        syn = calc.calculate_entity_factor(
            df, "synergy_name", [1.0], 5.0, use_distance_band=True
        )
        syn_names = set(syn["synergy_name"].astype(str).tolist())
        self.assertNotIn("& 巫偉傑", syn_names)
        self.assertTrue(all("&" in n and not n.startswith("&") for n in syn_names))


if __name__ == "__main__":
    unittest.main()
