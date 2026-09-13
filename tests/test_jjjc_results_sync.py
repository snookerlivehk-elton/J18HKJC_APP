"""Smoke test: jjjc.results.v1 fixture → SQLite runners.finish_order_num."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class JjjcResultsSyncTest(unittest.TestCase):
    def test_clip_varchar_fields(self):
        import jjjc_results_sync as sync

        self.assertEqual(sync._clip(None, 50), None)
        self.assertEqual(sync._clip("短", 50), "短")
        long = "G" * 80
        clipped = sync._clip(long, 50)
        self.assertEqual(len(clipped), 50)
        self.assertTrue(clipped.endswith("…"))

    def test_upsert_truncates_long_going_for_varchar50(self):
        """PG races.ground/course 為 VARCHAR(50)；超長 going 不可令整日 sync 回滾。"""
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

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            long_going = (
                "GOOD TO FIRM — SECTIONAL TIMES DISPLAYED IN TENTHS OF A SECOND "
                "ON THE GLENEALY HANDICAP TURF A COURSE (OFFICIAL)"
            )
            self.assertGreater(len(long_going), 50)
            payload["races"][0]["going"] = long_going
            payload["races"][0]["course"] = "TURF - \"A+3\" Course " + ("X" * 40)
            out = sync.upsert_payload(payload)
            self.assertTrue(out["ok"], out)

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            with eng.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT ground, course FROM races WHERE race_id='20260906ST01'"
                    )
                ).mappings().first()
            eng.dispose()
            self.assertIsNotNone(row)
            self.assertLessEqual(len(row["ground"] or ""), 50)
            self.assertLessEqual(len(row["course"] or ""), 50)
            self.assertTrue((row["ground"] or "").startswith("GOOD TO FIRM"))

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

    def test_partial_export_does_not_prune_finished_later_races(self):
        """賽中只同步到 R1 時，不可刪已有名次的 R6+（否則會出現 5/10 缺口）。"""
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

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            payload["race_date"] = "2026-09-13"
            payload["venue_code"] = "ST"
            race = payload["races"][0]
            race["race_date"] = "2026-09-13"
            race["venue_code"] = "ST"
            race["race_id"] = "20260913ST01"
            race["race_no"] = 1
            sync.upsert_payload(payload)

            eng = create_engine(f"sqlite:///{db_path}")
            with eng.begin() as conn:
                for rn in (6, 7):
                    rid = f"20260913ST{rn:02d}"
                    conn.execute(
                        text(
                            "INSERT OR IGNORE INTO races (race_id, meeting_id, race_num) "
                            "VALUES (:rid, :mid, :rn)"
                        ),
                        {"rid": rid, "mid": "2026-09-13", "rn": rn},
                    )
                    for h in range(1, 3):
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

            out2 = sync.upsert_payload(payload)
            self.assertTrue(out2["ok"])
            self.assertEqual(out2.get("pruned_orphan_races") or [], [])
            with eng.connect() as conn:
                left = conn.execute(
                    text(
                        "SELECT race_id FROM races WHERE race_id LIKE '20260913ST%' "
                        "ORDER BY 1"
                    )
                ).fetchall()
            eng.dispose()
            self.assertEqual(
                [r[0] for r in left],
                ["20260913ST01", "20260913ST06", "20260913ST07"],
            )

    def test_full_card_export_prunes_ghost_hv09_hv10(self):
        """完整 1..8 卡同步後，應刪掉 HV09/10 幽靈場。"""
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
            import copy

            base = json.loads(fixture.read_text(encoding="utf-8"))
            payload = copy.deepcopy(base)
            payload["race_date"] = "2026-09-09"
            payload["venue_code"] = "HV"
            payload["races"] = []
            for rn in range(1, 9):
                race = copy.deepcopy(base["races"][0])
                race["race_date"] = "2026-09-09"
                race["venue_code"] = "HV"
                race["race_id"] = f"20260909HV{rn:02d}"
                race["race_no"] = rn
                payload["races"].append(race)
            payload["race_count"] = 8
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

            out2 = sync.upsert_payload(payload)
            self.assertTrue(out2["ok"])
            self.assertEqual(
                sorted(out2.get("pruned_orphan_races") or []),
                ["20260909HV09", "20260909HV10"],
            )
            with eng.connect() as conn:
                races = conn.execute(
                    text(
                        "SELECT race_id FROM races WHERE race_id LIKE '20260909HV%' "
                        "ORDER BY 1"
                    )
                ).fetchall()
            eng.dispose()
            self.assertEqual(
                [r[0] for r in races],
                [f"20260909HV{n:02d}" for n in range(1, 9)],
            )


if __name__ == "__main__":
    unittest.main()
