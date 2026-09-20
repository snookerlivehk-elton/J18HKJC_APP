"""EN→ZH name aliases + remediator."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class NameAliasRemediatorTest(unittest.TestCase):
    def test_alias_key_and_resolve(self):
        from name_aliases import alias_key, resolve_via_alias

        self.assertEqual(alias_key("B Avdulla"), "B AVDULLA")
        maps = {"jockey": {"B AVDULLA": "艾道拿"}, "horse": {}, "trainer": {}}
        self.assertEqual(resolve_via_alias("jockey", "B Avdulla", maps), "艾道拿")
        self.assertEqual(resolve_via_alias("jockey", "艾道拿", maps), "艾道拿")

    def test_harvest_racecard_and_remediate_runners(self):
        root = Path(__file__).resolve().parents[1]
        card = root / "fixtures" / "jjjc_racecard_HV_20260909_R1.json"
        self.assertTrue(card.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "t.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_racecard_sync as rcard
            import name_remediator as rem
            from name_aliases import load_alias_maps
            from sqlalchemy import create_engine, text

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            rcard.USE_SQLITE = True
            rcard.SQLITE_DB_PATH = db_path
            rcard.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
            rem.USE_SQLITE = True
            rem.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            out = rcard.upsert_payload(json.loads(card.read_text(encoding="utf-8")))
            self.assertTrue(out.get("ok") or out.get("runner_upserted", 0) >= 1)

            eng = create_engine(f"sqlite:///{db_path}")
            with eng.begin() as conn:
                # 模擬賽果寫入英文
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS runners (
                          runner_id TEXT PRIMARY KEY,
                          race_id TEXT,
                          horse_no INTEGER,
                          brand_num TEXT,
                          horse_name TEXT,
                          jockey_name TEXT,
                          trainer_name TEXT
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO runners
                          (runner_id, race_id, horse_no, brand_num,
                           horse_name, jockey_name, trainer_name)
                        VALUES
                          ('20260909HV011', '20260909HV01', 1, 'K431',
                           'FLASH STAR', 'H Bowman', 'C S Shum')
                        """
                    )
                )
                maps = load_alias_maps(conn)
                self.assertIn("H BOWMAN", maps["jockey"])
                self.assertEqual(maps["jockey"]["H BOWMAN"], "布文")
                self.assertEqual(maps["horse"].get("FLASH STAR"), "閃電星福")

            result = rem.remediate_meeting(
                "2026-09-09", "HV", also_factors=False, engine=eng
            )
            self.assertTrue(result["ok"])
            self.assertGreaterEqual(result["runners"]["runners_updated"], 1)

            with eng.connect() as conn:
                row = (
                    conn.execute(
                        text(
                            "SELECT horse_name, jockey_name, trainer_name "
                            "FROM runners WHERE runner_id='20260909HV011'"
                        )
                    )
                    .mappings()
                    .first()
                )
            eng.dispose()
            self.assertEqual(row["horse_name"], "閃電星福")
            self.assertEqual(row["jockey_name"], "布文")
            self.assertEqual(row["trainer_name"], "沈集成")


if __name__ == "__main__":
    unittest.main()
