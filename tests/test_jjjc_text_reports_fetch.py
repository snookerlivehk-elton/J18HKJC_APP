"""text-reports sync：export 缺沿途時自動 POST /api/text-reports/fetch。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import jjjc_text_reports_sync as sync


class TextReportsAutoFetchTest(unittest.TestCase):
    def test_needs_fetch_when_only_incident(self):
        payload = {
            "status": "obtained",
            "reports": [{"report_type": "incident_report", "runners": []}],
        }
        self.assertTrue(sync._needs_upstream_fetch(payload, want=None))
        self.assertTrue(
            sync._needs_upstream_fetch(payload, want="running_comment")
        )
        self.assertFalse(
            sync._needs_upstream_fetch(payload, want="incident_report")
        )

    def test_needs_fetch_when_empty(self):
        self.assertTrue(
            sync._needs_upstream_fetch({"status": "empty", "reports": []}, None)
        )

    def test_sync_meeting_auto_fetch_then_upsert(self):
        empty = {"schema": "jjjc.text_reports.v1", "status": "empty", "reports": []}
        filled = {
            "schema": "jjjc.text_reports.v1",
            "status": "obtained",
            "reports": [
                {
                    "report_type": "running_comment",
                    "race_id": "20261028ST01",
                    "runners": [
                        {
                            "horse_no": 1,
                            "text": "沿途走勢測試",
                            "is_placeholder": False,
                        }
                    ],
                },
                {
                    "report_type": "incident_report",
                    "race_id": "20261028ST01",
                    "runners": [
                        {
                            "horse_no": 1,
                            "text": "競賽報告測試",
                            "is_placeholder": False,
                        }
                    ],
                },
            ],
        }
        calls = {"n": 0}

        def _fake_export(**kwargs):
            calls["n"] += 1
            return empty if calls["n"] == 1 else filled

        with patch.object(sync, "fetch_export", side_effect=_fake_export), patch.object(
            sync,
            "trigger_text_reports_fetch",
            return_value={
                "ok": True,
                "corunning_races": 9,
                "incident_races": 9,
                "report_count": 18,
            },
        ) as fetch, patch.object(
            sync,
            "upsert_payload",
            return_value={
                "ok": True,
                "waiting": False,
                "runner_upserted": 2,
                "report_count": 2,
            },
        ) as upsert:
            out = sync.sync_meeting("2026-10-28", "ST", auto_fetch=True)

        fetch.assert_called_once()
        upsert.assert_called_once()
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("auto_fetched"))
        self.assertEqual(out.get("runner_upserted"), 2)
        self.assertGreaterEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
