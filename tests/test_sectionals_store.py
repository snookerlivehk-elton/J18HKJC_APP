"""分段走位落庫：解析、jjjc sync 寫入 runner_sections、回填。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class SectionalsStoreTest(unittest.TestCase):
    def test_parse_running_position(self):
        from sectionals_store import parse_running_position, stages_from_runner_payload

        self.assertEqual(parse_running_position("7 7 1"), [7, 7, 1])
        self.assertEqual(parse_running_position("12-10-2"), [12, 10, 2])
        stages = stages_from_runner_payload({"running_position": "7 7 1"})
        self.assertEqual(len(stages), 3)
        self.assertEqual(stages[0]["stage_no"], 1)
        self.assertEqual(stages[0]["position_raw"], "7")
        self.assertEqual(stages[2]["position_raw"], "1")

    def test_j18_sections_preferred(self):
        from sectionals_store import stages_from_runner_payload

        payload = {
            "running_position": "9 9 9",
            "sections": {
                "stage_1": {"position": 2, "sectional_time": "13.2"},
                "stage_2": {"position": 1, "sectional_time": "22.0"},
            },
        }
        stages = stages_from_runner_payload(payload)
        self.assertEqual(stages[0]["position_raw"], "2")
        self.assertEqual(stages[0]["sectional_time"], "13.2")

    def test_jjjc_results_writes_runner_sections(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "fixtures" / "jjjc_results_ST_20260906_R1.json"
        self.assertTrue(fixture.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
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
            self.assertTrue(out["ok"], out)
            self.assertGreater(out.get("runner_sections_upserted", 0), 0)

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            with eng.connect() as conn:
                n = conn.execute(text("SELECT COUNT(*) FROM runner_sections")).scalar()
                sample = conn.execute(
                    text(
                        """
                        SELECT rs.stage_no, rs.position_raw, ru.horse_name, ru.finish_order_num
                        FROM runner_sections rs
                        JOIN runners ru ON ru.runner_id = rs.runner_id
                        WHERE ru.horse_name = 'GOOD FORTUNE'
                        ORDER BY rs.stage_no
                        """
                    )
                ).fetchall()
            eng.dispose()

            self.assertGreaterEqual(int(n or 0), 14)  # ≥1 stage × 14 runners
            self.assertGreaterEqual(len(sample), 3)
            # fixture: GOOD FORTUNE running_position "7 7 1", finish 1
            self.assertEqual(str(sample[0][1]), "7")
            self.assertEqual(str(sample[-1][1]), "1")
            self.assertEqual(int(sample[0][3]), 1)

            cov = ss.coverage_for_prefix(create_engine(f"sqlite:///{db_path}"), "20260906ST")
            self.assertEqual(cov["with_finish"], 14)
            self.assertEqual(cov["with_sections"], 14)
            self.assertGreaterEqual(cov["section_coverage"], 0.99)

            explained = ss.explain_pace_inputs(
                create_engine(f"sqlite:///{db_path}"), "GOOD FORTUNE", limit=5
            )
            self.assertTrue(explained)
            self.assertEqual(explained[0]["early_position"], 7)
            self.assertEqual(explained[0]["positions_gained"], 6)  # 7-1

    def test_backfill_from_raw_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "bf.db")
            os.environ["USE_SQLITE"] = "true"
            import etl_pipeline
            import sectionals_store as ss

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            ss.USE_SQLITE = True
            ss.SQLITE_DB_PATH = db_path
            # init schema
            etl_pipeline.J18ETLPipeline()

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO race_meetings (meeting_id, racing_date, race_count)
                        VALUES ('2026-01-01', '2026-01-01', 1)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO races (race_id, meeting_id, race_num, distance_m)
                        VALUES ('20260101ST01', '2026-01-01', 1, 1200)
                        """
                    )
                )
                raw = json.dumps({"sections": {"stage_1": {"position": 3, "sectional_time": "12.5"}}})
                conn.execute(
                    text(
                        """
                        INSERT INTO runners (
                          runner_id, race_id, horse_id, horse_no, horse_name,
                          finish_order_num, raw_json
                        ) VALUES (
                          '20260101ST01A001', '20260101ST01', 'HK_2026_A001', 1, 'TEST HORSE',
                          2, :raw
                        )
                        """
                    ),
                    {"raw": raw},
                )
            out = ss.backfill_from_runners(eng, limit=10)
            self.assertEqual(out["runners_written"], 1)
            with eng.connect() as conn:
                pos = conn.execute(
                    text(
                        "SELECT position_raw, sectional_time FROM runner_sections WHERE runner_id='20260101ST01A001'"
                    )
                ).fetchone()
            eng.dispose()
            self.assertIsNotNone(pos)
            self.assertEqual(str(pos[0]), "3")
            self.assertEqual(str(pos[1]), "12.5")


if __name__ == "__main__":
    unittest.main()
