"""作戰室「選擇賽日」清單：未齊備歷史 + 再往前 2 個 + 預設下次賽日。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from meeting_pipeline import (
    MeetingPipeline,
    default_ops_selector_index,
    select_ops_fixture_frame,
)


def _fx(rows):
    return pd.DataFrame(
        [
            {
                "racing_date": d,
                "course": c,
                "day_of_week": "星期三",
                "session": "night",
            }
            for d, c in rows
        ]
    )


class SelectOpsFixtureFrameTest(unittest.TestCase):
    def test_includes_incomplete_past_plus_two_earlier_and_upcoming(self):
        today = date(2026, 11, 2)
        fx = _fx(
            [
                ("2026-10-15", "ST"),
                ("2026-10-19", "HV"),
                ("2026-10-22", "ST"),
                ("2026-10-25", "HV"),
                ("2026-10-28", "ST"),
                ("2026-11-01", "HV"),
                ("2026-11-04", "HV"),
                ("2026-11-08", "ST"),
            ]
        )
        # 10-25 未齊備；最近歷史 10-28／11-01 也應出現；再往前補 10-19／10-22
        out = select_ops_fixture_frame(
            fx,
            incomplete_keys={("2026-10-25", "HV")},
            today=today,
            extra_earlier=2,
        )
        keys = [
            (str(r.racing_date)[:10], str(r.course))
            for r in out.itertuples(index=False)
        ]
        self.assertEqual(
            keys,
            [
                ("2026-10-19", "HV"),
                ("2026-10-22", "ST"),
                ("2026-10-25", "HV"),
                ("2026-10-28", "ST"),
                ("2026-11-01", "HV"),
                ("2026-11-04", "HV"),
                ("2026-11-08", "ST"),
            ],
        )
        self.assertNotIn(("2026-10-15", "ST"), keys)
        self.assertEqual(
            default_ops_selector_index(out, today=today),
            keys.index(("2026-11-04", "HV")),
        )

    def test_no_incomplete_still_shows_two_most_recent_past(self):
        today = date(2026, 11, 2)
        fx = _fx(
            [
                ("2026-10-22", "ST"),
                ("2026-10-25", "HV"),
                ("2026-10-28", "ST"),
                ("2026-11-01", "HV"),
                ("2026-11-04", "HV"),
            ]
        )
        out = select_ops_fixture_frame(
            fx,
            incomplete_keys=set(),
            today=today,
            extra_earlier=2,
        )
        keys = [
            (str(r.racing_date)[:10], str(r.course))
            for r in out.itertuples(index=False)
        ]
        self.assertEqual(
            keys,
            [
                ("2026-10-28", "ST"),
                ("2026-11-01", "HV"),
                ("2026-11-04", "HV"),
            ],
        )
        self.assertEqual(default_ops_selector_index(out, today=today), 2)

    def test_older_incomplete_kept_even_beyond_recent_two(self):
        today = date(2026, 11, 2)
        fx = _fx(
            [
                ("2026-09-10", "ST"),
                ("2026-10-01", "HV"),
                ("2026-10-28", "ST"),
                ("2026-11-01", "HV"),
                ("2026-11-04", "HV"),
            ]
        )
        out = select_ops_fixture_frame(
            fx,
            incomplete_keys={("2026-09-10", "ST")},
            today=today,
            extra_earlier=2,
        )
        keys = [
            (str(r.racing_date)[:10], str(r.course))
            for r in out.itertuples(index=False)
        ]
        # 未齊備 09-10 保留；其前無更早；最近 2 個歷史 + 未來
        self.assertEqual(
            keys,
            [
                ("2026-09-10", "ST"),
                ("2026-10-28", "ST"),
                ("2026-11-01", "HV"),
                ("2026-11-04", "HV"),
            ],
        )
        self.assertNotIn(("2026-10-01", "HV"), keys)


class ListFixturesForOpsSelectorTest(unittest.TestCase):
    def _pipe(self, db_path: str) -> MeetingPipeline:
        eng = create_engine(f"sqlite:///{db_path}")
        pipe = MeetingPipeline.__new__(MeetingPipeline)
        pipe.engine = eng
        pipe.ensure_tables()
        return pipe

    def test_incomplete_past_detected_and_default_next_meeting(self):
        today = date(2026, 11, 2)
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "ops_sel.db")
            pipe = self._pipe(db)
            with pipe.engine.begin() as conn:
                for d, c in [
                    ("2026-10-22", "ST"),
                    ("2026-10-25", "HV"),
                    ("2026-10-28", "ST"),
                    ("2026-11-01", "HV"),
                    ("2026-11-04", "HV"),
                ]:
                    conn.execute(
                        text(
                            """
                            INSERT INTO fixtures
                              (racing_date, course, day_of_week, session)
                            VALUES (:d, :c, '星期三', 'night')
                            """
                        ),
                        {"d": d, "c": c},
                    )
                # 10-22／10-28／11-01 齊備；10-25 RESULTS pending → 未齊備
                for d, c, results_st, settled_st in [
                    ("2026-10-22", "ST", "ok", "ok"),
                    ("2026-10-25", "HV", "pending", "pending"),
                    ("2026-10-28", "ST", "ok", "ok"),
                    ("2026-11-01", "HV", "ok", "skipped_manual"),
                ]:
                    for stage, st in (
                        ("RESULTS", results_st),
                        ("SETTLED", settled_st),
                    ):
                        conn.execute(
                            text(
                                """
                                INSERT INTO meeting_pipeline
                                  (racing_date, course, stage, status)
                                VALUES (:d, :c, :stage, :st)
                                """
                            ),
                            {"d": d, "c": c, "stage": stage, "st": st},
                        )

            incomplete = pipe.list_incomplete_past_fixture_keys(as_of=today)
            self.assertEqual(incomplete, {("2026-10-25", "HV")})

            fx, idx = pipe.list_fixtures_for_ops_selector(
                include_full_season=False, extra_earlier=2, as_of=today
            )
            keys = [
                (str(r["racing_date"])[:10], str(r["course"]))
                for _, r in fx.iterrows()
            ]
            self.assertIn(("2026-10-25", "HV"), keys)
            self.assertIn(("2026-10-22", "ST"), keys)  # 未齊備日前再往前
            self.assertIn(("2026-10-28", "ST"), keys)  # 最近歷史
            self.assertIn(("2026-11-01", "HV"), keys)
            self.assertIn(("2026-11-04", "HV"), keys)
            self.assertEqual(keys[idx], ("2026-11-04", "HV"))


if __name__ == "__main__":
    unittest.main()
