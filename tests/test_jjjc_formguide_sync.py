"""jjjc_formguide_sync：空／低覆蓋 export 自動上游 fetch。"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch


class TestFormguideAutoFetch(unittest.TestCase):
    def test_export_needs_refresh_on_empty(self):
        import jjjc_formguide_sync as sync

        self.assertTrue(sync.export_needs_formguide_refresh({"status": "empty", "races": []}))
        full = {
            "status": "obtained",
            "races": [{"runners": [{"form_text": "穩步前進"}, {"form_text": "追前"}]}],
        }
        self.assertFalse(sync.export_needs_formguide_refresh(full))

    def test_sync_meeting_auto_fetch_when_empty(self):
        import jjjc_formguide_sync as sync
        import etl_pipeline

        empty = {
            "schema": "jjjc.formguide.v1",
            "race_date": "2026-11-29",
            "venue_code": "ST",
            "status": "empty",
            "races": [],
        }
        filled = {
            "schema": "jjjc.formguide.v1",
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
                            "form_text": "近績穩定",
                        }
                    ],
                }
            ],
        }
        export_n = {"n": 0}
        fetch_n = {"n": 0}

        def _fake_export(**kwargs):
            export_n["n"] += 1
            return empty if export_n["n"] == 1 else filled

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
                sync, "trigger_formguide_fetch", side_effect=_fake_fetch
            ):
                out = sync.sync_meeting("2026-11-29", "ST")

            self.assertTrue(out.get("ok"), out)
            self.assertTrue(out.get("auto_fetched"), out)
            self.assertEqual(fetch_n["n"], 1)
            self.assertGreaterEqual(int(out.get("runners_with_text") or 0), 1)


if __name__ == "__main__":
    unittest.main()
