"""Smoke test: jjjc.results.v1 fixture → SQLite runners.finish_order_num."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class JjjcResultsSyncTest(unittest.TestCase):
    def test_upsert_fixture_into_sqlite(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "fixtures" / "jjjc_results_ST_20260906_R1.json"
        self.assertTrue(fixture.is_file(), f"missing {fixture}")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_results_sync as sync

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            out = sync.upsert_payload(payload)
            self.assertTrue(out["ok"])
            self.assertEqual(out["race_count"], 1)
            self.assertEqual(out["runner_upserted"], 14)

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            try:
                with eng.connect() as conn:
                    n = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM runners "
                            "WHERE race_id='20260906ST01' AND finish_order_num IS NOT NULL"
                        )
                    ).scalar()
                    winner = (
                        conn.execute(
                            text(
                                "SELECT horse_name, horse_no, finish_order_num FROM runners "
                                "WHERE race_id='20260906ST01' AND finish_order_num=1"
                            )
                        )
                        .mappings()
                        .first()
                    )
                    rid = conn.execute(
                        text(
                            "SELECT runner_id FROM runners "
                            "WHERE race_id='20260906ST01' AND horse_no=13"
                        )
                    ).scalar()
            finally:
                eng.dispose()

            self.assertEqual(n, 14)
            self.assertEqual(winner["horse_name"], "GOOD FORTUNE")
            self.assertEqual(int(winner["horse_no"]), 13)
            self.assertEqual(rid, "20260906ST01H349")


if __name__ == "__main__":
    unittest.main()
