"""Smoke test: jjjc.racecard.v1 fixture → SQLite upcoming_*."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class JjjcRacecardSyncTest(unittest.TestCase):
    def test_upsert_fixture_into_sqlite(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "fixtures" / "jjjc_racecard_HV_20260909_R1.json"
        self.assertTrue(fixture.is_file(), f"missing {fixture}")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_racecard_sync as sync

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            out = sync.upsert_payload(payload)
            self.assertTrue(out["ok"])
            self.assertEqual(out["race_count"], 1)
            self.assertEqual(out["runner_upserted"], 2)

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            try:
                with eng.connect() as conn:
                    race = conn.execute(
                        text(
                            "SELECT race_id, course, race_num, distance_m, race_name "
                            "FROM upcoming_races WHERE race_id='20260909HV01'"
                        )
                    ).mappings().first()
                    n = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM upcoming_runners WHERE race_id='20260909HV01'"
                        )
                    ).scalar()
                    first = conn.execute(
                        text(
                            "SELECT horse_name, draw, horse_code, jockey_name "
                            "FROM upcoming_runners WHERE runner_id='20260909HV01_1'"
                        )
                    ).mappings().first()
            finally:
                eng.dispose()

            self.assertEqual(race["course"], "HV")
            self.assertEqual(int(race["race_num"]), 1)
            self.assertEqual(int(race["distance_m"]), 1200)
            self.assertEqual(race["race_name"], "金鐘讓賽")
            self.assertEqual(n, 2)
            self.assertEqual(first["horse_name"], "閃電星福")
            self.assertEqual(int(first["draw"]), 11)
            self.assertEqual(first["horse_code"], "K431")
            self.assertEqual(first["jockey_name"], "布文")


if __name__ == "__main__":
    unittest.main()
