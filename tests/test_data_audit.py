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

    def test_backfill_meeting_action_shape(self):
        from data_audit import backfill_meeting_sectionals

        eng, _ = self._load_fixture_db()
        # wipe sections then backfill
        from sqlalchemy import text

        with eng.begin() as conn:
            conn.execute(text("DELETE FROM runner_sections"))
        out = backfill_meeting_sectionals(eng, "2026-09-06", "ST")
        self.assertGreaterEqual(out.get("runners_written", 0), 14)
        self.assertGreaterEqual(out["inventory"]["with_sections"], 14)
        eng.dispose()


if __name__ == "__main__":
    unittest.main()
