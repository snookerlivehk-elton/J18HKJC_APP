"""horse_key merges EN/ZH careers; identity prefers brand_num."""
from __future__ import annotations

import unittest

import pandas as pd


class HorseIdentityStatsTest(unittest.TestCase):
    def test_identity_helpers(self):
        from jjjc_export_common import horse_identity_key, is_real_horse_code

        self.assertTrue(is_real_horse_code("J446"))
        self.assertTrue(is_real_horse_code("H349"))
        self.assertFalse(is_real_horse_code("H13"))  # synthetic
        self.assertEqual(
            horse_identity_key("J446", "FORTUNATE SON"),
            "J446",
        )
        self.assertEqual(
            horse_identity_key("J446", "將義"),
            "J446",
        )
        self.assertEqual(
            horse_identity_key(None, "將義"),
            "將義",
        )

    def test_horse_factor_merges_en_zh_same_brand(self):
        from factor_calculator import FactorCalculator

        calc = FactorCalculator(target_date="2026-09-20")
        rows = []
        for i, (name, fo) in enumerate(
            [("FORTUNATE SON", 3), ("將義", 1), ("FORTUNATE SON", 5)],
            start=1,
        ):
            rows.append(
                {
                    "racing_date": pd.Timestamp("2026-09-0%d" % i),
                    "race_id": f"2026090{i}HV01",
                    "course": "草地",
                    "track": "A",
                    "distance_m": 1200,
                    "ground": "好",
                    "race_class": "第四班",
                    "runner_id": f"r{i}",
                    "horse_no": 10,
                    "brand_num": "J446",
                    "horse_id": "HK_2026_J446",
                    "jockey_name": "何澤昭",
                    "trainer_name": "巫偉傑",
                    "horse_name": name,
                    "finish_order_num": fo,
                    "draw": 5,
                    "runner_rating": 50,
                    "win_probability_raw": "10",
                    "final_time": "1:10.00",
                    "raw_json": "{}",
                    "class_num": 4,
                    "win_odds": 10.0,
                    "late_pos": 3,
                    "bucket_id": "HV_A_1200",
                    "band_bucket_id": "HV_SPRINT",
                    "horse_key": "J446",
                    "raw_score": 1.0 if fo <= 4 else 0.0,
                }
            )
        df = pd.DataFrame(rows)
        out = calc.calculate_horse_factor(df, apply_nlp=False)
        self.assertFalse(out.empty)
        # 同一馬碼應合成一列，唔好拆成英文＋中文兩行
        horse_rows = out[out["entity_name"] == "J446"]
        self.assertEqual(len(horse_rows), 1, out[["entity_name", "actual_runs"]].to_dict())
        self.assertEqual(int(horse_rows.iloc[0]["actual_runs"]), 3)


if __name__ == "__main__":
    unittest.main()
