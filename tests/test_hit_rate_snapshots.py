"""Tests for hit_rate_day_snapshots backfill / aggregate."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date


class HitRateSnapshotTest(unittest.TestCase):
    def test_snapshot_and_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "hit.db")
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
            cal = fc.FactorCalibration()
            d = date(2026, 9, 6).isoformat()

            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshot_batches
                          (batch_id, racing_date, course, note, settled_at)
                        VALUES ('20260906ST_hit', :d, 'ST', 'test', :d)
                        """
                    ),
                    {"d": d},
                )
                rows = [
                    (1, 1, 10.0, 0.40, 1.0),
                    (2, 2, 8.0, 0.30, 1.0),
                    (3, 3, 5.0, 0.20, 1.0),
                    (4, 4, 2.0, 0.10, 1.0),
                ]
                for hno, fin, tot, mp, zd in rows:
                    conn.execute(
                        text(
                            """
                            INSERT INTO prediction_snapshots (
                              batch_id, race_id, horse_no, horse_name,
                              z_jockey, z_trainer, z_synergy, z_draw,
                              z_horse, z_pace, z_speed, sg_contrib,
                              total_score, model_win_prob, pred_rank,
                              finish_order_num
                            ) VALUES (
                              '20260906ST_hit', '20260906ST01', :hno, :name,
                              0, 0, 0, :zd,
                              0, 0, 0, 0,
                              :tot, :mp, :rank, :fin
                            )
                            """
                        ),
                        {
                            "hno": hno,
                            "name": f"H{hno}",
                            "zd": zd,
                            "tot": tot,
                            "mp": mp,
                            "rank": hno,
                            "fin": fin,
                        },
                    )

            out = cal.snapshot_hit_rates_for_batch("20260906ST_hit")
            self.assertTrue(out.get("ok"), out)
            self.assertGreater(out.get("n_signals", 0), 0)

            snap = cal.load_hit_rate_day_snapshots(batch_ids=["20260906ST_hit"])
            self.assertFalse(snap.empty)
            self.assertIn("pq_pct", snap.columns)
            self.assertIn("wq_pct", snap.columns)

            overall, day_top, meta = cal.evaluate_raceday_rankings(
                only_settled=True, metric="WIN%", top_n=3, prefer_snapshot=True
            )
            self.assertTrue(meta.get("from_snapshot"))
            self.assertFalse(overall.empty)
            self.assertIn("PQ%", overall.columns)


if __name__ == "__main__":
    unittest.main()
