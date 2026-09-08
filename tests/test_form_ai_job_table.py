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


if __name__ == "__main__":
    unittest.main()
