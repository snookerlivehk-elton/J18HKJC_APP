"""Tests for ad promo hit rules and odds parsing."""
from __future__ import annotations

import json
import unittest

from ad_promo_hits import (
    attach_ad_pick_ranks_to_snapshot_rows,
    evaluate_ad_race_hits,
    parse_runner_win_odds,
)


class ParseOddsTest(unittest.TestCase):
    def test_jjjc_win_odds_in_raw(self):
        raw = json.dumps({"win_odds": 8.5, "synced_via": "jjjc_results_sync"})
        self.assertEqual(parse_runner_win_odds("8.5", raw), 8.5)

    def test_legacy_probability_percent(self):
        # 20% → odds 5.0
        self.assertAlmostEqual(parse_runner_win_odds("20", None), 5.0)


class AdRaceHitsTest(unittest.TestCase):
    def test_win_odds7(self):
        hits = evaluate_ad_race_hits(
            pick_finishes=[1, 5, 3, 8],
            pick_odds=[9.0, 4.0, 12.0, 20.0],
            top2_mask=[True, True, False, False],
        )
        self.assertTrue(hits["win_odds7"])
        self.assertFalse(hits["qin_odds10"])  # no cover of 1+2
        self.assertFalse(hits["t3_cover"])
        self.assertTrue(hits["any_promo"])

    def test_win_odds7_requires_top2_and_threshold(self):
        # winner is pick #3 (not top2)
        hits = evaluate_ad_race_hits(
            pick_finishes=[4, 5, 1],
            pick_odds=[3.0, 4.0, 15.0],
            top2_mask=[True, True, False],
        )
        self.assertFalse(hits["win_odds7"])

        # top2 wins but odds too low
        hits2 = evaluate_ad_race_hits(
            pick_finishes=[1, 3],
            pick_odds=[5.5, 8.0],
            top2_mask=[True, True],
        )
        self.assertFalse(hits2["win_odds7"])

    def test_qin_odds10(self):
        hits = evaluate_ad_race_hits(
            pick_finishes=[2, 1, 6, 7],
            pick_odds=[12.0, 3.5, 8.0, 9.0],
            top2_mask=[True, True, False, False],
        )
        self.assertTrue(hits["qin_odds10"])
        # 冠軍在推介頭兩位，但賠率 3.5 < 7
        self.assertFalse(hits["win_odds7"])
        self.assertTrue(hits["any_promo"])

    def test_t3_t4_no_odds(self):
        hits = evaluate_ad_race_hits(
            pick_finishes=[3, 1, 2, 4],
            pick_odds=[None, None, None, None],
            top2_mask=[True, True, False, False],
        )
        self.assertTrue(hits["t3_cover"])
        self.assertTrue(hits["t4_cover"])
        self.assertFalse(hits["win_odds7"])
        self.assertFalse(hits["qin_odds10"])


class AttachAdPickRankTest(unittest.TestCase):
    def test_assigns_up_to_four(self):
        rows = [
            {
                "race_id": "R1",
                "horse_no": i,
                "horse_name": f"H{i}",
                "model_win_prob": 0.35 - i * 0.04,
                "ai_score": 2.0 - i * 0.1,
                "confidence": 0.8,
            }
            for i in range(1, 7)
        ]
        attach_ad_pick_ranks_to_snapshot_rows(rows)
        ranked = [r for r in rows if r.get("ad_pick_rank") is not None]
        self.assertGreaterEqual(len(ranked), 2)
        self.assertLessEqual(len(ranked), 4)
        ranks = sorted(int(r["ad_pick_rank"]) for r in ranked)
        self.assertEqual(ranks, list(range(1, len(ranked) + 1)))


if __name__ == "__main__":
    unittest.main()
