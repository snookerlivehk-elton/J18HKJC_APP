"""Settle must match by horse_no when snapshot (ZH) ≠ results (EN) names."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date


class SettleHorseNoMatchTest(unittest.TestCase):
    def test_settle_matches_chinese_snapshot_to_english_results_by_no(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "settle.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import factor_calibration as fc

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            fc.USE_SQLITE = True
            fc.SQLITE_DB_PATH = db_path
            fc.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            # minimal schema
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE runners (
                          runner_id TEXT PRIMARY KEY,
                          race_id TEXT,
                          horse_no INT,
                          horse_name TEXT,
                          finish_order_num INT
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO runners (runner_id, race_id, horse_no, horse_name, finish_order_num)
                        VALUES
                          ('r1', '20260906ST01', 13, 'GOOD FORTUNE', 1),
                          ('r2', '20260906ST01', 7, 'SO MY FOLKS', 2),
                          ('r3', '20260906ST01', 2, 'FOREVER FANCY', 3)
                        """
                    )
                )

            cal = fc.FactorCalibration()
            # tables for snapshots created by ensure_tables
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshot_batches
                          (batch_id, racing_date, course, note)
                        VALUES ('20260906ST_test', :d, 'ST', 'test')
                        """
                    ),
                    {"d": date(2026, 9, 6).isoformat()},
                )
                # Chinese names in snapshot (as racecard) — would fail name-only match
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshots (
                          batch_id, race_id, horse_no, horse_name,
                          total_score, model_win_prob, pred_rank, finish_order_num
                        ) VALUES
                          ('20260906ST_test', '20260906ST01', 13, '好運來', 3.0, 0.4, 1, NULL),
                          ('20260906ST_test', '20260906ST01', 7, '我的夥伴', 2.0, 0.3, 2, NULL),
                          ('20260906ST_test', '20260906ST01', 2, '永遠花巧', 1.0, 0.2, 3, NULL)
                        """
                    )
                )

            out = cal.settle_pending()
            self.assertTrue(out["ok"])
            self.assertEqual(out["updated_rows"], 3)
            self.assertIn("20260906ST_test", out["settled_batches"])

            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT horse_no, finish_order_num FROM prediction_snapshots "
                        "WHERE batch_id='20260906ST_test' ORDER BY horse_no"
                    )
                ).fetchall()
            by_no = {int(r[0]): int(r[1]) for r in rows}
            self.assertEqual(by_no[13], 1)
            self.assertEqual(by_no[7], 2)
            self.assertEqual(by_no[2], 3)

            settled_at = eng.connect().execute(
                text(
                    "SELECT settled_at FROM prediction_snapshot_batches "
                    "WHERE batch_id='20260906ST_test'"
                )
            ).scalar()
            self.assertIsNotNone(settled_at)


if __name__ == "__main__":
    unittest.main()
