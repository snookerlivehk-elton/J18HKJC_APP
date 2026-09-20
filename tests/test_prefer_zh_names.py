"""Prefer Chinese display names for horse/jockey/trainer."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class PreferZhNamesTest(unittest.TestCase):
    def test_prefer_zh_helpers(self):
        from jjjc_export_common import (
            display_horse_name,
            looks_latin_name,
            prefer_zh_text,
        )

        self.assertTrue(looks_latin_name("FORTUNATE SON"))
        self.assertFalse(looks_latin_name("將義"))
        self.assertEqual(prefer_zh_text("FORTUNATE SON", "將義"), "將義")
        self.assertEqual(prefer_zh_text("將義", "FORTUNATE SON"), "將義")
        self.assertEqual(
            display_horse_name(
                {"horse_name": "FORTUNATE SON", "horse_name_ch": "將義"}
            ),
            "將義",
        )

    def test_results_uses_upcoming_chinese_names(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "fixtures" / "jjjc_results_ST_20260906_R1.json"
        self.assertTrue(fixture.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "t.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_results_sync as sync
            from sqlalchemy import create_engine, text

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            sync._ensure_sqlite_schema()
            eng = create_engine(f"sqlite:///{db_path}")
            # upcoming schema may differ; create minimal table if missing
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS upcoming_runners (
                          runner_id TEXT PRIMARY KEY,
                          race_id TEXT,
                          horse_no INTEGER,
                          horse_name TEXT,
                          horse_code TEXT,
                          jockey_name TEXT,
                          trainer_name TEXT
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO upcoming_runners
                          (runner_id, race_id, horse_no, horse_name, horse_code,
                           jockey_name, trainer_name)
                        VALUES
                          ('u1', '20260906ST01', 13, '同有運', 'H349', '潘頓', '蔡約翰')
                        """
                    )
                )

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            out = sync.upsert_payload(payload)
            self.assertTrue(out["ok"])

            with eng.connect() as conn:
                row = (
                    conn.execute(
                        text(
                            """
                            SELECT horse_name, jockey_name, trainer_name, brand_num
                            FROM runners
                            WHERE race_id='20260906ST01' AND horse_no=13
                            """
                        )
                    )
                    .mappings()
                    .first()
                )
            eng.dispose()
            self.assertIsNotNone(row)
            self.assertEqual(row["horse_name"], "同有運")
            self.assertEqual(row["brand_num"], "H349")
            self.assertEqual(row["jockey_name"], "潘頓")
            self.assertEqual(row["trainer_name"], "蔡約翰")

    def test_sectionals_overwrites_english_horse_name(self):
        root = Path(__file__).resolve().parents[1]
        results_fx = root / "fixtures" / "jjjc_results_ST_20260906_R1.json"
        sec_fx = root / "fixtures" / "jjjc_sectionals_ST_20260906_R1.json"
        self.assertTrue(results_fx.is_file() and sec_fx.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "t.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_results_sync as rsync
            import jjjc_sectionals_sync as ssync
            from sqlalchemy import create_engine, text

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            rsync.USE_SQLITE = True
            rsync.SQLITE_DB_PATH = db_path
            rsync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
            ssync.USE_SQLITE = True
            ssync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            rsync.upsert_payload(json.loads(results_fx.read_text(encoding="utf-8")))
            # results alone → English
            eng = create_engine(f"sqlite:///{db_path}")
            with eng.connect() as conn:
                before = conn.execute(
                    text(
                        "SELECT horse_name FROM runners "
                        "WHERE race_id='20260906ST01' AND horse_no=13"
                    )
                ).scalar()
            self.assertEqual(before, "GOOD FORTUNE")

            ssync.upsert_payload(json.loads(sec_fx.read_text(encoding="utf-8")))
            with eng.connect() as conn:
                after = conn.execute(
                    text(
                        "SELECT horse_name FROM runners "
                        "WHERE race_id='20260906ST01' AND horse_no=13"
                    )
                ).scalar()
            eng.dispose()
            self.assertEqual(after, "同有運")


if __name__ == "__main__":
    unittest.main()
