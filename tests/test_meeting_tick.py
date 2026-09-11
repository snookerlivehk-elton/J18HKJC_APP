"""Unit tests for meeting_tick post-race planning and guards."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pandas as pd


class PlanPreRaceTest(unittest.TestCase):
    def _runner(self, **guard_kw):
        from meeting_tick import MeetingTickRunner, TickGuards

        pipe = MagicMock()
        pipe.engine = MagicMock()
        runner = MeetingTickRunner.__new__(MeetingTickRunner)
        runner.pipe = pipe
        runner.guards = TickGuards(**guard_kw)
        runner._factors_ran = False
        runner.get_tick_state = MagicMock(
            return_value={
                "fail_count": 0,
                "last_attempt_at": None,
                "last_ok_at": None,
                "last_status": None,
                "last_detail": None,
            }
        )
        runner.record_tick_attempt = MagicMock()
        return runner

    def test_plans_full_chain_when_empty(self):
        runner = self._runner()
        readiness = {
            "RACECARD": {"status": "pending"},
            "SPEEDGUIDE": {"status": "pending"},
            "FORMGUIDE": {"status": "pending"},
            "FACTORS": {"status": "pending"},
            "FORM_AI": {"status": "pending"},
            "SNAPSHOT": {"status": "pending"},
        }
        stages = pd.DataFrame(
            [
                {"stage": s, "status": "pending", "manual_override": 0}
                for s in (
                    "RACECARD",
                    "SPEEDGUIDE",
                    "FORMGUIDE",
                    "FACTORS",
                    "FORM_AI",
                    "SNAPSHOT",
                )
            ]
        )
        plan = runner.plan_pre_race_meeting(
            "2026-09-13", "ST", readiness=readiness, stages_df=stages
        )
        self.assertTrue(plan.sync_racecard)
        self.assertTrue(plan.pull_speedguide)
        self.assertTrue(plan.pull_formguide)
        self.assertTrue(plan.run_factors)
        # Form AI 可樂觀排入（本輪會拉上游），但 deferred；snapshot 仍閘住
        self.assertTrue(plan.start_form_ai)
        self.assertTrue(
            any("FORM_AI deferred_until_execute" in s for s in plan.skip_reasons)
        )
        self.assertFalse(plan.snapshot)  # 閘門未齊
        self.assertTrue(any("gates" in s for s in plan.skip_reasons))

    def test_form_ai_blocked_when_speedguide_not_pullable(self):
        """SG 未 ok 且本輪不拉（例如 cooldown）→ 不准開 Form AI。"""
        runner = self._runner()
        readiness = {
            "RACECARD": {"status": "ok"},
            "SPEEDGUIDE": {"status": "waiting"},
            "FORMGUIDE": {"status": "ok"},
            "FACTORS": {"status": "ok"},
            "FORM_AI": {"status": "pending"},
            "SNAPSHOT": {"status": "pending"},
        }
        stages = pd.DataFrame(
            [{"stage": s, "status": "pending", "manual_override": 0} for s in ("FORM_AI",)]
        )
        # 模擬 SPEEDGUIDE 仍在 cooldown → 不排 pull
        runner.get_tick_state = MagicMock(
            side_effect=lambda d, c, stage: {
                "fail_count": 0,
                "last_attempt_at": "2099-01-01T00:00:00+00:00",
                "last_ok_at": None,
                "last_status": "waiting",
                "last_detail": None,
            }
            if stage == "SPEEDGUIDE"
            else {
                "fail_count": 0,
                "last_attempt_at": None,
                "last_ok_at": None,
                "last_status": None,
                "last_detail": None,
            }
        )
        plan = runner.plan_pre_race_meeting(
            "2026-09-13", "ST", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.pull_speedguide)
        self.assertFalse(plan.start_form_ai)
        self.assertTrue(any("FORM_AI wait: SPEEDGUIDE" in s for s in plan.skip_reasons))

    def test_form_ai_starts_when_upstream_ok(self):
        runner = self._runner()
        readiness = {
            "RACECARD": {"status": "ok"},
            "SPEEDGUIDE": {"status": "ok"},
            "FORMGUIDE": {"status": "ok"},
            "FACTORS": {"status": "ok"},
            "FORM_AI": {"status": "pending"},
            "SNAPSHOT": {"status": "pending"},
        }
        stages = pd.DataFrame(
            [
                {
                    "stage": s,
                    "status": "ok" if s != "FORM_AI" else "pending",
                    "manual_override": 0,
                }
                for s in (
                    "RACECARD",
                    "SPEEDGUIDE",
                    "FORMGUIDE",
                    "FACTORS",
                    "FORM_AI",
                    "SNAPSHOT",
                )
            ]
        )
        plan = runner.plan_pre_race_meeting(
            "2026-09-13", "ST", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.pull_speedguide)
        self.assertTrue(plan.start_form_ai)
        self.assertFalse(
            any("FORM_AI deferred_until_execute" in s for s in plan.skip_reasons)
        )
        self.assertFalse(plan.snapshot)  # FORM_AI 未 ok

    def test_execute_skips_form_ai_when_sg_still_missing(self):
        from meeting_tick import PreRaceActionPlan, MeetingTickRunner, TickGuards, STATUS_WAITING

        pipe = MagicMock()
        pipe.refresh_readiness.return_value = {
            "RACECARD": {"status": "ok"},
            "SPEEDGUIDE": {"status": "waiting"},
            "FORMGUIDE": {"status": "ok"},
            "FACTORS": {"status": "ok"},
            "FORM_AI": {"status": "pending"},
            "SNAPSHOT": {"status": "pending"},
        }
        pipe.get_stages.return_value = pd.DataFrame()
        runner = MeetingTickRunner.__new__(MeetingTickRunner)
        runner.pipe = pipe
        runner.guards = TickGuards()
        runner._factors_ran = False
        runner.record_tick_attempt = MagicMock()
        plan = PreRaceActionPlan(
            racing_date="2026-09-13",
            course="ST",
            start_form_ai=True,
            readiness={
                "RACECARD": {"status": "ok"},
                "SPEEDGUIDE": {"status": "pending"},
                "FORMGUIDE": {"status": "ok"},
                "FACTORS": {"status": "ok"},
            },
        )
        out = runner.execute_pre_race_meeting(plan, dry_run=False)
        pipe.run_action.assert_not_called()
        skipped = [a for a in out["actions"] if a.get("action") == "start_form_ai_background"]
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0].get("skipped"))
        self.assertIn("SPEEDGUIDE", skipped[0].get("reason") or "")
        runner.record_tick_attempt.assert_any_call(
            "2026-09-13",
            "ST",
            "FORM_AI",
            ok=True,
            status=STATUS_WAITING,
            detail="wait gates SPEEDGUIDE",
        )

    def test_snapshot_when_gates_ok(self):
        runner = self._runner()
        readiness = {
            "RACECARD": {"status": "ok"},
            "SPEEDGUIDE": {"status": "ok"},
            "FORMGUIDE": {"status": "ok"},
            "FACTORS": {"status": "ok"},
            "FORM_AI": {"status": "ok"},
            "SNAPSHOT": {"status": "pending"},
        }
        stages = pd.DataFrame(
            [
                {"stage": s, "status": "ok" if s != "SNAPSHOT" else "pending", "manual_override": 0}
                for s in (
                    "RACECARD",
                    "SPEEDGUIDE",
                    "FORMGUIDE",
                    "FACTORS",
                    "FORM_AI",
                    "SNAPSHOT",
                )
            ]
        )
        plan = runner.plan_pre_race_meeting(
            "2026-09-13", "ST", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.sync_racecard)
        self.assertFalse(plan.pull_speedguide)
        self.assertTrue(plan.snapshot)
        self.assertTrue(plan.social_copy)

    def test_factors_wait_without_racecard(self):
        runner = self._runner()
        readiness = {
            "RACECARD": {"status": "pending"},
            "SPEEDGUIDE": {"status": "pending"},
            "FORMGUIDE": {"status": "pending"},
            "FACTORS": {"status": "pending"},
            "FORM_AI": {"status": "pending"},
            "SNAPSHOT": {"status": "pending"},
        }
        # 排位人工略過 → 下游全部停
        stages = pd.DataFrame(
            [
                {
                    "stage": "RACECARD",
                    "status": "skipped_manual",
                    "manual_override": 1,
                },
            ]
        )
        plan = runner.plan_pre_race_meeting(
            "2026-09-13", "ST", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.sync_racecard)
        self.assertFalse(plan.run_factors)
        self.assertFalse(plan.start_form_ai)
        self.assertTrue(any("FACTORS wait: RACECARD" in s for s in plan.skip_reasons))
        self.assertTrue(any("FORM_AI wait: RACECARD" in s for s in plan.skip_reasons))

    def test_social_copy_waits_without_snapshot(self):
        runner = self._runner()
        readiness = {
            "RACECARD": {"status": "ok"},
            "SPEEDGUIDE": {"status": "pending"},
            "FORMGUIDE": {"status": "pending"},
            "FACTORS": {"status": "ok"},
            "FORM_AI": {"status": "pending"},
            "SNAPSHOT": {"status": "pending"},
        }
        stages = pd.DataFrame(
            [{"stage": s, "status": "pending", "manual_override": 0} for s in ("SNAPSHOT",)]
        )
        plan = runner.plan_pre_race_meeting(
            "2026-09-13", "ST", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.social_copy)
        self.assertTrue(any("SOCIAL_COPY wait" in s for s in plan.skip_reasons))

    def test_manual_skip_blocks_racecard(self):
        runner = self._runner()
        readiness = {
            "RACECARD": {"status": "pending"},
            "SPEEDGUIDE": {"status": "pending"},
            "FORMGUIDE": {"status": "pending"},
            "FACTORS": {"status": "ok"},
            "FORM_AI": {"status": "pending"},
            "SNAPSHOT": {"status": "pending"},
        }
        stages = pd.DataFrame(
            [
                {
                    "stage": "RACECARD",
                    "status": "skipped_manual",
                    "manual_override": 1,
                },
            ]
        )
        plan = runner.plan_pre_race_meeting(
            "2026-09-13", "ST", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.sync_racecard)
        self.assertFalse(plan.pull_speedguide)
        self.assertTrue(any("RACECARD manual" in s for s in plan.skip_reasons))

    def test_dry_run_pre_race_execute(self):
        from meeting_tick import PreRaceActionPlan, MeetingTickRunner, TickGuards

        pipe = MagicMock()
        runner = MeetingTickRunner.__new__(MeetingTickRunner)
        runner.pipe = pipe
        runner.guards = TickGuards()
        runner._factors_ran = False
        runner.record_tick_attempt = MagicMock()
        plan = PreRaceActionPlan(
            racing_date="2026-09-13",
            course="ST",
            sync_racecard=True,
            pull_speedguide=True,
            pull_formguide=True,
            run_factors=True,
            start_form_ai=True,
            snapshot=False,
            social_copy=True,
        )
        out = runner.execute_pre_race_meeting(plan, dry_run=True)
        pipe.run_action.assert_not_called()
        self.assertEqual(len(out["actions"]), 6)
        self.assertTrue(all(a.get("dry_run") for a in out["actions"]))
        self.assertTrue(any(a.get("action") == "social_copy" for a in out["actions"]))


class PlanPostRaceTest(unittest.TestCase):
    def _runner(self, **guard_kw):
        from meeting_tick import MeetingTickRunner, TickGuards

        pipe = MagicMock()
        pipe.engine = MagicMock()
        runner = MeetingTickRunner.__new__(MeetingTickRunner)
        runner.pipe = pipe
        runner.guards = TickGuards(**guard_kw)
        runner.get_tick_state = MagicMock(
            return_value={
                "fail_count": 0,
                "last_attempt_at": None,
                "last_ok_at": None,
                "last_status": None,
                "last_detail": None,
            }
        )
        runner.record_tick_attempt = MagicMock()
        return runner

    def test_plans_sync_and_settle_when_pending(self):
        runner = self._runner()
        readiness = {
            "RESULTS": {"status": "waiting", "detail": "no results"},
            "SETTLED": {"status": "pending", "detail": ""},
            "SNAPSHOT": {"status": "ok", "detail": "batch"},
        }
        stages = pd.DataFrame(
            [
                {"stage": "RESULTS", "status": "waiting", "manual_override": 0},
                {"stage": "SETTLED", "status": "pending", "manual_override": 0},
                {"stage": "SNAPSHOT", "status": "ok", "manual_override": 0},
            ]
        )
        plan = runner.plan_post_race_meeting(
            "2026-09-09", "HV", readiness=readiness, stages_df=stages
        )
        self.assertTrue(plan.sync_results)
        self.assertTrue(plan.sync_text_reports)
        self.assertTrue(plan.settle)

    def test_skips_when_already_settled(self):
        runner = self._runner()
        readiness = {
            "RESULTS": {"status": "ok", "detail": ""},
            "SETTLED": {"status": "ok", "detail": "done"},
            "SNAPSHOT": {"status": "ok", "detail": ""},
        }
        stages = pd.DataFrame(
            [
                {"stage": "RESULTS", "status": "ok", "manual_override": 0},
                {"stage": "SETTLED", "status": "ok", "manual_override": 0},
            ]
        )
        plan = runner.plan_post_race_meeting(
            "2026-09-09", "ST", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.sync_results)
        self.assertFalse(plan.settle)
        # 賽後評述仍可週期補拉（RESULTS 已 ok）
        self.assertTrue(plan.sync_text_reports)
        # 已結算 → 可跑宣傳評估／賽後文案
        self.assertTrue(plan.promo_hits)
        self.assertTrue(plan.post_race_copy)

    def test_manual_skip_blocks_actions(self):
        runner = self._runner()
        readiness = {
            "RESULTS": {"status": "waiting", "detail": ""},
            "SETTLED": {"status": "pending", "detail": ""},
            "SNAPSHOT": {"status": "ok", "detail": ""},
        }
        stages = pd.DataFrame(
            [
                {
                    "stage": "RESULTS",
                    "status": "skipped_manual",
                    "manual_override": 1,
                },
                {
                    "stage": "SETTLED",
                    "status": "skipped_manual",
                    "manual_override": 1,
                },
            ]
        )
        plan = runner.plan_post_race_meeting(
            "2026-09-09", "HV", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.sync_results)
        self.assertFalse(plan.settle)
        self.assertTrue(any("manual" in s for s in plan.skip_reasons))

    def test_settle_waits_without_snapshot(self):
        runner = self._runner()
        readiness = {
            "RESULTS": {"status": "ok", "detail": ""},
            "SETTLED": {"status": "pending", "detail": ""},
            "SNAPSHOT": {"status": "pending", "detail": ""},
        }
        stages = pd.DataFrame(
            [
                {"stage": "RESULTS", "status": "ok", "manual_override": 0},
                {"stage": "SETTLED", "status": "pending", "manual_override": 0},
                {"stage": "SNAPSHOT", "status": "pending", "manual_override": 0},
            ]
        )
        plan = runner.plan_post_race_meeting(
            "2026-09-09", "HV", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.sync_results)
        self.assertFalse(plan.settle)
        self.assertTrue(any("SNAPSHOT" in s for s in plan.skip_reasons))
        self.assertTrue(plan.sync_text_reports)

    def test_cooldown_blocks_retry(self):
        runner = self._runner(cooldown_waiting_sec=1800)
        runner.get_tick_state = MagicMock(
            return_value={
                "fail_count": 0,
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
                "last_ok_at": None,
                "last_status": "waiting",
                "last_detail": "",
            }
        )
        readiness = {
            "RESULTS": {"status": "waiting", "detail": ""},
            "SETTLED": {"status": "pending", "detail": ""},
            "SNAPSHOT": {"status": "ok", "detail": ""},
        }
        stages = pd.DataFrame(
            [
                {"stage": "RESULTS", "status": "waiting", "manual_override": 0},
                {"stage": "SETTLED", "status": "pending", "manual_override": 0},
            ]
        )
        plan = runner.plan_post_race_meeting(
            "2026-09-09", "HV", readiness=readiness, stages_df=stages
        )
        self.assertFalse(plan.sync_results)
        self.assertTrue(any("cooldown" in s for s in plan.skip_reasons))

    def test_force_bypasses_cooldown(self):
        runner = self._runner(force=True, cooldown_waiting_sec=1800)
        runner.get_tick_state = MagicMock(
            return_value={
                "fail_count": 9,
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
                "last_ok_at": None,
                "last_status": "failed",
                "last_detail": "",
            }
        )
        readiness = {
            "RESULTS": {"status": "failed", "detail": ""},
            "SETTLED": {"status": "pending", "detail": ""},
            "SNAPSHOT": {"status": "ok", "detail": ""},
        }
        stages = pd.DataFrame(
            [
                {"stage": "RESULTS", "status": "failed", "manual_override": 0},
                {"stage": "SETTLED", "status": "pending", "manual_override": 0},
            ]
        )
        plan = runner.plan_post_race_meeting(
            "2026-09-09", "HV", readiness=readiness, stages_df=stages
        )
        self.assertTrue(plan.sync_results)
        self.assertTrue(plan.sync_text_reports)
        self.assertTrue(plan.settle)


class TickStateTableTest(unittest.TestCase):
    def test_record_and_read_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "tick.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import meeting_pipeline as mp
            import meeting_tick as mt

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            mp.USE_SQLITE = True
            mp.SQLITE_DB_PATH = db_path
            mp.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
            mt.USE_SQLITE = True

            pipe = mp.MeetingPipeline()
            runner = mt.MeetingTickRunner(pipe)
            runner.record_tick_attempt(
                "2026-09-09",
                "HV",
                "RESULTS",
                ok=False,
                status="failed",
                detail="boom",
            )
            st = runner.get_tick_state("2026-09-09", "HV", "RESULTS")
            self.assertEqual(int(st["fail_count"]), 1)
            runner.record_tick_attempt(
                "2026-09-09",
                "HV",
                "RESULTS",
                ok=True,
                status="ok",
                detail="done",
            )
            st2 = runner.get_tick_state("2026-09-09", "HV", "RESULTS")
            self.assertEqual(int(st2["fail_count"]), 0)


class DryRunCliTest(unittest.TestCase):
    def test_dry_run_execute_does_not_call_actions(self):
        from meeting_tick import MeetingActionPlan, MeetingTickRunner, TickGuards

        pipe = MagicMock()
        runner = MeetingTickRunner.__new__(MeetingTickRunner)
        runner.pipe = pipe
        runner.guards = TickGuards()
        runner.record_tick_attempt = MagicMock()
        plan = MeetingActionPlan(
            racing_date="2026-09-09",
            course="HV",
            sync_results=True,
            settle=True,
        )
        out = runner.execute_post_race_meeting(plan, dry_run=True)
        pipe.run_action.assert_not_called()
        self.assertEqual(len(out["actions"]), 2)
        self.assertTrue(all(a.get("dry_run") for a in out["actions"]))


class HelpersTest(unittest.TestCase):
    def test_is_manual_blocked(self):
        from meeting_tick import is_manual_blocked

        self.assertTrue(
            is_manual_blocked(
                {"manual_override": 1, "status": "skipped_manual"}
            )
        )
        self.assertFalse(
            is_manual_blocked({"manual_override": 0, "status": "waiting"})
        )


if __name__ == "__main__":
    unittest.main()
