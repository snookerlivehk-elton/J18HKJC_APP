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

    def test_prune_orphan_races_under_same_meeting(self):
        """upsert 後應刪掉同 prefix 但不在 export 的幽靈場（HV09/10）。"""
        root = Path(__file__).resolve().parents[1]
        fixture = root / "fixtures" / "jjjc_results_ST_20260906_R1.json"
        self.assertTrue(fixture.is_file())

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

            from sqlalchemy import create_engine, text

            # bootstrap schema via first upsert
            payload = json.loads(fixture.read_text(encoding="utf-8"))
            # rewrite fixture race to HV meeting for prune test
            payload["race_date"] = "2026-09-09"
            payload["venue_code"] = "HV"
            race = payload["races"][0]
            race["race_date"] = "2026-09-09"
            race["venue_code"] = "HV"
            race["race_id"] = "20260909HV01"
            race["race_no"] = 1
            sync.upsert_payload(payload)

            eng = create_engine(f"sqlite:///{db_path}")
            with eng.begin() as conn:
                for rn in (9, 10):
                    rid = f"20260909HV{rn:02d}"
                    conn.execute(
                        text(
                            "INSERT OR IGNORE INTO races (race_id, meeting_id, race_num) "
                            "VALUES (:rid, :mid, :rn)"
                        ),
                        {"rid": rid, "mid": "2026-09-09", "rn": rn},
                    )
                    for h in range(1, 15):
                        conn.execute(
                            text(
                                "INSERT INTO runners "
                                "(runner_id, race_id, horse_id, horse_no, finish_order_num, scratched) "
                                "VALUES (:id, :race, :hid, :hn, :fo, 0)"
                            ),
                            {
                                "id": f"{rid}H{h:02d}",
                                "race": rid,
                                "hid": f"UNK_{rid}_{h:02d}",
                                "hn": h,
                                "fo": h,
                            },
                        )
                before = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM runners WHERE race_id LIKE '20260909HV%'"
                    )
                ).scalar()
            self.assertEqual(before, 14 + 28)

            out2 = sync.upsert_payload(payload)
            self.assertTrue(out2["ok"])
            self.assertEqual(sorted(out2.get("pruned_orphan_races") or []), [
                "20260909HV09",
                "20260909HV10",
            ])
            with eng.connect() as conn:
                after = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM runners WHERE race_id LIKE '20260909HV%'"
                    )
                ).scalar()
                races = conn.execute(
                    text(
                        "SELECT race_id FROM races WHERE race_id LIKE '20260909HV%' ORDER BY 1"
                    )
                ).fetchall()
            eng.dispose()
            self.assertEqual(after, 14)
            self.assertEqual([r[0] for r in races], ["20260909HV01"])


if __name__ == "__main__":
    unittest.main()
