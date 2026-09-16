"""RESULTS readiness vs snapshot coverage + auto-settle after sync."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock, patch


def _setup_sqlite(db_path: str):
    os.environ["USE_SQLITE"] = "true"
    import etl_pipeline
    import meeting_pipeline as mp
    import factor_calibration as fc

    etl_pipeline.USE_SQLITE = True
    etl_pipeline.SQLITE_DB_PATH = db_path
    mp.USE_SQLITE = True
    mp.SQLITE_DB_PATH = db_path
    mp.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
    fc.USE_SQLITE = True
    fc.SQLITE_DB_PATH = db_path
    fc.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
    return mp, fc


class ResultsCoverageGateTest(unittest.TestCase):
    def test_partial_snapshot_races_keep_results_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "cov.db")
            mp, fc = _setup_sqlite(db_path)
            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
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
                # 只有第 1 場有名次
                conn.execute(
                    text(
                        """
                        INSERT INTO runners
                          (runner_id, race_id, horse_no, horse_name, finish_order_num)
                        VALUES
                          ('a', '20260913ST01', 1, 'A', 1),
                          ('b', '20260913ST01', 2, 'B', 2),
                          ('c', '20260913ST02', 1, 'C', NULL),
                          ('d', '20260913ST02', 2, 'D', NULL)
                        """
                    )
                )

            cal = fc.FactorCalibration()
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshot_batches
                          (batch_id, racing_date, course, note)
                        VALUES ('20260913ST_t', :d, 'ST', 't')
                        """
                    ),
                    {"d": date(2026, 9, 13).isoformat()},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshots (
                          batch_id, race_id, horse_no, horse_name,
                          total_score, model_win_prob, pred_rank, finish_order_num
                        ) VALUES
                          ('20260913ST_t', '20260913ST01', 1, 'A', 2, 0.5, 1, NULL),
                          ('20260913ST_t', '20260913ST01', 2, 'B', 1, 0.4, 2, NULL),
                          ('20260913ST_t', '20260913ST02', 1, 'C', 2, 0.5, 1, NULL),
                          ('20260913ST_t', '20260913ST02', 2, 'D', 1, 0.4, 2, NULL)
                        """
                    )
                )

            pipe = mp.MeetingPipeline()
            st, detail = pipe.check_results("2026-09-13", "ST")
            self.assertEqual(st, mp.STATUS_WAITING)
            self.assertIn("1/2", detail)
            self.assertIn("尚缺", detail)

            # 補齊第 2 場 → ok
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE runners SET finish_order_num = 1 "
                        "WHERE race_id='20260913ST02' AND horse_no=1"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE runners SET finish_order_num = 2 "
                        "WHERE race_id='20260913ST02' AND horse_no=2"
                    )
                )
            st2, detail2 = pipe.check_results("2026-09-13", "ST")
            self.assertEqual(st2, mp.STATUS_OK)
            self.assertIn("快照 2 場齊", detail2)

    def test_settled_pending_shows_fill_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "fill.db")
            mp, fc = _setup_sqlite(db_path)
            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
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

            cal = fc.FactorCalibration()
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshot_batches
                          (batch_id, racing_date, course, note)
                        VALUES ('20260913ST_u', :d, 'ST', 'u')
                        """
                    ),
                    {"d": date(2026, 9, 13).isoformat()},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshots (
                          batch_id, race_id, horse_no, horse_name,
                          total_score, model_win_prob, pred_rank, finish_order_num
                        ) VALUES
                          ('20260913ST_u', '20260913ST01', 1, 'A', 2, 0.5, 1, 1),
                          ('20260913ST_u', '20260913ST01', 2, 'B', 1, 0.4, 2, NULL),
                          ('20260913ST_u', '20260913ST02', 1, 'C', 2, 0.5, 1, NULL),
                          ('20260913ST_u', '20260913ST02', 2, 'D', 1, 0.4, 2, NULL)
                        """
                    )
                )

            pipe = mp.MeetingPipeline()
            st, detail = pipe.check_settled("2026-09-13", "ST")
            self.assertEqual(st, mp.STATUS_PENDING)
            self.assertIn("達標", detail)
            self.assertIn("1/2", detail)


class AutoSettleAfterResultsTest(unittest.TestCase):
    def test_sync_results_chains_settle_when_ready(self):
        from unittest.mock import patch

        import meeting_pipeline as mp

        pipe = mp.MeetingPipeline.__new__(mp.MeetingPipeline)
        pipe.refresh_readiness = MagicMock()
        pipe.check_results = MagicMock(return_value=(mp.STATUS_OK, "ok"))
        pipe.check_snapshot = MagicMock(return_value=(mp.STATUS_OK, "snap"))
        pipe.check_settled = MagicMock(return_value=(mp.STATUS_PENDING, "pending"))
        pipe._maybe_run_post_race_ads_after_settle = MagicMock(
            return_value={"ok": True, "actions": [{"action": "promo_hits", "ok": True}]}
        )

        sync_out = {"ok": True, "runner_upserted": 10, "race_count": 2}
        settle_out = {
            "ok": True,
            "settled_batches": ["bid"],
            "updated_rows": 10,
            "message": "done",
        }
        with patch("jjjc_results_sync.sync_meeting", return_value=sync_out), patch(
            "factor_calibration.FactorCalibration"
        ) as Cal:
            Cal.return_value.settle_pending.return_value = settle_out
            out = mp.MeetingPipeline.run_action(
                pipe, "2026-09-13", "ST", "sync_jjjc_results"
            )
        self.assertTrue(out.get("ok"))
        self.assertEqual(
            (out.get("auto_settle") or {}).get("settled_batches"), ["bid"]
        )
        self.assertIn("auto_post_race_ads", out.get("auto_settle") or {})
        self.assertIn("auto_post_race_ads", out)
        Cal.return_value.settle_pending.assert_called_once()
        pipe._maybe_run_post_race_ads_after_settle.assert_called()

    def test_sync_results_skips_settle_when_results_incomplete(self):
        import meeting_pipeline as mp

        pipe = mp.MeetingPipeline.__new__(mp.MeetingPipeline)
        pipe.refresh_readiness = MagicMock()
        pipe.check_results = MagicMock(return_value=(mp.STATUS_WAITING, "partial"))
        pipe.check_snapshot = MagicMock(return_value=(mp.STATUS_OK, "snap"))
        pipe.check_settled = MagicMock(return_value=(mp.STATUS_PENDING, "pending"))

        with patch(
            "jjjc_results_sync.sync_meeting",
            return_value={"ok": True, "runner_upserted": 1, "race_count": 1},
        ), patch("factor_calibration.FactorCalibration") as Cal:
            out = mp.MeetingPipeline.run_action(
                pipe, "2026-09-13", "ST", "sync_jjjc_results"
            )
        self.assertNotIn("auto_settle", out)
        Cal.return_value.settle_pending.assert_not_called()

    def test_settle_action_triggers_post_race_ads_when_already_settled(self):
        """已 SETTLED 再按結算，仍應補跑 promo／文案（今日漏產救援）。"""
        import meeting_pipeline as mp

        pipe = mp.MeetingPipeline.__new__(mp.MeetingPipeline)
        pipe.refresh_readiness = MagicMock()
        pipe.check_settled = MagicMock(return_value=(mp.STATUS_OK, "已結算"))
        ads = {
            "ok": True,
            "actions": [
                {"action": "promo_hits", "ok": True, "n_promo_races": 1},
                {"action": "post_race_copy", "ok": True},
            ],
        }
        pipe._maybe_run_post_race_ads_after_settle = MagicMock(return_value=ads)

        settle_out = {
            "ok": True,
            "settled_batches": [],
            "updated_rows": 0,
            "message": "沒有未結算的快照 batch",
        }
        with patch("factor_calibration.FactorCalibration") as Cal:
            Cal.return_value.settle_pending.return_value = settle_out
            out = mp.MeetingPipeline.run_action(pipe, "2026-09-16", "HV", "settle")
        self.assertEqual(out.get("auto_post_race_ads"), ads)
        pipe._maybe_run_post_race_ads_after_settle.assert_called_once()

    def test_maybe_run_ads_skips_when_not_settled(self):
        import meeting_pipeline as mp

        pipe = mp.MeetingPipeline.__new__(mp.MeetingPipeline)
        pipe.check_settled = MagicMock(return_value=(mp.STATUS_PENDING, "pending"))
        out = mp.MeetingPipeline._maybe_run_post_race_ads_after_settle(
            pipe, "2026-09-16", "HV", {"settled_batches": []}
        )
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
