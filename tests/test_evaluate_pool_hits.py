"""Unit tests for WIN/PLA/WQ/T3/T4 hit rules and pick ranking."""
from __future__ import annotations

import unittest

import pandas as pd

from factor_calibration import evaluate_pool_hits, ranked_picks_for_signal


class EvaluatePoolHitsTest(unittest.TestCase):
    def test_win_pla_top2(self):
        hits = evaluate_pool_hits([1, 5], [1, 5, 8, 9])
        self.assertTrue(hits["win"])
        self.assertTrue(hits["pla"])
        self.assertFalse(hits["wq"])
        self.assertFalse(hits["t3"])
        self.assertFalse(hits["t4"])

    def test_pla_only_third(self):
        hits = evaluate_pool_hits([3, 7], [3, 7, 8, 9])
        self.assertFalse(hits["win"])
        self.assertTrue(hits["pla"])
        self.assertFalse(hits["wq"])

    def test_pla_fourth_not_hit(self):
        hits = evaluate_pool_hits([4, 8], [4, 8, 1, 2])
        self.assertFalse(hits["win"])
        self.assertFalse(hits["pla"])

    def test_wq_exact_first_second(self):
        hits = evaluate_pool_hits([2, 1], [2, 1, 5, 6])
        self.assertTrue(hits["win"])
        self.assertTrue(hits["pla"])
        self.assertTrue(hits["wq"])

    def test_wq_requires_both_slots(self):
        hits = evaluate_pool_hits([1, 3], [1, 3, 2, 4])
        self.assertFalse(hits["wq"])

    def test_t3_cover_regardless_order(self):
        hits = evaluate_pool_hits([5, 6], [3, 1, 2, 9])
        self.assertFalse(hits["win"])
        self.assertTrue(hits["t3"])
        self.assertFalse(hits["t4"])

    def test_t4_cover(self):
        hits = evaluate_pool_hits([1, 2], [4, 2, 1, 3])
        self.assertTrue(hits["wq"])
        self.assertTrue(hits["t3"])
        self.assertTrue(hits["t4"])

    def test_t3_miss_if_pick_missing_place(self):
        hits = evaluate_pool_hits([1, 2], [1, 2, 5, 6])
        self.assertTrue(hits["wq"])
        self.assertFalse(hits["t3"])
        self.assertFalse(hits["t4"])


class RankedPicksForSignalTest(unittest.TestCase):
    def test_top2_and_dynamic_picks(self):
        g = pd.DataFrame(
            {
                "horse_no": [1, 2, 3, 4, 5, 6],
                "total_score": [10.0, 9.0, 8.0, 2.0, 1.0, 0.5],
                "finish_order_num": [3, 1, 2, 4, 5, 6],
            }
        )
        top2, all_picks = ranked_picks_for_signal(g, "total_score")
        self.assertEqual(list(top2["horse_no"]), [1, 2])
        self.assertGreaterEqual(len(all_picks), 2)
        self.assertEqual(int(all_picks.iloc[0]["horse_no"]), 1)
        hits = evaluate_pool_hits(
            top2["finish_order_num"].tolist(),
            all_picks["finish_order_num"].tolist(),
        )
        # top2 finishes 3 and 1 → WIN+PLA, not WQ
        self.assertTrue(hits["win"])
        self.assertTrue(hits["pla"])
        self.assertFalse(hits["wq"])

    def test_flat_scores_only_use_top2_not_whole_field(self):
        """全平分時不應把全場當 contender；WIN 只看頭兩位。"""
        g = pd.DataFrame(
            {
                "horse_no": list(range(1, 9)),
                "z_draw": [0.0] * 8,
                "finish_order_num": [8, 7, 6, 5, 4, 3, 2, 1],
            }
        )
        top2, all_picks = ranked_picks_for_signal(g, "z_draw")
        self.assertEqual(len(top2), 2)
        hits = evaluate_pool_hits(
            top2["finish_order_num"].tolist(),
            all_picks["finish_order_num"].tolist(),
        )
        # horse_no 1,2 sorted first on tie → finishes 8,7 → no WIN
        self.assertFalse(hits["win"])
        self.assertFalse(hits["pla"])


if __name__ == "__main__":
    unittest.main()
