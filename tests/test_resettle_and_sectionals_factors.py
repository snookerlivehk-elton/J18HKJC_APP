"""resettle_meeting + sectional-times → factors auto recompute."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import ANY, MagicMock, patch


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


class ResettleMeetingTest(unittest.TestCase):
    def test_resettle_updates_finish_and_refreshes_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "re.db")
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
                          finish_order_num INT,
                          win_probability_raw TEXT,
                          raw_json TEXT
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO runners
                          (runner_id, race_id, horse_no, horse_name, finish_order_num)
                        VALUES
                          ('a', '20260913ST01', 1, 'A', 2),
                          ('b', '20260913ST01', 2, 'B', 1)
                        """
                    )
                )

            cal = fc.FactorCalibration()
            settled_at = datetime.now(timezone.utc).isoformat()
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshot_batches
                          (batch_id, racing_date, course, note, settled_at)
                        VALUES ('20260913ST_re', :d, 'ST', 're', :s)
                        """
                    ),
                    {"d": date(2026, 9, 13).isoformat(), "s": settled_at},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshots (
                          batch_id, race_id, horse_no, horse_name,
                          total_score, model_win_prob, pred_rank, finish_order_num
                        ) VALUES
                          ('20260913ST_re', '20260913ST01', 1, 'A', 2, 0.5, 1, 1),
                          ('20260913ST_re', '20260913ST01', 2, 'B', 1, 0.4, 2, 2)
                        """
                    )
                )

            with patch.object(
                cal, "snapshot_hit_rates_for_batch", return_value={"ok": True}
            ) as hit:
                out = cal.resettle_meeting("2026-09-13", "ST")

            self.assertTrue(out.get("ok"), out)
            self.assertTrue(out.get("changed"), out)
            self.assertGreaterEqual(int(out.get("updated_rows") or 0), 2)
            self.assertIn("20260913ST_re", out.get("refreshed_hit_batches") or [])
            hit.assert_called_with("20260913ST_re")

            with eng.connect() as conn:
                rows = {
                    int(r[0]): int(r[1])
                    for r in conn.execute(
                        text(
                            "SELECT horse_no, finish_order_num FROM prediction_snapshots "
                            "WHERE batch_id='20260913ST_re'"
                        )
                    )
                }
            self.assertEqual(rows[1], 2)
            self.assertEqual(rows[2], 1)

    def test_resettle_unchanged_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "noop.db")
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
                conn.execute(
                    text(
                        """
                        INSERT INTO runners
                          (runner_id, race_id, horse_no, horse_name, finish_order_num)
                        VALUES ('a', '20260913ST01', 1, 'A', 1)
                        """
                    )
                )

            cal = fc.FactorCalibration()
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshot_batches
                          (batch_id, racing_date, course, note, settled_at)
                        VALUES ('20260913ST_n', :d, 'ST', 'n', :s)
                        """
                    ),
                    {
                        "d": date(2026, 9, 13).isoformat(),
                        "s": datetime.now(timezone.utc).isoformat(),
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshots (
                          batch_id, race_id, horse_no, horse_name,
                          total_score, model_win_prob, pred_rank, finish_order_num
                        ) VALUES
                          ('20260913ST_n', '20260913ST01', 1, 'A', 2, 0.5, 1, 1)
                        """
                    )
                )

            with patch.object(cal, "snapshot_hit_rates_for_batch") as hit:
                out = cal.resettle_meeting("2026-09-13", "ST")
            self.assertTrue(out.get("ok"), out)
            self.assertFalse(out.get("changed"), out)
            hit.assert_not_called()


class SectionalsFactorsHookTest(unittest.TestCase):
    def test_maybe_recompute_factors_when_times_ok(self):
        import meeting_pipeline as mp

        pipe = mp.MeetingPipeline.__new__(mp.MeetingPipeline)
        pipe.engine = MagicMock()
        pipe.refresh_readiness = MagicMock()

        with patch("data_audit.meeting_inventory", return_value={
            "sectional_times_ok": True,
            "sectional_time_coverage": 1.0,
        }), patch("factor_calculator.FactorCalculator") as Calc:
            Calc.return_value.run_all_factors.return_value = (1, 2, 3, 4, 5, 6, 7, 8)
            out = mp.MeetingPipeline._maybe_recompute_factors_after_sectionals(
                pipe, "2026-09-16", "HV"
            )
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out.get("reason"), "sectional_times_ok")
        Calc.return_value.run_all_factors.assert_called_once()

    def test_maybe_recompute_factors_skips_when_times_not_ok(self):
        import meeting_pipeline as mp

        pipe = mp.MeetingPipeline.__new__(mp.MeetingPipeline)
        pipe.engine = MagicMock()
        with patch(
            "data_audit.meeting_inventory",
            return_value={"sectional_times_ok": False, "sectional_time_coverage": 0.1},
        ), patch("factor_calculator.FactorCalculator") as Calc:
            out = mp.MeetingPipeline._maybe_recompute_factors_after_sectionals(
                pipe, "2026-09-16", "HV"
            )
        self.assertIsNone(out)
        Calc.return_value.run_all_factors.assert_not_called()

    def test_sectionals_times_pass_triggers_factors(self):
        import data_audit as da
        from meeting_tick import MeetingTickRunner, TickGuards, SECTIONALS_TIMES_STAGE

        pipe = MagicMock()
        pipe.engine = MagicMock()
        pipe._maybe_recompute_factors_after_sectionals = MagicMock(
            return_value={"ok": True, "reason": "sectional_times_ok"}
        )
        runner = MeetingTickRunner.__new__(MeetingTickRunner)
        runner.pipe = pipe
        runner.guards = TickGuards(force=True)
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
        candidates = [
            {
                "racing_date": "2026-09-16",
                "course": "HV",
                "age_days": 10,
                "sectional_time_coverage": 0.0,
            }
        ]
        sync_out = {
            "ok": True,
            "waiting": False,
            "sectional_times_ok": True,
            "inventory": {
                "sectional_time_coverage": 1.0,
                "sectional_times_ok": True,
                "status": "ok",
            },
            "sectionals_export": {"ok": True, "waiting": False, "status": "ready"},
        }
        with patch.object(
            da, "list_meetings_missing_sectional_times", return_value=candidates
        ), patch.object(da, "sync_sectional_times_for_meeting", return_value=sync_out):
            out = runner.run_sectionals_times_pass(
                as_of=date(2026, 9, 26), dry_run=False, limit=5
            )
        self.assertEqual(out["n_ok"], 1)
        meeting = out["meetings"][0]
        self.assertEqual(
            (meeting.get("auto_factors") or {}).get("reason"), "sectional_times_ok"
        )
        pipe._maybe_recompute_factors_after_sectionals.assert_called_once_with(
            "2026-09-16", "HV"
        )
        runner.record_tick_attempt.assert_called_with(
            "2026-09-16",
            "HV",
            SECTIONALS_TIMES_STAGE,
            ok=True,
            status="ok",
            detail=ANY,
        )


if __name__ == "__main__":
    unittest.main()
