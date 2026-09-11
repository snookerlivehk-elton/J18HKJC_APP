"""Tests for ops_incidents + MeetingPipeline stage helpers."""
from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text


class OpsIncidentsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = create_engine(f"sqlite:///{self._tmp.name}")
        # Force SQLite path for OpsIncidentService DDL
        self._use_sqlite = patch("ops_incidents.USE_SQLITE", True)
        self._use_sqlite.start()
        self.addCleanup(self._use_sqlite.stop)

        from ops_incidents import OpsIncidentService

        self.svc = OpsIncidentService(engine=self.engine)

    def test_create_and_dedupe(self):
        a = self.svc.create_incident(
            reason_code="stage_failed",
            detail="SG failed",
            racing_date="2026-09-13",
            course="ST",
            stage="SPEEDGUIDE",
            notify=False,
        )
        self.assertTrue(a["created"])
        b = self.svc.create_incident(
            reason_code="stage_failed",
            detail="SG failed again",
            racing_date="2026-09-13",
            course="ST",
            stage="SPEEDGUIDE",
            notify=False,
        )
        self.assertFalse(b["created"])
        self.assertTrue(b["deduped"])
        self.assertEqual(a["report_id"], b["report_id"])

    def test_evaluate_meeting_needs_human(self):
        ready = {
            "RACECARD": {
                "status": "failed",
                "detail": "排位疑似錯位（檔位 0）",
            },
            "SPEEDGUIDE": {"status": "waiting", "detail": "尚未上架"},
            "FORM_AI": {"status": "pending", "detail": "尚未跑"},
        }
        outs = self.svc.evaluate_meeting_needs_human(
            "2026-09-13",
            "ST",
            ready,
            tick_fail_count=5,
            max_fails=5,
            backlog_expiring=True,
            notify=False,
        )
        codes = {o.get("report_id") and self.svc.get_report(o["report_id"]).get("reason_code") for o in outs if o.get("report_id")}
        # re-fetch via list
        df = self.svc.list_reports(statuses=["open"], racing_date="2026-09-13")
        reason_codes = set(df["reason_code"].tolist())
        self.assertIn("racecard_corrupt", reason_codes)
        self.assertIn("tick_max_fails", reason_codes)
        self.assertIn("backlog_expiring", reason_codes)
        # waiting should NOT create incident
        self.assertNotIn("stage_failed", reason_codes - {"racecard_corrupt"})

    def test_record_manual_action_no_dedupe(self):
        a = self.svc.record_manual_action(
            racing_date="2026-09-13",
            course="HV",
            stage="SNAPSHOT",
            action="manual_ok",
            detail="人工放行",
        )
        b = self.svc.record_manual_action(
            racing_date="2026-09-13",
            course="HV",
            stage="SNAPSHOT",
            action="manual_ok",
            detail="人工放行 again",
        )
        self.assertTrue(a["created"])
        self.assertTrue(b["created"])
        self.assertNotEqual(a["report_id"], b["report_id"])

    def test_resolve(self):
        out = self.svc.create_incident(
            reason_code="notify_test",
            detail="x",
            racing_date="2026-09-10",
            course="ST",
            notify=False,
            dedupe=False,
        )
        rid = out["report_id"]
        self.svc.resolve(rid, action_taken="fixed", triggered_by="admin")
        row = self.svc.get_report(rid)
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["action_taken"], "fixed")

    def test_notify_admins_stub(self):
        from ops_incidents import notify_admins

        with patch("ops_incidents.NOTIFY_ENABLED", False):
            out = notify_admins(
                {
                    "report_id": "inc_test",
                    "racing_date": "2026-09-13",
                    "course": "ST",
                    "reason_code": "stage_failed",
                    "severity": "crit",
                    "status": "open",
                    "triggered_by": "system",
                    "detail": "boom",
                }
            )
        self.assertTrue(out["skipped"])
        self.assertTrue(out["stub"])


class MeetingPipelineHelpersTest(unittest.TestCase):
    def test_stage_primary_action_map(self):
        from meeting_pipeline import STAGE_HELP, STAGE_PRIMARY_ACTION, STAGES

        for stage, _label in STAGES:
            self.assertIn(stage, STAGE_PRIMARY_ACTION)
            self.assertIn(stage, STAGE_HELP)

    def test_complete_stage_dispatches(self):
        from meeting_pipeline import MeetingPipeline

        pipe = MeetingPipeline.__new__(MeetingPipeline)
        pipe.engine = MagicMock()
        called = {}

        def fake_run(d, c, action, **kw):
            called["args"] = (d, c, action, kw)
            return {"ok": True, "action": action}

        pipe.run_action = fake_run
        pipe.run_backlog_chain = MagicMock(return_value={"ok": True, "action": "run_backlog_chain"})

        out = MeetingPipeline.complete_stage(pipe, "2026-09-13", "ST", "RACECARD")
        self.assertEqual(called["args"][2], "sync_jjjc_racecard")
        self.assertTrue(out["ok"])

        out2 = MeetingPipeline.complete_stage(pipe, "2026-09-13", "ST", "NLP")
        pipe.run_backlog_chain.assert_called_once()
        self.assertEqual(out2.get("action"), "run_backlog_chain")

    def test_auto_backlog_factors_default_true(self):
        import importlib
        import os

        os.environ.pop("MEETING_TICK_BACKLOG_AUTO_FACTORS", None)
        import data_backlog as db

        importlib.reload(db)
        self.assertTrue(db.AUTO_BACKLOG_FACTORS)


if __name__ == "__main__":
    unittest.main()
