"""
賽日作戰管線：fixtures + 各階段狀態 + readiness 檢查 + 手動節點動作。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import create_engine, text

from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )

# 階段定義（順序）
STAGES = [
    ("FIXTURE", "賽期表"),
    ("RACECARD", "排位表"),
    ("SPEEDGUIDE", "速勢能量"),
    ("FORMGUIDE", "賽績指引"),
    ("FACTORS", "因子分數"),
    ("NLP", "賽後NLP(可選)"),
    ("FORM_AI", "Form AI評價"),
    ("SNAPSHOT", "預測快照"),
    ("RESULTS", "賽果入庫"),
    ("SETTLED", "快照結算"),
]

STATUS_PENDING = "pending"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_WAITING = "waiting"  # 官方尚未上架（如 SG）
STATUS_SKIPPED = "skipped_manual"


def _racecard_looks_corrupt(runners_df: pd.DataFrame):
    """偵測排位欄位錯位（不依賴 ui_utils，避免 Streamlit 循環 import）。"""
    if runners_df is None or runners_df.empty:
        return False, ""
    n = len(runners_df)
    draw_zero = 0
    if "draw" in runners_df.columns:
        draw_zero = int(
            (pd.to_numeric(runners_df["draw"], errors="coerce").fillna(0) == 0).sum()
        )
    trainer_numeric = 0
    if "trainer_name" in runners_df.columns:
        trainer_numeric = int(
            runners_df["trainer_name"].astype(str).str.fullmatch(r"\d+").fillna(False).sum()
        )
    if draw_zero >= max(n - 1, 1) and trainer_numeric >= max(n // 2, 1):
        return True, (
            f"排位疑似錯位（檔位 0：{draw_zero}/{n}，練馬師為數字：{trainer_numeric}/{n}）"
        )
    if trainer_numeric >= max(n // 2, 1):
        return True, f"練馬師多數為數字（{trainer_numeric}/{n}）"
    return False, ""


class MeetingPipeline:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL_SYNC)
        self.ensure_tables()

    def ensure_tables(self):
        if USE_SQLITE:
            ddl = [
                """
                CREATE TABLE IF NOT EXISTS fixtures (
                    racing_date TEXT NOT NULL,
                    course TEXT NOT NULL,
                    day_of_week TEXT,
                    is_day_meeting INTEGER,
                    session TEXT,
                    status TEXT DEFAULT 'PENDING',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (racing_date, course)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS meeting_pipeline (
                    racing_date TEXT NOT NULL,
                    course TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    detail TEXT,
                    manual_override INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (racing_date, course, stage)
                )
                """,
            ]
        else:
            ddl = [
                """
                CREATE TABLE IF NOT EXISTS fixtures (
                    racing_date DATE NOT NULL,
                    course VARCHAR(10) NOT NULL,
                    day_of_week VARCHAR(20),
                    is_day_meeting BOOLEAN,
                    session VARCHAR(20),
                    status VARCHAR(40) DEFAULT 'PENDING',
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (racing_date, course)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS meeting_pipeline (
                    racing_date DATE NOT NULL,
                    course VARCHAR(10) NOT NULL,
                    stage VARCHAR(40) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    detail TEXT,
                    manual_override BOOLEAN DEFAULT FALSE,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (racing_date, course, stage)
                )
                """,
            ]
        with self.engine.begin() as conn:
            for s in ddl:
                conn.execute(text(s))
            # 舊 fixtures 可能只有 racing_date PK — 盡力相容
            if not USE_SQLITE:
                try:
                    conn.execute(text("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS session VARCHAR(20)"))
                    conn.execute(text("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()"))
                except Exception:
                    pass

    def upsert_fixtures(self, rows: List[dict]) -> int:
        if not rows:
            return 0
        n = 0
        with self.engine.begin() as conn:
            for r in rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO fixtures (racing_date, course, day_of_week, is_day_meeting, session, status)
                        VALUES (:racing_date, :course, :day_of_week, :is_day_meeting, :session, 'PENDING')
                        ON CONFLICT (racing_date, course) DO UPDATE SET
                          day_of_week=EXCLUDED.day_of_week,
                          is_day_meeting=EXCLUDED.is_day_meeting,
                          session=EXCLUDED.session,
                          updated_at=CURRENT_TIMESTAMP
                        """
                        if not USE_SQLITE
                        else """
                        INSERT INTO fixtures (racing_date, course, day_of_week, is_day_meeting, session, status)
                        VALUES (:racing_date, :course, :day_of_week, :is_day_meeting, :session, 'PENDING')
                        ON CONFLICT (racing_date, course) DO UPDATE SET
                          day_of_week=excluded.day_of_week,
                          is_day_meeting=excluded.is_day_meeting,
                          session=excluded.session,
                          updated_at=CURRENT_TIMESTAMP
                        """
                    ),
                    {
                        "racing_date": r["racing_date"],
                        "course": r["course"],
                        "day_of_week": r.get("day_of_week"),
                        "is_day_meeting": r.get("is_day_meeting"),
                        "session": r.get("session"),
                    },
                )
                self._ensure_stages(conn, r["racing_date"], r["course"])
                n += 1
        return n

    def _ensure_stages(self, conn, racing_date: str, course: str):
        for stage, _label in STAGES:
            conn.execute(
                text(
                    """
                    INSERT INTO meeting_pipeline (racing_date, course, stage, status, detail)
                    VALUES (:d, :c, :s, 'pending', '')
                    ON CONFLICT (racing_date, course, stage) DO NOTHING
                    """
                ),
                {"d": racing_date, "c": course, "s": stage},
            )
        # FIXTURE 階段直接 ok
        conn.execute(
            text(
                """
                UPDATE meeting_pipeline SET status='ok', detail='已在賽期表',
                  updated_at=CURRENT_TIMESTAMP
                WHERE racing_date=:d AND course=:c AND stage='FIXTURE'
                """
            ),
            {"d": racing_date, "c": course},
        )

    def list_fixtures(self, upcoming_only: bool = True) -> pd.DataFrame:
        q = "SELECT * FROM fixtures"
        if upcoming_only:
            q += " WHERE racing_date >= CURRENT_DATE" if not USE_SQLITE else \
                f" WHERE racing_date >= '{date.today().isoformat()}'"
        q += " ORDER BY racing_date ASC"
        try:
            return pd.read_sql(text(q), self.engine)
        except Exception:
            return pd.DataFrame()

    def get_stages(self, racing_date: str, course: str) -> pd.DataFrame:
        return pd.read_sql(
            text(
                "SELECT * FROM meeting_pipeline WHERE racing_date=:d AND course=:c"
            ),
            self.engine,
            params={"d": racing_date, "c": course},
        )

    def set_stage(
        self,
        racing_date: str,
        course: str,
        stage: str,
        status: str,
        detail: str = "",
        manual: bool = False,
    ):
        with self.engine.begin() as conn:
            self._ensure_stages(conn, racing_date, course)
            conn.execute(
                text(
                    """
                    UPDATE meeting_pipeline
                    SET status=:st, detail=:detail, manual_override=:m,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE racing_date=:d AND course=:c AND stage=:stage
                    """
                ),
                {
                    "st": status,
                    "detail": detail[:2000] if detail else "",
                    "m": manual,
                    "d": racing_date,
                    "c": course,
                    "stage": stage,
                },
            )

    # ---------- readiness（單一真相）----------
    def check_racecard(self, racing_date: str, course: str) -> Tuple[str, str]:
        d = racing_date[:10]
        q = text(
            """
            SELECT r.race_id, r.race_num, COUNT(u.runner_id) AS n
            FROM upcoming_races r
            LEFT JOIN upcoming_runners u ON r.race_id = u.race_id
            WHERE CAST(r.racing_date AS TEXT) LIKE :d AND r.course = :c
            GROUP BY r.race_id, r.race_num
            ORDER BY r.race_num
            """
        )
        # PG date compare
        if not USE_SQLITE:
            q = text(
                """
                SELECT r.race_id, r.race_num, COUNT(u.runner_id) AS n
                FROM upcoming_races r
                LEFT JOIN upcoming_runners u ON r.race_id = u.race_id
                WHERE r.racing_date = CAST(:d AS DATE) AND r.course = :c
                GROUP BY r.race_id, r.race_num
                ORDER BY r.race_num
                """
            )
        df = pd.read_sql(q, self.engine, params={"d": d, "c": course})
        if df.empty:
            return STATUS_PENDING, "尚無排位賽事"
        empty = df[df["n"] == 0]
        if not empty.empty:
            return STATUS_FAILED, f"{len(empty)} 場無馬匹"
        # 抽樣檢查欄位錯位
        from inference_engine import InferenceEngine
        sample_id = str(df.iloc[0]["race_id"])
        runners = InferenceEngine().get_race_runners(sample_id)
        bad, msg = _racecard_looks_corrupt(runners)
        if bad:
            return STATUS_FAILED, f"排位疑似錯位：{msg}"
        return STATUS_OK, f"{len(df)} 場、共 {int(df['n'].sum())} 匹"

    def check_speedguide(self, racing_date: str, course: str) -> Tuple[str, str]:
        d = racing_date.replace("-", "")[:8]
        prefix = f"{d}{course}"
        q = text(
            """
            SELECT
              (SELECT COUNT(*) FROM upcoming_runners WHERE race_id LIKE :p || '%') AS runners,
              (SELECT COUNT(*) FROM upcoming_speedguide WHERE race_id LIKE :p || '%'
                 AND speed_energy IS NOT NULL) AS sg
            """
        )
        row = pd.read_sql(q, self.engine, params={"p": prefix}).iloc[0]
        runners, sg = int(row["runners"] or 0), int(row["sg"] or 0)
        if runners == 0:
            return STATUS_PENDING, "尚無排位，無法對照 SG"
        cov = sg / runners if runners else 0
        # 距賽日 > 36h 且無資料 → waiting
        try:
            meet = date.fromisoformat(racing_date[:10])
            hours_to_race = (
                datetime.combine(meet, datetime.min.time()) - datetime.now()
            ).total_seconds() / 3600
        except Exception:
            hours_to_race = 48
        if cov >= 0.8:
            return STATUS_OK, f"覆蓋 {sg}/{runners} ({cov:.0%})"
        if hours_to_race > 36 and sg == 0:
            return STATUS_WAITING, f"距賽日約 {hours_to_race:.0f}h，官方 SG 可能尚未上架（{sg}/{runners}）"
        if sg == 0:
            return STATUS_WAITING, f"SG 仍空（{sg}/{runners}），可重爬或等待"
        return STATUS_FAILED, f"SG 覆蓋不足 {sg}/{runners} ({cov:.0%})"

    def check_formguide(self, racing_date: str, course: str) -> Tuple[str, str]:
        d = racing_date.replace("-", "")[:8]
        prefix = f"{d}{course}"
        q = text(
            """
            SELECT
              (SELECT COUNT(*) FROM upcoming_runners WHERE race_id LIKE :p || '%') AS runners,
              (SELECT COUNT(*) FROM upcoming_formguide WHERE race_id LIKE :p || '%'
                 AND form_text IS NOT NULL AND TRIM(form_text) <> '') AS fg
            """
        )
        try:
            row = pd.read_sql(q, self.engine, params={"p": prefix}).iloc[0]
        except Exception as e:
            return STATUS_PENDING, f"formguide 表不可用：{e}"
        runners, fg = int(row["runners"] or 0), int(row["fg"] or 0)
        if runners == 0:
            return STATUS_PENDING, "尚無排位"
        cov = fg / runners if runners else 0
        if cov >= 0.8:
            return STATUS_OK, f"覆蓋 {fg}/{runners} ({cov:.0%})"
        if fg == 0:
            return STATUS_WAITING, f"Form Guide 仍空（0/{runners}）"
        return STATUS_FAILED, f"Form Guide 覆蓋不足 {fg}/{runners}"

    def check_factors(self) -> Tuple[str, str]:
        from factor_calculator import FactorCalculator
        df = FactorCalculator().load_factor_scores(
            factor_types=["JOCKEY", "TRAINER", "SYNERGY", "DRAW", "HORSE", "PACE", "SPEED"]
        )
        if df is None or df.empty:
            return STATUS_PENDING, "factor_scores 为空"
        types = sorted(df["factor_type"].unique().tolist())
        return STATUS_OK, f"{len(df)} 筆；類型 {types}"

    def check_form_ai(self, racing_date: str, course: str) -> Tuple[str, str]:
        d = racing_date.replace("-", "")[:8]
        prefix = f"{d}{course}"
        try:
            q = text(
                """
                SELECT
                  (SELECT COUNT(*) FROM upcoming_runners WHERE race_id LIKE :p || '%') AS runners,
                  (SELECT COUNT(*) FROM upcoming_form_ai WHERE race_id LIKE :p || '%'
                     AND summary IS NOT NULL) AS ai
                """
            )
            row = pd.read_sql(q, self.engine, params={"p": prefix}).iloc[0]
        except Exception:
            return STATUS_PENDING, "尚無 Form AI 表／結果"
        runners, ai = int(row["runners"] or 0), int(row["ai"] or 0)
        if runners == 0:
            return STATUS_PENDING, "尚無排位"
        cov = ai / runners if runners else 0
        if cov >= 0.8:
            return STATUS_OK, f"覆蓋 {ai}/{runners} ({cov:.0%})"
        if ai == 0:
            return STATUS_PENDING, f"尚未跑 Form AI（0/{runners}）"
        return STATUS_FAILED, f"Form AI 覆蓋不足 {ai}/{runners}"

    def check_snapshot(self, racing_date: str, course: str) -> Tuple[str, str]:
        q = text(
            """
            SELECT batch_id, settled_at,
                   (SELECT COUNT(*) FROM prediction_snapshots s WHERE s.batch_id=b.batch_id) AS n
            FROM prediction_snapshot_batches b
            WHERE CAST(racing_date AS TEXT) LIKE :d AND course=:c
            ORDER BY created_at DESC
            """
        )
        if not USE_SQLITE:
            q = text(
                """
                SELECT batch_id, settled_at,
                       (SELECT COUNT(*) FROM prediction_snapshots s WHERE s.batch_id=b.batch_id) AS n
                FROM prediction_snapshot_batches b
                WHERE racing_date = CAST(:d AS DATE) AND course=:c
                ORDER BY created_at DESC
                """
            )
        try:
            df = pd.read_sql(q, self.engine, params={"d": racing_date[:10], "c": course})
        except Exception:
            return STATUS_PENDING, "尚無快照表"
        if df.empty:
            return STATUS_PENDING, "尚未建立預測快照"
        row = df.iloc[0]
        return STATUS_OK, f"最新 batch `{row['batch_id']}`（{int(row['n'])} 列）"

    def check_results(self, racing_date: str, course: str) -> Tuple[str, str]:
        d = racing_date.replace("-", "")[:8]
        prefix = f"{d}{course}"
        q = text(
            """
            SELECT COUNT(DISTINCT ru.race_id) AS races,
                   COUNT(*) AS runners
            FROM runners ru
            WHERE ru.race_id LIKE :p || '%'
              AND ru.finish_order_num IS NOT NULL
            """
        )
        row = pd.read_sql(q, self.engine, params={"p": prefix}).iloc[0]
        races, runners = int(row["races"] or 0), int(row["runners"] or 0)
        if races == 0:
            return STATUS_WAITING, "歷史庫尚無名次（待 J18 賽後更新）"
        return STATUS_OK, f"{races} 場已有名次、{runners} 匹"

    def check_settled(self, racing_date: str, course: str) -> Tuple[str, str]:
        q = text(
            """
            SELECT batch_id, settled_at FROM prediction_snapshot_batches
            WHERE CAST(racing_date AS TEXT) LIKE :d AND course=:c
              AND settled_at IS NOT NULL
            ORDER BY settled_at DESC
            """
        )
        if not USE_SQLITE:
            q = text(
                """
                SELECT batch_id, settled_at FROM prediction_snapshot_batches
                WHERE racing_date = CAST(:d AS DATE) AND course=:c
                  AND settled_at IS NOT NULL
                ORDER BY settled_at DESC
                """
            )
        try:
            df = pd.read_sql(q, self.engine, params={"d": racing_date[:10], "c": course})
        except Exception:
            return STATUS_PENDING, "無結算紀錄"
        if df.empty:
            return STATUS_PENDING, "快照尚未結算"
        return STATUS_OK, f"已結算 `{df.iloc[0]['batch_id']}`"

    def refresh_readiness(self, racing_date: str, course: str) -> Dict[str, Any]:
        """重算各階段真實狀態（保留 manual_override=ok 的不覆蓋）。"""
        stages_now = self.get_stages(racing_date, course)
        manual_ok = set()
        if not stages_now.empty:
            for _, r in stages_now.iterrows():
                if r.get("manual_override") and r.get("status") in (STATUS_OK, STATUS_SKIPPED):
                    manual_ok.add(r["stage"])

        checks = {
            "FIXTURE": (STATUS_OK, "已在賽期表"),
            "RACECARD": self.check_racecard(racing_date, course),
            "SPEEDGUIDE": self.check_speedguide(racing_date, course),
            "FORMGUIDE": self.check_formguide(racing_date, course),
            "FACTORS": self.check_factors(),
            "NLP": (STATUS_PENDING, "可選；於近績頁／批次手動"),
            "FORM_AI": self.check_form_ai(racing_date, course),
            "SNAPSHOT": self.check_snapshot(racing_date, course),
            "RESULTS": self.check_results(racing_date, course),
            "SETTLED": self.check_settled(racing_date, course),
        }
        out = {}
        for stage, (st, detail) in checks.items():
            if stage in manual_ok:
                out[stage] = {"status": STATUS_OK, "detail": f"[人工放行] {detail}", "manual": True}
                continue
            self.set_stage(racing_date, course, stage, st, detail, manual=False)
            out[stage] = {"status": st, "detail": detail, "manual": False}
        return out

    def run_action(self, racing_date: str, course: str, action: str) -> Dict[str, Any]:
        """手動節點動作。"""
        d_slash = racing_date.replace("-", "/")
        env = os.environ.copy()
        try:
            if action == "crawl_fixtures":
                from fixture_crawler import HKJCFixtureCrawler
                import asyncio
                return asyncio.run(HKJCFixtureCrawler().crawl_season())

            root = os.path.dirname(os.path.abspath(__file__))
            if action == "crawl_racecard":
                r = subprocess.run(
                    ["python", "racecard_crawler.py", "--date", d_slash, "--course", course],
                    capture_output=True, text=True, env=env, timeout=600, cwd=root,
                )
                ok = r.returncode == 0
                self.refresh_readiness(racing_date, course)
                return {"ok": ok, "stdout": r.stdout[-2000:], "stderr": r.stderr[-1000:]}

            if action == "crawl_speedguide":
                r = subprocess.run(
                    ["python", "speedguide_crawler.py", "--date", d_slash, "--course", course],
                    capture_output=True, text=True, env=env, timeout=600, cwd=root,
                )
                self.refresh_readiness(racing_date, course)
                return {"ok": r.returncode == 0, "stdout": r.stdout[-2000:], "stderr": r.stderr[-1000:]}

            if action == "crawl_formguide":
                r = subprocess.run(
                    ["python", "formguide_crawler.py", "--date", d_slash, "--course", course],
                    capture_output=True, text=True, env=env, timeout=600, cwd=root,
                )
                self.refresh_readiness(racing_date, course)
                return {"ok": r.returncode == 0, "stdout": r.stdout[-2000:], "stderr": r.stderr[-1000:]}

            if action == "run_factors":
                from factor_calculator import FactorCalculator
                calc = FactorCalculator()
                result = calc.run_all_factors(persist=True, apply_nlp=False)
                if result is None or result[0] is None:
                    return {"ok": False, "error": "無歷史數據或計算失敗"}
                self.refresh_readiness(racing_date, course)
                return {"ok": True, "msg": "已重算並寫入 factor_scores"}

            if action == "run_form_ai":
                from form_ai_analyst import FormAIAnalyst
                from inference_engine import InferenceEngine
                analyst = FormAIAnalyst()
                if not analyst.is_ready():
                    return {"ok": False, "error": "無 OPENAI_API_KEY"}
                races = InferenceEngine().get_upcoming_races()
                races = races[
                    (races["racing_date"].astype(str).str[:10] == racing_date[:10])
                    & (races["course"].astype(str) == course)
                ]
                done = 0
                for rid in races["race_id"].tolist():
                    out = analyst.analyze_race(str(rid), only_missing=True)
                    done += out.get("done", 0)
                self.refresh_readiness(racing_date, course)
                return {"ok": True, "done": done}

            if action == "snapshot":
                from factor_calibration import FactorCalibration
                out = FactorCalibration().snapshot_meeting(racing_date, course)
                self.refresh_readiness(racing_date, course)
                return out

            if action == "settle":
                from factor_calibration import FactorCalibration
                out = FactorCalibration().settle_pending()
                self.refresh_readiness(racing_date, course)
                return out

            if action == "mark_ok":
                # need stage in kwargs — handled by caller via set_stage
                return {"ok": True}

            return {"ok": False, "error": f"未知動作 {action}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
