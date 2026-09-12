"""Smoke: background_jobs table create/update on SQLite."""
from __future__ import annotations

import os
import tempfile
import unittest


class FormAIJobTableTest(unittest.TestCase):
    def test_create_and_update_job(self):
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
            job_id = faj.create_job(
                eng, job_type="form_ai", racing_date="2026-09-06", course="ST"
            )
            self.assertTrue(job_id)
            faj.update_job(
                eng,
                job_id,
                status="running",
                detail="test",
                progress={"race_index": 1, "race_count": 2},
            )
            job = faj.get_job(eng, job_id)
            self.assertIsNotNone(job)
            self.assertEqual(job["status"], "running")
            latest = faj.latest_job(
                eng, job_type="form_ai", racing_date="2026-09-06", course="ST"
            )
            self.assertEqual(latest["job_id"], job_id)

    def test_reconcile_stale_spawned_marks_failed(self):
        """spawned 逾時 → failed（唔再單靠 PID；跨容器寬限內唔殺）。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            os.environ["USE_SQLITE"] = "true"
            os.environ["FORM_AI_SPAWNED_STALE_SEC"] = "60"

            import etl_pipeline
            import form_ai_batch_job as faj
            from datetime import datetime, timedelta, timezone

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            faj.USE_SQLITE = True
            faj.SQLITE_DB_PATH = db_path
            faj.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            job_id = faj.create_job(
                eng, job_type="form_ai", racing_date="2026-09-13", course="ST"
            )
            faj.update_job(
                eng,
                job_id,
                status="running",
                detail="pid=999999",
                progress={"phase": "spawned", "pid": 999999, "log": "/tmp/missing.log"},
            )
            old = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
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
                import json

                prog = json.loads(prog)
            self.assertEqual(prog.get("phase"), "dead")
            self.assertTrue(prog.get("reconciled"))

    def test_reconcile_fresh_spawned_waits_grace(self):
        """剛 spawned 未逾時：即使 PID 喺本容器唔存在，亦唔即時 failed。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            os.environ["USE_SQLITE"] = "true"
            os.environ["FORM_AI_SPAWNED_STALE_SEC"] = "120"

            import etl_pipeline
            import form_ai_batch_job as faj

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            faj.USE_SQLITE = True
            faj.SQLITE_DB_PATH = db_path
            faj.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            from sqlalchemy import create_engine

            eng = create_engine(f"sqlite:///{db_path}")
            job_id = faj.create_job(
                eng, job_type="form_ai", racing_date="2026-09-13", course="ST"
            )
            faj.update_job(
                eng,
                job_id,
                status="running",
                detail="pid=999999",
                progress={"phase": "spawned", "pid": 999999, "log": "/tmp/missing.log"},
            )
            out = faj.reconcile_running_job(eng, faj.get_job(eng, job_id))
            self.assertEqual(out["status"], "running")
            prog = out.get("progress_json") or {}
            if isinstance(prog, str):
                import json

                prog = json.loads(prog)
            self.assertEqual(prog.get("phase"), "spawned")

    def test_reconcile_stale_spawned_even_if_pid_alive(self):
        """跨容器 PID 重用：spawned 逾時即使 pid 仍存活也要 failed。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            os.environ["USE_SQLITE"] = "true"
            os.environ["FORM_AI_SPAWNED_STALE_SEC"] = "60"

            import etl_pipeline
            import form_ai_batch_job as faj
            from datetime import datetime, timedelta, timezone

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            faj.USE_SQLITE = True
            faj.SQLITE_DB_PATH = db_path
            faj.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            job_id = faj.create_job(
                eng, job_type="form_ai", racing_date="2026-09-13", course="ST"
            )
            faj.update_job(
                eng,
                job_id,
                status="running",
                detail="pid=self",
                progress={
                    "phase": "spawned",
                    "pid": os.getpid(),  # 存活但唔係 form ai worker
                    "log": "/tmp/missing.log",
                },
            )
            old = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
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
                import json

                prog = json.loads(prog)
            self.assertEqual(prog.get("phase"), "dead")


if __name__ == "__main__":
    unittest.main()
