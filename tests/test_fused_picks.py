"""Tests for model×AI fused picks (third track)."""
from __future__ import annotations

import unittest

from form_ai_picks import attach_fused_shares_to_snapshot_rows, build_fused_picks
from factor_calibration import evaluate_pool_hits, ranked_picks_for_signal
import pandas as pd


class BuildFusedPicksTest(unittest.TestCase):
    def test_blend_prefers_consensus(self):
        rows = [
            {"horse_no": 1, "horse_name": "A", "model_win_prob": 0.40, "ai_score": 2.0, "confidence": 0.9},
            {"horse_no": 2, "horse_name": "B", "model_win_prob": 0.30, "ai_score": 1.8, "confidence": 0.85},
            {"horse_no": 3, "horse_name": "C", "model_win_prob": 0.20, "ai_score": 0.5, "confidence": 0.5},
            {"horse_no": 4, "horse_name": "D", "model_win_prob": 0.10, "ai_score": 0.2, "confidence": 0.4},
        ]
        pack = build_fused_picks(rows, alpha=0.6)
        self.assertTrue(pack["available"])
        self.assertFalse(pack["fallback_model_only"])
        self.assertGreaterEqual(pack["pick_n"], 2)
        place_nos = [int(x["horse_no"]) for x in pack["place"]]
        self.assertIn(1, place_nos)
        # shares sum ~ 1
        s = sum(float(x["fused_share"]) for x in pack["ranked"])
        self.assertAlmostEqual(s, 1.0, places=5)

    def test_fallback_when_ai_low_confidence(self):
        rows = [
            {"horse_no": 1, "horse_name": "A", "model_win_prob": 0.5, "ai_score": 1.0, "confidence": 0.1},
            {"horse_no": 2, "horse_name": "B", "model_win_prob": 0.3, "ai_score": 0.8, "confidence": 0.1},
            {"horse_no": 3, "horse_name": "C", "model_win_prob": 0.2, "ai_score": 0.5, "confidence": 0.05},
        ]
        pack = build_fused_picks(rows, alpha=0.6)
        self.assertTrue(pack["available"])
        self.assertTrue(pack["fallback_model_only"])
        self.assertEqual(pack["alpha"], 1.0)
        # fused ≈ model order
        self.assertEqual(int(pack["place"][0]["horse_no"]), 1)

    def test_attach_fused_share_and_hit_signal(self):
        rows = [
            {
                "race_id": "R1",
                "horse_no": 1,
                "horse_name": "A",
                "model_win_prob": 0.45,
                "ai_combo": 1.5,
                "finish_order_num": 1,
            },
            {
                "race_id": "R1",
                "horse_no": 2,
                "horse_name": "B",
                "model_win_prob": 0.35,
                "ai_combo": 1.2,
                "finish_order_num": 2,
            },
            {
                "race_id": "R1",
                "horse_no": 3,
                "horse_name": "C",
                "model_win_prob": 0.20,
                "ai_combo": 0.4,
                "finish_order_num": 3,
            },
        ]
        # add confidence so AI available
        for r in rows:
            r["ai_score"] = float(r["ai_combo"]) / 0.8
            r["confidence"] = 0.8
        attach_fused_shares_to_snapshot_rows(rows)
        self.assertTrue(all(r.get("fused_share") is not None for r in rows))
        g = pd.DataFrame(rows)
        top2, all_picks, top3 = ranked_picks_for_signal(g, "fused_share")
        hits = evaluate_pool_hits(
            top2["finish_order_num"].tolist(),
            all_picks["finish_order_num"].tolist(),
            top3["finish_order_num"].tolist(),
        )
        self.assertTrue(hits["win"])
        self.assertTrue(hits["pla"])


if __name__ == "__main__":
    unittest.main()
