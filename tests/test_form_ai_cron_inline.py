"""Tests for Form AI Cron inline execution (C1)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class FormAICronInlineTest(unittest.TestCase):
    def test_ui_start_enqueues_without_popen(self):
        from meeting_pipeline import MeetingPipeline

        pipe = MeetingPipeline.__new__(MeetingPipeline)
        pipe.engine = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            os.environ["USE_SQLITE"] = "true"
            os.environ["FORM_AI_WEB_ENQUEUE_ONLY"] = "true"
            os.environ["FORM_AI_ALLOW_SPAWN"] = "false"

            import etl_pipeline
            import form_ai_batch_job as faj

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            faj.USE_SQLITE = True
            faj.SQLITE_DB_PATH = db_path
            faj.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            from sqlalchemy import create_engine

            eng = create_engine(f"sqlite:///{db_path}")
            pipe.engine = eng

            with patch("subprocess.Popen") as popen:
                out = MeetingPipeline.start_form_ai_background(
                    pipe,
                    "2026-10-03",
                    "ST",
                    only_missing=True,
                    enqueue_only=True,
                    run_inline=False,
                )
            popen.assert_not_called()
            self.assertTrue(out.get("ok"))
            self.assertTrue(out.get("queued"))
            self.assertTrue(out.get("job_id"))
            job = faj.get_job(eng, out["job_id"])
            self.assertEqual(job["status"], "queued")

    def test_self_heal_runs_inline(self):
        from meeting_pipeline import MeetingPipeline, STATUS_FAILED

        pipe = MeetingPipeline.__new__(MeetingPipeline)
        pipe.engine = MagicMock()
        pipe.check_form_ai = MagicMock(
            return_value=(STATUS_FAILED, "Form AI 覆蓋不足 7/142")
        )
        pipe.start_form_ai_background = MagicMock(
            return_value={
                "ok": True,
                "inline": True,
                "job_id": "j1",
                "exec_mode": "inline",
            }
        )
        with patch("form_ai_batch_job.ensure_jobs_table"), patch(
            "form_ai_batch_job.latest_job", return_value={"job_id": "old", "status": "failed"}
        ), patch("form_ai_batch_job.reconcile_running_job"):
            out = MeetingPipeline.ensure_form_ai_self_heal(pipe, "2026-10-03", "ST")

        kwargs = pipe.start_form_ai_background.call_args.kwargs
        self.assertTrue(kwargs.get("run_inline"))
        self.assertFalse(kwargs.get("enqueue_only"))
        self.assertTrue(kwargs.get("auto_restart"))
        self.assertTrue(out.get("self_heal"))

    def test_inline_job_calls_run_meeting(self):
        from meeting_pipeline import MeetingPipeline

        pipe = MeetingPipeline.__new__(MeetingPipeline)
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
            pipe.engine = eng
            job_id = faj.create_job(
                eng, job_type="form_ai", racing_date="2026-10-03", course="HV"
            )

            with patch(
                "form_ai_batch_job.run_meeting",
                return_value={
                    "ok": True,
                    "done": 12,
                    "budget_exhausted": True,
                    "n_races": 10,
                },
            ) as rm:
                out = MeetingPipeline._run_form_ai_inline_job(
                    pipe,
                    "2026-10-03",
                    "HV",
                    job_id=job_id,
                    only_missing=True,
                    auto_restart=True,
                    detail="test",
                    restart_n=1,
                )
            rm.assert_called_once()
            self.assertTrue(out.get("inline"))
            self.assertTrue(out.get("paused"))
            self.assertTrue(out.get("waiting"))


if __name__ == "__main__":
    unittest.main()
