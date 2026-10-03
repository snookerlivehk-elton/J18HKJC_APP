"""Tests for Form AI self-heal (auto-restart + shorter stale)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


class FormAISelfHealTest(unittest.TestCase):
    def test_running_stale_default_is_15min(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            os.environ["USE_SQLITE"] = "true"
            os.environ.pop("FORM_AI_RUNNING_STALE_SEC", None)

            import etl_pipeline
            import form_ai_batch_job as faj

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            faj.USE_SQLITE = True
            faj.SQLITE_DB_PATH = db_path
            faj.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            job_id = faj.create_job(
                eng, job_type="form_ai", racing_date="2026-10-03", course="ST"
            )
            faj.update_job(
                eng,
                job_id,
                status="running",
                detail="running",
                progress={"phase": "running", "pid": 1},
            )
            # 20 minutes without heartbeat → failed under new 15min default
            old = (datetime.now(timezone.utc) - timedelta(seconds=20 * 60)).isoformat()
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE background_jobs SET updated_at=:u, created_at=:u WHERE job_id=:id"
                    ),
                    {"u": old, "id": job_id},
                )
            out = faj.reconcile_running_job(eng, faj.get_job(eng, job_id))
            self.assertEqual(out["status"], "failed")
            prog = out.get("progress_json") or {}
            if isinstance(prog, str):
                prog = json.loads(prog)
            self.assertEqual(prog.get("phase"), "dead")

    def test_count_auto_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import form_ai_batch_job as faj

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            faj.USE_SQLITE = True
            faj.SQLITE_DB_PATH = db_path
            faj.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            from sqlalchemy import create_engine

            eng = create_engine(f"sqlite:///{db_path}")
            j1 = faj.create_job(
                eng, job_type="form_ai", racing_date="2026-10-03", course="HV"
            )
            faj.update_job(
                eng,
                j1,
                status="failed",
                detail="auto_restart #1",
                progress={"auto_restart": True, "phase": "dead"},
                finished=True,
            )
            j2 = faj.create_job(
                eng, job_type="form_ai", racing_date="2026-10-03", course="HV"
            )
            faj.update_job(
                eng,
                j2,
                status="failed",
                detail="manual",
                progress={"phase": "dead"},
                finished=True,
            )
            n = faj.count_auto_restarts(
                eng, racing_date="2026-10-03", course="HV", within_hours=24
            )
            self.assertEqual(n, 1)

    def test_ensure_self_heal_skips_when_ok(self):
        from meeting_pipeline import MeetingPipeline, STATUS_OK

        pipe = MeetingPipeline.__new__(MeetingPipeline)
        pipe.check_form_ai = MagicMock(return_value=(STATUS_OK, "90/100"))
        out = MeetingPipeline.ensure_form_ai_self_heal(pipe, "2026-10-03", "ST")
        self.assertTrue(out.get("skipped"))
        self.assertTrue(out.get("ok"))

    def test_ensure_self_heal_restarts_after_failed(self):
        from meeting_pipeline import MeetingPipeline, STATUS_FAILED

        pipe = MeetingPipeline.__new__(MeetingPipeline)
        pipe.engine = MagicMock()
        pipe.check_form_ai = MagicMock(
            return_value=(STATUS_FAILED, "Form AI 覆蓋不足 4/142")
        )
        pipe.start_form_ai_background = MagicMock(
            return_value={
                "ok": True,
                "job_id": "abc",
                "auto_restart": True,
                "auto_restart_n": 1,
            }
        )
        with patch("form_ai_batch_job.ensure_jobs_table"), patch(
            "form_ai_batch_job.latest_job",
            return_value={
                "job_id": "old",
                "status": "failed",
                "detail": "無進度心跳",
            },
        ), patch("form_ai_batch_job.reconcile_running_job") as recon:
            out = MeetingPipeline.ensure_form_ai_self_heal(pipe, "2026-10-03", "ST")
        recon.assert_not_called()  # not running → no reconcile needed
        pipe.start_form_ai_background.assert_called_once()
        kwargs = pipe.start_form_ai_background.call_args.kwargs
        self.assertTrue(kwargs.get("auto_restart"))
        self.assertTrue(kwargs.get("only_missing"))
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("self_heal"))

    def test_form_ai_attempt_uses_short_cooldown(self):
        from meeting_tick import MeetingTickRunner, TickGuards

        svc = MeetingTickRunner.__new__(MeetingTickRunner)
        svc.guards = TickGuards(
            cooldown_waiting_sec=1800,
            cooldown_failed_sec=3600,
            max_fails=5,
            force=False,
        )
        svc.pipe = MagicMock()
        svc.pipe.engine = MagicMock()
        svc.get_tick_state = MagicMock(
            return_value={
                "last_attempt_at": (
                    datetime.now(timezone.utc) - timedelta(seconds=400)
                ).isoformat(),
                "fail_count": 9,
            }
        )
        with patch(
            "form_ai_batch_job.count_auto_restarts", return_value=1
        ):
            ok, why = MeetingTickRunner._attempt_allowed_form_ai(
                svc, "2026-10-03", "ST", "failed"
            )
        self.assertTrue(ok)
        self.assertEqual(why, "form_ai_retry_ok")


if __name__ == "__main__":
    unittest.main()
