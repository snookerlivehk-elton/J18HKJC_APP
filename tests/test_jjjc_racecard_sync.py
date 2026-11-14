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

    def test_sync_meeting_auto_fetch_when_export_empty(self):
        """export 空時應自動 POST /api/racecard/fetch，再 re-export 入庫。"""
        from unittest.mock import patch

        import jjjc_racecard_sync as sync

        empty = {
            "schema": "jjjc.racecard.v1",
            "race_date": "2026-11-01",
            "venue_code": "HV",
            "race_count": 0,
            "runner_count": 0,
            "races": [],
        }
        filled = {
            "schema": "jjjc.racecard.v1",
            "race_date": "2026-11-01",
            "venue_code": "HV",
            "race_count": 1,
            "runner_count": 1,
            "races": [
                {
                    "race_id": "20261101HV01",
                    "race_no": 1,
                    "race_date": "2026-11-01",
                    "venue_code": "HV",
                    "distance_m": 1200,
                    "runners": [
                        {
                            "horse_no": 1,
                            "horse_name": "測試駒",
                            "horse_code": "K999",
                            "draw": 1,
                            "jockey_name": "測試騎",
                            "trainer_name": "測試練",
                        }
                    ],
                }
            ],
        }
        fetch_calls = {"n": 0}
        export_calls = {"n": 0}

        def _fake_export(**kwargs):
            export_calls["n"] += 1
            return empty if export_calls["n"] == 1 else filled

        def _fake_fetch(race_date, venue, **kwargs):
            fetch_calls["n"] += 1
            return {
                "ok": True,
                "race_count": 1,
                "runner_count": 1,
                "race_date": race_date,
                "venue_code": venue,
            }

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            os.environ["USE_SQLITE"] = "true"
            import etl_pipeline

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            with patch.object(sync, "fetch_export", side_effect=_fake_export), patch.object(
                sync, "trigger_racecard_fetch", side_effect=_fake_fetch
            ):
                out = sync.sync_meeting("2026-11-01", "HV")

            self.assertTrue(out.get("ok"), out)
            self.assertTrue(out.get("auto_fetched"), out)
            self.assertEqual(fetch_calls["n"], 1)
            self.assertGreaterEqual(export_calls["n"], 2)
            self.assertGreaterEqual(int(out.get("runner_upserted") or 0), 1)

    def test_sync_meeting_still_empty_after_fetch_is_waiting(self):
        from unittest.mock import patch

        import jjjc_racecard_sync as sync

        empty = {
            "schema": "jjjc.racecard.v1",
            "race_date": "2026-11-01",
            "venue_code": "HV",
            "races": [],
        }
        with patch.object(sync, "fetch_export", return_value=empty), patch.object(
            sync,
            "trigger_racecard_fetch",
            return_value={"ok": False, "error": "WHITELIST_ERROR", "status_code": 502},
        ):
            out = sync.sync_meeting("2026-11-01", "HV")
        self.assertFalse(out.get("ok"), out)
        self.assertTrue(out.get("waiting"), out)
        self.assertIn("無排位", str(out.get("detail") or out.get("error") or ""))


if __name__ == "__main__":
    unittest.main()
