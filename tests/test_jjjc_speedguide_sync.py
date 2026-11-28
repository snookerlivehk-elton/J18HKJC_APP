"""jjjc_speedguide_sync：partial／空 export 自動上游 fetch。"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch


class TestSpeedguideAutoFetch(unittest.TestCase):
    def test_export_needs_refresh_on_partial_and_low_coverage(self):
        import jjjc_speedguide_sync as sync

        self.assertTrue(
            sync.export_needs_speedguide_refresh({"status": "partial", "races": []})
        )
        thin = {
            "status": "obtained",
            "races": [
                {
                    "runners": [
                        {"energy": 90, "energy_is_placeholder": False},
                        {"energy": None, "energy_is_placeholder": False},
                        {"energy": None, "energy_is_placeholder": False},
                        {"energy": None, "energy_is_placeholder": False},
                        {"energy": None, "energy_is_placeholder": False},
                    ]
                }
            ],
        }
        self.assertTrue(sync.export_needs_speedguide_refresh(thin))
        full = {
            "status": "obtained",
            "races": [
                {
                    "runners": [
                        {"energy": 90, "energy_is_placeholder": False},
                        {"energy": 88, "energy_is_placeholder": False},
                    ]
                }
            ],
        }
        self.assertFalse(sync.export_needs_speedguide_refresh(full))

    def test_sync_meeting_auto_fetch_when_partial(self):
        import jjjc_speedguide_sync as sync
        import etl_pipeline

        partial = {
            "schema": "jjjc.speedguide.v1",
            "race_date": "2026-11-29",
            "venue_code": "ST",
            "status": "partial",
            "races": [
                {
                    "race_id": "20261129ST01",
                    "runners": [
                        {
                            "horse_no": 1,
                            "horse_name": "測試",
                            "energy": None,
                            "energy_is_placeholder": True,
                        }
                    ],
                }
            ],
        }
        filled = {
            "schema": "jjjc.speedguide.v1",
            "race_date": "2026-11-29",
            "venue_code": "ST",
            "status": "obtained",
            "races": [
                {
                    "race_id": "20261129ST01",
                    "runners": [
                        {
                            "horse_no": 1,
                            "horse_name": "測試",
                            "energy": 91,
                            "energy_delta": 0,
                            "energy_is_placeholder": False,
                            "fitness_rating": "2",
                        }
                    ],
                }
            ],
        }
        export_n = {"n": 0}
        fetch_n = {"n": 0}

        def _fake_export(**kwargs):
            export_n["n"] += 1
            return partial if export_n["n"] == 1 else filled

        def _fake_fetch(race_date, venue, **kwargs):
            fetch_n["n"] += 1
            return {"ok": True, "race_count": 1, "runner_count": 1, "status": "obtained"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            os.environ["USE_SQLITE"] = "true"
            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            with patch.object(sync, "fetch_export", side_effect=_fake_export), patch.object(
                sync, "trigger_speedguide_fetch", side_effect=_fake_fetch
            ):
                out = sync.sync_meeting("2026-11-29", "ST")

            self.assertTrue(out.get("ok"), out)
            self.assertTrue(out.get("auto_fetched"), out)
            self.assertEqual(fetch_n["n"], 1)
            self.assertGreaterEqual(export_n["n"], 2)
            self.assertGreaterEqual(int(out.get("runners_with_energy") or 0), 1)


if __name__ == "__main__":
    unittest.main()
