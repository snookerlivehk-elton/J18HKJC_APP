"""Tests for data_backlog enroll / coverage / process."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine, text


class DataBacklogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = create_engine(f"sqlite:///{self._tmp.name}")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE runners (
                        runner_id TEXT PRIMARY KEY,
                        race_id TEXT,
                        horse_no INTEGER,
                        finish_order_num INTEGER,
                        raw_json TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE text_reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        entity_type TEXT,
                        entity_id TEXT,
                        report_type TEXT,
                        report_text TEXT,
                        nlp_result TEXT
                    )
                    """
                )
            )
        from data_backlog import DataBacklogService

        self.svc = DataBacklogService(engine=self.engine)

    def _seed_runners(self, n=10, date_s="20260906", course="ST", *, jjjc=True, race_no=1):
        with self.engine.begin() as conn:
            for i in range(1, n + 1):
                rid = f"{date_s}{course}{int(race_no):02d}"
                runner_id = f"{rid}_{i}"
                raw = (
                    json.dumps(
                        {"synced_via": "jjjc_results_sync", "source": "official_hkjc"}
                    )
                    if jjjc
                    else json.dumps({"source": "j18_history"})
                )
                conn.execute(
                    text(
                        "INSERT INTO runners (runner_id, race_id, horse_no, finish_order_num, raw_json) "
                        "VALUES (:id, :race, :hn, :fo, :raw)"
                    ),
                    {"id": runner_id, "race": rid, "hn": i, "fo": i, "raw": raw},
                )

    def test_coverage_ignores_phantom_races_when_jjjc_present(self):
        """8 場 jjjc + 2 場幽靈（舊爬蟲）→ 分母應為 8×14=112，不是 140。"""
        for rn in range(1, 9):
            self._seed_runners(14, date_s="20260909", course="HV", race_no=rn, jjjc=True)
        for rn in range(9, 11):
            self._seed_runners(14, date_s="20260909", course="HV", race_no=rn, jjjc=False)
        cov = self.svc.measure_comment_coverage(
            "2026-09-09", "HV", "incident_report"
        )
        self.assertEqual(cov["race_n"], 8)
        self.assertEqual(cov["expected_n"], 112)
        self.assertEqual(cov["canonical_races"], 8)

    def _seed_comments(self, horse_nos, date_s="20260906", course="ST"):
        rid = f"{date_s}{course}01"
        with self.engine.begin() as conn:
            for hn in horse_nos:
                conn.execute(
                    text(
                        "INSERT INTO text_reports "
                        "(entity_type, entity_id, report_type, report_text) "
                        "VALUES ('runner', :eid, 'running_comment', :txt)"
                    ),
                    {"eid": f"{rid}_{hn}", "txt": f"沿途走勢 {hn}"},
                )

    def test_coverage_and_enroll_open(self):
        self._seed_runners(10)
        self._seed_comments([1, 2, 3])  # 30%
        cov = self.svc.measure_comment_coverage("2026-09-06", "ST", "running_comment")
        self.assertEqual(cov["expected_n"], 10)
        self.assertEqual(cov["covered_n"], 3)
        self.assertFalse(self.svc.coverage_ok(cov))

        actions = self.svc.enroll_meeting(
            "2026-09-06", "ST", as_of=date(2026, 9, 8), retention_days=14
        )
        kinds = {a["data_kind"]: a for a in actions}
        self.assertEqual(kinds["running_comment"]["action"], "enrolled")
        item = self.svc.get_item("2026-09-06", "ST", "running_comment")
        self.assertIsNotNone(item)
        self.assertIn(item["status"], ("open", "retrying"))

    def test_enroll_done_when_coverage_ok(self):
        self._seed_runners(10)
        self._seed_comments(list(range(1, 9)))  # 80%
        actions = self.svc.enroll_meeting(
            "2026-09-06", "ST", as_of=date(2026, 9, 8), kinds=["running_comment"]
        )
        self.assertEqual(actions[0]["action"], "done")
        item = self.svc.get_item("2026-09-06", "ST", "running_comment")
        self.assertEqual(item["status"], "done")

    def test_expire_beyond_retention(self):
        self._seed_runners(5)
        actions = self.svc.enroll_meeting(
            "2026-09-06",
            "ST",
            as_of=date(2026, 9, 25),
            retention_days=14,
            kinds=["running_comment"],
        )
        self.assertEqual(actions[0]["action"], "expired")

    def test_process_item_marks_done(self):
        self._seed_runners(5)
        self.svc.enroll_meeting(
            "2026-09-06", "ST", as_of=date(2026, 9, 8), kinds=["running_comment"]
        )
        item = self.svc.get_item("2026-09-06", "ST", "running_comment")
        self.assertEqual(item["status"], "open")

        def fake_sync(d, c, report_type=None, **kwargs):
            self._seed_comments([1, 2, 3, 4, 5])
            return {"ok": True, "waiting": False, "runner_upserted": 5}

        with patch("jjjc_text_reports_sync.sync_meeting", side_effect=fake_sync):
            out = self.svc.process_item(
                item, as_of=date(2026, 9, 8), retention_days=14
            )
        self.assertEqual(out["action"], "done")
        item2 = self.svc.get_item("2026-09-06", "ST", "running_comment")
        self.assertEqual(item2["status"], "done")

    def test_backoff_seconds(self):
        from data_backlog import backoff_seconds

        self.assertEqual(backoff_seconds(1, 0.5), 6 * 3600)
        self.assertEqual(backoff_seconds(2, 3), 24 * 3600)
        self.assertEqual(backoff_seconds(5, 10), 72 * 3600)

    def test_skip_and_reopen(self):
        self._seed_runners(5)
        self.svc.enroll_meeting(
            "2026-09-06", "ST", as_of=date(2026, 9, 8), kinds=["running_comment"]
        )
        self.svc.mark_skipped("2026-09-06", "ST", "running_comment")
        self.assertEqual(
            self.svc.get_item("2026-09-06", "ST", "running_comment")["status"],
            "skipped_manual",
        )
        self.svc.reopen("2026-09-06", "ST", "running_comment")
        self.assertEqual(
            self.svc.get_item("2026-09-06", "ST", "running_comment")["status"],
            "open",
        )


if __name__ == "__main__":
    unittest.main()
