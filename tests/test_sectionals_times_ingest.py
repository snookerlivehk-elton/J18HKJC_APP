"""ST 2026-09-06 R1：賽果只有走位；R2 sectionals 先有秒數。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class SectionalsTimesIngestTest(unittest.TestCase):
    def test_results_alone_has_positions_not_times(self):
        root = Path(__file__).resolve().parents[1]
        results_fx = root / "fixtures" / "jjjc_results_ST_20260906_R1.json"
        self.assertTrue(results_fx.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "t.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_results_sync as rsync
            from sqlalchemy import create_engine, text

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            rsync.USE_SQLITE = True
            rsync.SQLITE_DB_PATH = db_path
            rsync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            out = rsync.upsert_payload(json.loads(results_fx.read_text(encoding="utf-8")))
            self.assertTrue(out["ok"])

            eng = create_engine(f"sqlite:///{db_path}")
            with eng.connect() as conn:
                with_pos = conn.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT rs.runner_id) FROM runner_sections rs
                        JOIN runners ru ON ru.runner_id = rs.runner_id
                        WHERE ru.race_id='20260906ST01' AND rs.position_raw IS NOT NULL
                        """
                    )
                ).scalar()
                with_time = conn.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT rs.runner_id) FROM runner_sections rs
                        JOIN runners ru ON ru.runner_id = rs.runner_id
                        WHERE ru.race_id='20260906ST01'
                          AND rs.sectional_time IS NOT NULL
                          AND TRIM(rs.sectional_time) != ''
                        """
                    )
                ).scalar()
            eng.dispose()
            self.assertEqual(int(with_pos or 0), 14)
            self.assertEqual(int(with_time or 0), 0)

    def test_sectionals_export_fills_times_after_results(self):
        root = Path(__file__).resolve().parents[1]
        results_fx = root / "fixtures" / "jjjc_results_ST_20260906_R1.json"
        sec_fx = root / "fixtures" / "jjjc_sectionals_ST_20260906_R1.json"
        self.assertTrue(results_fx.is_file())
        self.assertTrue(sec_fx.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "t.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_results_sync as rsync
            import jjjc_sectionals_sync as ssync
            from sqlalchemy import create_engine, text

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            rsync.USE_SQLITE = True
            rsync.SQLITE_DB_PATH = db_path
            rsync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
            ssync.USE_SQLITE = True
            ssync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            rsync.upsert_payload(json.loads(results_fx.read_text(encoding="utf-8")))
            out = ssync.upsert_payload(json.loads(sec_fx.read_text(encoding="utf-8")))
            self.assertTrue(out["ok"])
            self.assertFalse(out.get("waiting"))
            self.assertEqual(out.get("runners_with_sections"), 14)

            eng = create_engine(f"sqlite:///{db_path}")
            with eng.connect() as conn:
                with_time = conn.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT rs.runner_id) FROM runner_sections rs
                        JOIN runners ru ON ru.runner_id = rs.runner_id
                        WHERE ru.race_id='20260906ST01'
                          AND rs.sectional_time IS NOT NULL
                          AND TRIM(rs.sectional_time) != ''
                        """
                    )
                ).scalar()
                sample = conn.execute(
                    text(
                        """
                        SELECT rs.sectional_time FROM runner_sections rs
                        JOIN runners ru ON ru.runner_id = rs.runner_id
                        WHERE ru.race_id='20260906ST01' AND ru.horse_no=13 AND rs.stage_no=1
                        """
                    )
                ).scalar()
            eng.dispose()
            self.assertEqual(int(with_time or 0), 14)
            self.assertEqual(str(sample), "24.13")


if __name__ == "__main__":
    unittest.main()
