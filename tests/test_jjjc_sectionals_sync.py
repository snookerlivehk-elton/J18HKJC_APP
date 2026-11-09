"""jjjc sectionals sync + contract helpers."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class JjjcContractHelpersTest(unittest.TestCase):
    def test_venue_meeting_horse_no(self):
        from jjjc_export_common import (
            horse_no_of,
            make_race_id,
            meeting_id,
            normalize_venue,
        )

        self.assertEqual(normalize_venue("HV"), "HV")
        self.assertEqual(normalize_venue("沙田"), "ST")
        self.assertEqual(normalize_venue("Happy Valley"), "HV")
        self.assertIsNone(normalize_venue("TOKYO"))
        self.assertEqual(meeting_id("2026-09-16", "HV"), "2026-09-16_HV")
        self.assertEqual(make_race_id("2026-09-16", "HV", 1), "20260916HV01")
        self.assertEqual(horse_no_of({"runner_no": 7}), 7)
        self.assertEqual(horse_no_of({"horse_no": 3}), 3)


class JjjcSectionalsSyncTest(unittest.TestCase):
    def test_upsert_fixture_with_times(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "fixtures" / "jjjc_sectionals_HV_20260916_R1.json"
        self.assertTrue(fixture.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "sec.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_sectionals_sync as sync
            import sectionals_store as ss

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
            ss.USE_SQLITE = True
            ss.SQLITE_DB_PATH = db_path

            # 先建 runners（join race_id+horse_no）
            from sqlalchemy import create_engine, text

            etl_pipeline.J18ETLPipeline()
            eng = create_engine(f"sqlite:///{db_path}")
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO race_meetings (meeting_id, racing_date, race_count)
                        VALUES ('2026-09-16', '2026-09-16', 1)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO races (race_id, meeting_id, race_num, distance_m)
                        VALUES ('20260916HV01', '2026-09-16', 1, 1200)
                        """
                    )
                )
                for hn, code, name in (
                    (3, "H101", "DEMO ONE"),
                    (7, "H202", "DEMO TWO"),
                ):
                    conn.execute(
                        text(
                            """
                            INSERT INTO runners (
                              runner_id, race_id, horse_id, horse_no, brand_num,
                              horse_name, finish_order_num
                            ) VALUES (
                              :rid, '20260916HV01', :hid, :hn, :code, :name, :fo
                            )
                            """
                        ),
                        {
                            "rid": f"20260916HV01{code}",
                            "hid": f"HK_2026_{code}",
                            "hn": hn,
                            "code": code,
                            "name": name,
                            "fo": 1 if hn == 3 else 3,
                        },
                    )

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            out = sync.upsert_payload(payload)
            self.assertTrue(out["ok"], out)
            self.assertFalse(out.get("waiting"))
            self.assertGreaterEqual(out["runner_sections_upserted"], 6)
            self.assertGreaterEqual(out["race_sectionals_upserted"], 3)

            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT rs.stage_no, rs.position_raw, rs.sectional_time
                        FROM runner_sections rs
                        JOIN runners ru ON ru.runner_id = rs.runner_id
                        WHERE ru.horse_no = 3
                        ORDER BY rs.stage_no
                        """
                    )
                ).fetchall()
                race_t = conn.execute(
                    text(
                        "SELECT sectional_time FROM race_sectionals WHERE race_id='20260916HV01' ORDER BY stage_no"
                    )
                ).fetchall()
                margin = conn.execute(
                    text(
                        """
                        SELECT distance_behind_raw FROM runner_sections rs
                        JOIN runners ru ON ru.runner_id = rs.runner_id
                        WHERE ru.horse_no = 3 AND rs.stage_no = 1
                        """
                    )
                ).scalar()

            self.assertEqual(len(rows), 3)
            self.assertEqual(str(rows[0][1]), "2")
            self.assertEqual(str(rows[0][2]), "13.1")
            self.assertEqual(str(rows[2][1]), "1")
            self.assertEqual([str(r[0]) for r in race_t], ["12.8", "10.7", "11.6"])
            self.assertEqual(str(margin), "1")

            from data_audit import race_sectionals_grid

            grid = race_sectionals_grid(eng, "20260916HV01")
            self.assertEqual(len(grid), 2)
            one = grid[grid["馬號"] == 3].iloc[0]
            self.assertEqual(str(one["走位"]), "2-2-1")
            self.assertIn("13.1", str(one["分段時間串"]))
            self.assertIn("10.9", str(one["分段時間串"]))
            eng.dispose()

    def test_sync_meeting_auto_refresh_when_export_empty(self):
        """export empty 應觸發 phases/target + post/run，再 re-export 入庫。"""
        from unittest.mock import patch

        import jjjc_sectionals_sync as sync

        empty = {
            "schema": "jjjc.sectionals.v1",
            "race_date": "2026-10-25",
            "venue_code": "ST",
            "status": "empty",
            "race_count": 0,
            "runners_with_sectional_time": 0,
            "races": [],
        }
        filled = {
            "schema": "jjjc.sectionals.v1",
            "race_date": "2026-10-25",
            "venue_code": "ST",
            "status": "obtained",
            "race_count": 1,
            "runners_with_sectional_time": 1,
            "races": [
                {
                    "race_id": "20261025ST01",
                    "race_no": 1,
                    "race_date": "2026-10-25",
                    "venue_code": "ST",
                    "runners": [
                        {
                            "horse_no": 1,
                            "horse_code": "H001",
                            "sections": [
                                {
                                    "section_index": 1,
                                    "position": 1,
                                    "sectional_time": "12.5",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        export_calls = {"n": 0}
        refresh_calls = {"n": 0}

        def _fake_export(**kwargs):
            export_calls["n"] += 1
            return empty if export_calls["n"] == 1 else filled

        def _fake_refresh(race_date, venue, **kwargs):
            refresh_calls["n"] += 1
            return {
                "ok": True,
                "race_date": race_date,
                "venue_code": venue,
                "post_run": {"ok": True, "sectional_race_count": 1},
            }

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "sec_refresh.db")
            os.environ["USE_SQLITE"] = "true"
            import etl_pipeline
            import sectionals_store as ss

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"
            ss.USE_SQLITE = True
            ss.SQLITE_DB_PATH = db_path
            etl_pipeline.J18ETLPipeline()

            with patch.object(sync, "fetch_export", side_effect=_fake_export), patch.object(
                sync, "trigger_sectionals_upstream_refresh", side_effect=_fake_refresh
            ):
                out = sync.sync_meeting("2026-10-25", "ST")

            self.assertTrue(out.get("ok"), out)
            self.assertTrue(out.get("auto_refreshed"), out)
            self.assertEqual(refresh_calls["n"], 1)
            self.assertGreaterEqual(export_calls["n"], 2)
            self.assertGreaterEqual(int(out.get("runner_sections_upserted") or 0), 1)


if __name__ == "__main__":
    unittest.main()
