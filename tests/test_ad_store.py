"""ad_store dual-write / read roundtrip (sqlite)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class AdStoreRoundtripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "data" / "t.db"
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.env = mock.patch.dict(
            os.environ,
            {
                "USE_SQLITE": "true",
                "AD_STORE_ENABLED": "true",
                "SQLITE_DB_PATH": str(self.db),
                "DATABASE_URL": "",
                "DATABASE_URL_SYNC": "",
            },
            clear=False,
        )
        self.env.start()

        import ad_store

        self.ad_store = ad_store
        self._old_engine = ad_store._ENGINE
        self._old_ensured = ad_store._ENSURED
        self._old_use = ad_store.USE_SQLITE
        self._old_path = ad_store.SQLITE_DB_PATH
        ad_store._ENGINE = None
        ad_store._ENSURED = False
        ad_store.USE_SQLITE = True
        ad_store.SQLITE_DB_PATH = str(self.db)

    def tearDown(self):
        self.ad_store._ENGINE = self._old_engine
        self.ad_store._ENSURED = self._old_ensured
        self.ad_store.USE_SQLITE = self._old_use
        self.ad_store.SQLITE_DB_PATH = self._old_path
        if self.ad_store._ENGINE is not None:
            try:
                self.ad_store._ENGINE.dispose()
            except Exception:
                pass
        self.env.stop()
        self.tmp.cleanup()

    def test_upsert_and_load_package_with_poster(self):
        ad_store = self.ad_store
        pkg = {
            "id": "2026-09-13-st-day",
            "status": "pending_ai",
            "meeting": {
                "date": "2026-09-13",
                "venue_code": "ST",
                "venue": "沙田",
                "session": "日",
            },
            "meta": {"batch_id": "20260913ST_test", "has_poster": True},
            "assets": {"poster_url": "/v1/ads/2026-09-13-st-day/poster"},
            "copy": {"facebook": "hello"},
        }
        poster = b"\x89PNG\r\n\x1a\n" + b"abc123"
        out = ad_store.upsert_ad_package(pkg, poster_png=poster)
        self.assertTrue(out.get("ok"), out)
        loaded = ad_store.load_ad_package_db("2026-09-13-st-day")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["id"], "2026-09-13-st-day")
        self.assertEqual(loaded["status"], "pending_ai")
        blob = ad_store.get_poster_bytes_db("2026-09-13-st-day")
        self.assertEqual(blob, poster)
        ids = ad_store.list_ad_package_ids_db()
        self.assertIn("2026-09-13-st-day", ids)

    def test_archive_and_job_done(self):
        ad_store = self.ad_store
        payload = {"meeting": {"batch_id": "B1"}, "text": "x"}
        r = ad_store.upsert_archive(
            "2026-09-13", "ST", "social", payload, batch_id="B1"
        )
        self.assertTrue(r.get("ok"), r)
        got = ad_store.load_archive_latest_db("2026-09-13", "ST", "social")
        self.assertEqual(got.get("text"), "x")
        self.assertTrue(
            ad_store.job_done_for_batch_db("2026-09-13", "ST", "social", "B1")
        )
        self.assertFalse(
            ad_store.job_done_for_batch_db("2026-09-13", "ST", "social", "B2")
        )

    def test_social_json_and_hydrate(self):
        ad_store = self.ad_store
        pkg = {
            "id": "2026-09-13-st-day",
            "status": "ready",
            "meeting": {
                "date": "2026-09-13",
                "venue_code": "ST",
                "venue": "沙田",
                "session": "日",
            },
            "copy": {
                "facebook": "post",
                "ai": {
                    "title": "今晚邊場？",
                    "post_text": "今晚邊場？\nj18.hk\n",
                    "featured": [{"race_no": 1, "horse_name": "快馬"}],
                },
            },
            "assets": {"poster_url": "https://ads.example.com/v1/ads/2026-09-13-st-day/poster"},
        }
        social = {
            "title": "今晚邊場？",
            "post_text": "今晚邊場？\nj18.hk\n",
            "featured": [{"race_no": 1, "horse_name": "快馬"}],
        }
        poster = b"\x89PNG\r\n\x1a\n" + b"xyz"
        out = ad_store.upsert_ad_package(pkg, poster_png=poster, social_json=social)
        self.assertTrue(out.get("ok"), out)
        got = ad_store.get_social_json_db("2026-09-13-st-day")
        self.assertEqual(got.get("title"), "今晚邊場？")
        disk = Path(self.tmp.name) / "ad_out"
        hyd = ad_store.hydrate_package_to_disk("2026-09-13-st-day", disk)
        self.assertTrue(hyd.get("ok"), hyd)
        self.assertTrue(hyd.get("has_social"))
        self.assertTrue((disk / "social_copy.json").is_file())
        self.assertTrue((disk / "packages" / "2026-09-13-st-day.png").is_file())


if __name__ == "__main__":
    unittest.main()
