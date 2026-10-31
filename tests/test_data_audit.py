"""資料齊備矩陣／血緣稽核。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class DataAuditTest(unittest.TestCase):
    def _load_fixture_db(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "fixtures" / "jjjc_results_ST_20260906_R1.json"
        db_path = os.path.join(tempfile.mkdtemp(), "audit.db")
        os.environ["USE_SQLITE"] = "true"

        import etl_pipeline
        import jjjc_results_sync as sync
        import sectionals_store as ss

        etl_pipeline.USE_SQLITE = True
        etl_pipeline.SQLITE_DB_PATH = db_path
        sync.USE_SQLITE = True
        sync.SQLITE_DB_PATH = db_path
        sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
        ss.USE_SQLITE = True
        ss.SQLITE_DB_PATH = db_path

        payload = json.loads(fixture.read_text(encoding="utf-8"))
        out = sync.upsert_payload(payload)
        self.assertTrue(out["ok"])
        from sqlalchemy import create_engine

        return create_engine(f"sqlite:///{db_path}"), db_path

    def test_meeting_inventory_and_correctness(self):
        from data_audit import (
            factor_lineage,
            meeting_inventory,
            sectional_correctness_sample,
            window_inventory,
        )

        eng, _ = self._load_fixture_db()
        # fixture race_date vs race.race_date 可能差一日；用 race_id 前綴對應日
        inv = meeting_inventory(eng, "2026-09-06", "ST")
        self.assertGreaterEqual(inv["finish_n"], 14)
        self.assertGreaterEqual(inv["with_sections"], 14)
        self.assertGreaterEqual(inv["section_coverage"], 0.99)
        self.assertEqual(inv["status"], "partial")  # 無評述 → gaps

        df = window_inventory(eng, [("2026-09-06", "ST")])
        self.assertEqual(len(df), 1)
        self.assertEqual(int(df.iloc[0]["有分段"]), 14)

        corr = sectional_correctness_sample(eng, "2026-09-06", "ST", limit=20)
        self.assertFalse(corr.empty)
        self.assertTrue(bool(corr["ok"].all()))

        lin = factor_lineage(eng, "GOOD FORTUNE", limit=5)
        self.assertTrue(lin["form_races"])
        self.assertTrue(lin["pace_races"])
        self.assertEqual(lin["pace_races"][0]["positions_gained"], 6)
        eng.dispose()

    def test_race_sectionals_grid(self):
        from data_audit import list_historical_races, race_sectionals_grid

        eng, _ = self._load_fixture_db()
        races = list_historical_races(eng, "2026-09-06", "ST")
        self.assertFalse(races.empty)
        rid = str(races.iloc[0]["race_id"])
        grid = race_sectionals_grid(eng, rid)
        self.assertEqual(len(grid), 14)
        self.assertIn("走位", grid.columns)
        self.assertIn("S1名次", grid.columns)
        # GOOD FORTUNE finish 1 → 走位 7-7-1
        gf = grid[grid["馬名"] == "GOOD FORTUNE"].iloc[0]
        self.assertEqual(str(gf["走位"]), "7-7-1")
        self.assertEqual(int(gf["名次"]), 1)
        self.assertEqual(int(races.iloc[0]["runner_n"]), 14)
        self.assertEqual(int(races.iloc[0]["finish_n"]), 14)
        eng.dispose()

    def test_backfill_meeting_action_shape(self):
        from data_audit import backfill_meeting_sectionals
        from sqlalchemy import text

        eng, _ = self._load_fixture_db()
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM runner_sections"))
        out = backfill_meeting_sectionals(eng, "2026-09-06", "ST")
        self.assertGreaterEqual(out.get("runners_written", 0), 14)
        self.assertGreaterEqual(out["inventory"]["with_sections"], 14)
        eng.dispose()

    def test_list_meetings_missing_sectional_times_respects_age(self):
        from datetime import date

        from data_audit import list_meetings_missing_sectional_times
        from sqlalchemy import text

        eng, _ = self._load_fixture_db()
        # results fixture 多數只有走位；清秒數確保 time_cov 不足
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runner_sections SET sectional_time = NULL "
                    "WHERE runner_id LIKE '20260906ST%'"
                )
            )
        missing = list_meetings_missing_sectional_times(
            eng,
            as_of=date(2026, 9, 12),  # age=6 ≥ min_age 5
            min_age_days=5,
            max_age_days=30,
            limit=10,
        )
        self.assertTrue(
            any(
                m["racing_date"] == "2026-09-06" and m["course"] == "ST"
                for m in missing
            ),
            missing,
        )
        too_soon = list_meetings_missing_sectional_times(
            eng,
            as_of=date(2026, 9, 8),  # age=2 < 5
            min_age_days=5,
            max_age_days=30,
            limit=10,
        )
        self.assertFalse(
            any(m["racing_date"] == "2026-09-06" for m in too_soon),
            too_soon,
        )
        eng.dispose()

    def test_sync_sectional_times_for_meeting_calls_sectionals(self):
        from unittest.mock import MagicMock, patch

        from data_audit import sync_sectional_times_for_meeting

        pipe = MagicMock()
        pipe.engine = MagicMock()
        pipe.run_action = MagicMock(
            return_value={
                "ok": True,
                "waiting": False,
                "runner_sections_upserted": 10,
            }
        )
        with patch(
            "data_audit.meeting_inventory",
            return_value={
                "finish_n": 10,
                "with_sections": 10,
                "with_sectional_times": 10,
                "sectional_time_coverage": 1.0,
                "sectional_times_ok": True,
                "gaps": [],
                "status": "ok",
            },
        ), patch(
            "data_audit.backfill_meeting_sectionals",
            return_value={"ok": True, "runners_written": 0},
        ):
            out = sync_sectional_times_for_meeting(
                pipe, "2026-09-06", "ST", also_backfill=True
            )
        pipe.run_action.assert_called_with(
            "2026-09-06", "ST", "sync_jjjc_sectionals"
        )
        self.assertTrue(out["sectional_times_ok"])
        self.assertTrue(out["ok"])
        self.assertFalse(out.get("waiting"))


if __name__ == "__main__":
    unittest.main()
