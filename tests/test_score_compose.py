"""Unit tests for coverage stakeholder compose + interference helpers."""
from __future__ import annotations

import unittest

from config import ModelConfig
from score_compose import (
    compose_total,
    coverage_from_ratio,
    hit_coverage,
    legacy_total_from_parts,
    make_stakeholder,
    miss_coverage,
    pick_score_for_ranking,
)
from factor_calculator import FactorCalculator


class TestScoreCompose(unittest.TestCase):
    def test_miss_does_not_contribute_full_weight(self):
        hit = make_stakeholder("JOCKEY", 1.0, present=True, coverage=1.0, base_weight=2.0)
        miss = make_stakeholder("HORSE", 5.0, present=False, coverage=0.0, base_weight=1.5)
        total, cov, br = compose_total([hit, miss])
        self.assertAlmostEqual(total, 2.0)
        self.assertAlmostEqual(br["HORSE"]["effective"], 0.0)
        self.assertLess(cov, 1.0)

    def test_coverage_scales_effective(self):
        s = make_stakeholder("DRAW", 2.0, present=True, coverage=0.5, base_weight=1.2)
        total, _, br = compose_total([s])
        self.assertAlmostEqual(total, 2.0 * 1.2 * 0.5)
        self.assertAlmostEqual(br["DRAW"]["effective"], 1.2)

    def test_no_renormalization(self):
        a = make_stakeholder("A", 1.0, present=True, coverage=1.0, base_weight=1.0)
        b = make_stakeholder("B", 1.0, present=False, coverage=0.0, base_weight=1.0)
        total, _, _ = compose_total([a, b])
        self.assertAlmostEqual(total, 1.0)

    def test_coverage_from_ratio(self):
        self.assertEqual(coverage_from_ratio(0.0), 0.0)
        self.assertEqual(coverage_from_ratio(1.0), 1.0)
        mid = coverage_from_ratio(0.6)
        self.assertGreaterEqual(mid, float(ModelConfig.COVERAGE_PARTIAL_FLOOR))
        self.assertAlmostEqual(mid, 0.6)

    def test_pick_score_modes(self):
        self.assertEqual(pick_score_for_ranking(legacy_score=1.0, coverage_score=9.0, mode="off"), 1.0)
        self.assertEqual(pick_score_for_ranking(legacy_score=1.0, coverage_score=9.0, mode="shadow"), 1.0)
        self.assertEqual(pick_score_for_ranking(legacy_score=1.0, coverage_score=9.0, mode="on"), 9.0)

    def test_legacy_total_matches_manual(self):
        t = legacy_total_from_parts(
            z_jockey=1.0,
            z_trainer=0.0,
            z_synergy=0.0,
            z_draw=0.0,
            z_horse=0.0,
            z_pace=0.0,
            z_speed=0.0,
            sg_form=0.0,
            sg_energy=0.0,
            sg_delta=0.0,
        )
        self.assertAlmostEqual(t, ModelConfig.WEIGHT_JOCKEY)

    def test_hit_miss_helpers(self):
        self.assertEqual(hit_coverage(), 1.0)
        self.assertEqual(miss_coverage(), float(ModelConfig.COVERAGE_MISS_DEFAULT))


class TestInterferenceHelpers(unittest.TestCase):
    def test_form_delta_positive_when_excuse(self):
        info = {"severity": 1.0, "excuse_stage": "late"}
        d = FactorCalculator.compute_interference_form_delta(0.3, info)
        self.assertGreater(d, 0.0)

    def test_form_delta_zero_without_excuse(self):
        self.assertEqual(FactorCalculator.compute_interference_form_delta(0.3, {}), 0.0)

    def test_speed_boost(self):
        info = {"severity": 1.0, "excuse_stage": "late"}
        b = FactorCalculator.compute_interference_speed_boost(info)
        self.assertAlmostEqual(b, 0.12 * 1.0 * 1.3)


if __name__ == "__main__":
    unittest.main()
