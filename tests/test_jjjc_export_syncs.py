"""Smoke tests: jjjc export fixtures → SQLite upcoming_* / text_reports."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class JjjcSpeedguideSyncTest(unittest.TestCase):
    def test_upsert_fixture(self):
        fixture = ROOT / "fixtures" / "jjjc_speedguide_HV_20260909_R1.json"
        self.assertTrue(fixture.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_speedguide_sync as sync

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            out = sync.upsert_payload(payload)
            self.assertTrue(out["ok"])
            self.assertFalse(out.get("waiting"))
            self.assertEqual(out["runner_upserted"], 2)

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            try:
                with eng.connect() as conn:
                    row = conn.execute(
                        text(
                            "SELECT form_rating, speed_energy, speed_energy_delta "
                            "FROM upcoming_speedguide WHERE runner_id='20260909HV01_1'"
                        )
                    ).mappings().first()
            finally:
                eng.dispose()

            self.assertEqual(row["form_rating"], "A")
            self.assertEqual(float(row["speed_energy"]), 88.0)
            self.assertEqual(float(row["speed_energy_delta"]), -2.0)

    def test_empty_races_waiting(self):
        import jjjc_speedguide_sync as sync

        out = sync.upsert_payload(
            {
                "schema": "jjjc.speedguide.v1",
                "status": "empty",
                "races": [],
                "content_updated_at": "2026-09-01T00:00:00.000Z",
            }
        )
        self.assertTrue(out["ok"])
        self.assertTrue(out["waiting"])

    def test_placeholder_shells_waiting(self):
        """JJJC 回傳有 runners 但 energy 全 null／placeholder → waiting。"""
        import jjjc_speedguide_sync as sync

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            out = sync.upsert_payload(
                {
                    "schema": "jjjc.speedguide.v1",
                    "status": "suspicious",
                    "races": [
                        {
                            "race_id": "20260913ST01",
                            "runners": [
                                {
                                    "horse_no": 1,
                                    "horse_name": "甲",
                                    "energy": None,
                                    "energy_delta": None,
                                    "energy_required": 90,
                                    "energy_is_placeholder": True,
                                },
                                {
                                    "horse_no": 2,
                                    "horse_name": "乙",
                                    "energy": 88,
                                    "energy_is_placeholder": True,
                                },
                            ],
                        }
                    ],
                }
            )
            self.assertTrue(out["ok"])
            self.assertTrue(out["waiting"])
            self.assertEqual(out["runners_with_energy"], 0)
            self.assertEqual(out["runners_placeholder"], 2)


class JjjcFormguideSyncTest(unittest.TestCase):
    def test_upsert_fixture(self):
        fixture = ROOT / "fixtures" / "jjjc_formguide_HV_20260909_R1.json"
        self.assertTrue(fixture.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_formguide_sync as sync

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            out = sync.upsert_payload(payload)
            self.assertTrue(out["ok"])
            self.assertEqual(out["runners_with_text"], 2)

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            try:
                with eng.connect() as conn:
                    row = conn.execute(
                        text(
                            "SELECT form_text FROM upcoming_formguide "
                            "WHERE runner_id='20260909HV01_1'"
                        )
                    ).mappings().first()
            finally:
                eng.dispose()

            self.assertIn("中等步速", row["form_text"])


class JjjcTextReportsSyncTest(unittest.TestCase):
    def test_upsert_skips_placeholder_and_idempotent(self):
        fixture = ROOT / "fixtures" / "jjjc_text_reports_ST_20260906_R1.json"
        self.assertTrue(fixture.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_text_reports_sync as sync

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            payload = json.loads(fixture.read_text(encoding="utf-8"))
            out1 = sync.upsert_payload(payload)
            self.assertTrue(out1["ok"])
            self.assertEqual(out1["runner_upserted"], 2)  # horse 13 RC + IR；placeholder 略過
            self.assertGreaterEqual(out1["skipped_placeholder_or_empty"], 1)

            out2 = sync.upsert_payload(payload)
            self.assertTrue(out2["ok"])
            self.assertEqual(out2["runner_upserted"], 0)
            self.assertEqual(out2["skipped_unchanged"], 2)

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            try:
                with eng.connect() as conn:
                    n = conn.execute(text("SELECT COUNT(*) FROM text_reports")).scalar()
                    types = {
                        r[0]
                        for r in conn.execute(
                            text("SELECT DISTINCT report_type FROM text_reports")
                        )
                    }
                    eid = conn.execute(
                        text(
                            "SELECT entity_id FROM text_reports "
                            "WHERE report_type='running_comment' LIMIT 1"
                        )
                    ).scalar()
            finally:
                eng.dispose()

            self.assertEqual(n, 2)
            self.assertEqual(types, {"running_comment", "incident_report"})
            self.assertEqual(eid, "20260906ST01_13")

    def test_unavailable_failed(self):
        import jjjc_text_reports_sync as sync

        out = sync.sync_meeting(
            racing_date="2026-09-06",
            course="ST",
            from_file=None,
            base_url=None,
        )
        # no base / no file → failed from ValueError path when fetch attempted
        # call upsert path via unavailable status using sync after mocking file:
        # use load via temporary
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "schema": "jjjc.text_reports.v1",
                    "status": "unavailable",
                    "reports": [],
                },
                f,
            )
            path = f.name
        try:
            out = sync.sync_meeting("2026-09-06", "ST", from_file=path)
        finally:
            os.unlink(path)
        self.assertFalse(out["ok"])
        self.assertEqual(out["phase"], "failed")

    def test_normalize_jjjc_internal_aliases(self):
        import jjjc_text_reports_sync as sync

        self.assertEqual(sync.normalize_report_type("corunning"), "running_comment")
        self.assertEqual(sync.normalize_report_type("racereport"), "incident_report")
        self.assertEqual(sync.normalize_report_type("race_report"), "incident_report")
        self.assertEqual(sync.normalize_report_type("running_comment"), "running_comment")
        self.assertIsNone(sync.normalize_report_type("unknown_xyz"))

    def test_upsert_accepts_racereport_corunning_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "alias.db")
            os.environ["USE_SQLITE"] = "true"

            import etl_pipeline
            import jjjc_text_reports_sync as sync

            etl_pipeline.USE_SQLITE = True
            etl_pipeline.SQLITE_DB_PATH = db_path
            sync.USE_SQLITE = True
            sync.SQLITE_DB_PATH = db_path
            sync.DATABASE_URL_SYNC = f"sqlite:///{db_path}"

            payload = {
                "schema": "jjjc.text_reports.v1",
                "status": "obtained",
                "content_updated_at": "2026-09-06T12:00:00Z",
                "reports": [
                    {
                        "report_type": "corunning",
                        "race_id": "20260906ST01",
                        "runners": [
                            {
                                "horse_no": 1,
                                "text": "沿欄上前",
                                "is_placeholder": False,
                            }
                        ],
                    },
                    {
                        "report_type": "racereport",
                        "race_id": "20260906ST01",
                        "runners": [
                            {
                                "horse_no": 1,
                                "text": "直路受阻",
                                "is_placeholder": False,
                            }
                        ],
                    },
                ],
            }
            out = sync.upsert_payload(payload)
            self.assertTrue(out["ok"])
            self.assertEqual(out["runner_upserted"], 2)

            from sqlalchemy import create_engine, text

            eng = create_engine(f"sqlite:///{db_path}")
            try:
                with eng.connect() as conn:
                    types = {
                        r[0]
                        for r in conn.execute(
                            text("SELECT DISTINCT report_type FROM text_reports")
                        )
                    }
            finally:
                eng.dispose()
            self.assertEqual(types, {"running_comment", "incident_report"})


class CrawlSpeedguideCmsFallbackTest(unittest.TestCase):
    def test_waiting_shells_trigger_cms_by_default(self):
        from unittest.mock import MagicMock, patch

        import meeting_pipeline as mp

        pipe = mp.MeetingPipeline.__new__(mp.MeetingPipeline)
        pipe.refresh_readiness = MagicMock()
        os.environ.pop("MEETING_TICK_SG_CMS_ON_WAITING", None)

        jjjc_waiting = {
            "ok": True,
            "waiting": True,
            "phase": "waiting",
            "runner_upserted": 139,
            "runners_with_energy": 0,
            "detail": "export 空殼",
        }
        cms = MagicMock(
            returncode=0, stdout="cms ok", stderr="",
        )
        with patch("jjjc_speedguide_sync.sync_meeting", return_value=jjjc_waiting), patch(
            "subprocess.run", return_value=cms
        ) as run:
            out = mp.MeetingPipeline.run_action(
                pipe, "2026-09-13", "ST", "crawl_speedguide"
            )
        self.assertEqual(out.get("source"), "hkjc_cms_fallback")
        self.assertTrue(out.get("ok"))
        self.assertTrue(run.called)
        self.assertIn("speedguide_crawler.py", run.call_args[0][0])

    def test_cms_on_waiting_can_be_disabled(self):
        from unittest.mock import MagicMock, patch

        import meeting_pipeline as mp

        pipe = mp.MeetingPipeline.__new__(mp.MeetingPipeline)
        pipe.refresh_readiness = MagicMock()
        os.environ["MEETING_TICK_SG_CMS_ON_WAITING"] = "false"
        self.addCleanup(lambda: os.environ.pop("MEETING_TICK_SG_CMS_ON_WAITING", None))

        jjjc_waiting = {
            "ok": True,
            "waiting": True,
            "runner_upserted": 10,
            "runners_with_energy": 0,
        }
        with patch("jjjc_speedguide_sync.sync_meeting", return_value=jjjc_waiting), patch(
            "subprocess.run"
        ) as run:
            out = mp.MeetingPipeline.run_action(
                pipe, "2026-09-13", "ST", "crawl_speedguide"
            )
        self.assertEqual(out.get("fallback_skipped"), "waiting")
        self.assertEqual(out.get("source"), "jjjc")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
