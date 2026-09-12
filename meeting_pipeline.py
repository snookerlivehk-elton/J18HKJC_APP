"""
賽日作戰管線：fixtures + 各階段狀態 + readiness 檢查 + 手動節點動作。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import create_engine, text

from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH, resolve_database_url

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    # Railway 常只設 DATABASE_URL；勿只讀 DATABASE_URL_SYNC 否則會落到 localhost
    DATABASE_URL_SYNC = resolve_database_url()
    if DATABASE_URL_SYNC.startswith("postgres://"):
        DATABASE_URL_SYNC = DATABASE_URL_SYNC.replace("postgres://", "postgresql://", 1)

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

# 一鍵完成階段 → 主路徑 run_action（作戰室／Ops Center）
STAGE_PRIMARY_ACTION: Dict[str, str] = {
    "FIXTURE": "crawl_fixtures",
    "RACECARD": "sync_jjjc_racecard",
    "SPEEDGUIDE": "crawl_speedguide",
    "FORMGUIDE": "crawl_formguide",
    "FACTORS": "run_factors",
    "NLP": "run_backlog_chain",
    "FORM_AI": "start_form_ai_background",
    "SNAPSHOT": "snapshot",
    "RESULTS": "sync_jjjc_results",
    "SETTLED": "settle",
}

STAGE_HELP: Dict[str, str] = {
    "FIXTURE": "從 HKJC Fixture.aspx 抓整季賽期表；通常只需做一次。",
    "RACECARD": "優先同步 jjjc 排位 export；錯位時改用備援 HKJC HTML。",
    "SPEEDGUIDE": "JJJC speedguide 主路徑；空殼／waiting 會打 HKJC CMS 備援（JJJC 爬蟲修好前）。",
    "FORMGUIDE": "JJJC formguide 主路徑；覆蓋不足可重抓或等待。",
    "FACTORS": "重算 factor_scores（預設不含 NLP 干擾）；需排位後才自動跑；有評述後再用「含 NLP」。",
    "NLP": "可選強化：評述 → NLP → 干擾通道。不阻擋快照／結算。一鍵可跑遺留鏈。",
    "FORM_AI": "硬閘：SG＋FormGuide＋Factors 皆 ok 才後台啟動。覆蓋 ≥80% 才出正式快照。",
    "SNAPSHOT": "SG＋FormGuide＋Factors＋Form AI 齊備才建 primary；否則可 provisional／revision。",
    "RESULTS": "賽後同步 jjjc results（名次／派彩）；結算依賴此步。",
    "SETTLED": "快照 × 名次結算命中率；與當日評述無關。",
}


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

    def check_nlp(self, racing_date: str, course: str) -> Tuple[str, str]:
        """
        NLP／沿路走勢評述為可選強化，不阻擋快照與賽後結算。
        無評述＝干擾持份者低 coverage，無需人工放行。
        """
        # 粗略：庫內是否已有任何 nlp_result（不綁本賽日——賽後評述屬歷史強化）
        try:
            q = text(
                """
                SELECT
                  COUNT(*) FILTER (WHERE nlp_result IS NOT NULL) AS done,
                  COUNT(*) AS total
                FROM text_reports
                WHERE entity_type = 'runner'
                """
            )
            if USE_SQLITE:
                q = text(
                    """
                    SELECT
                      SUM(CASE WHEN nlp_result IS NOT NULL THEN 1 ELSE 0 END) AS done,
                      COUNT(*) AS total
                    FROM text_reports
                    WHERE entity_type = 'runner'
                    """
                )
            row = pd.read_sql(q, self.engine).iloc[0]
            done, total = int(row["done"] or 0), int(row["total"] or 0)
        except Exception:
            done, total = 0, 0

        if total == 0:
            return (
                STATUS_OK,
                "可選｜尚無 text_reports；無沿路走勢亦可建快照／結算（干擾降覆蓋），無需人工放行",
            )
        if done == 0:
            return (
                STATUS_OK,
                "可選｜評述尚未解析；不阻擋快照／結算。有評述後再批次 NLP→重算干擾→revision",
            )
        return (
            STATUS_OK,
            f"可選｜已解析 {done}/{total}；本節點不阻擋快照／結算",
        )

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
            SELECT batch_id, settled_at, note,
                   (SELECT COUNT(*) FROM prediction_snapshots s WHERE s.batch_id=b.batch_id) AS n
            FROM prediction_snapshot_batches b
            WHERE CAST(racing_date AS TEXT) LIKE :d AND course=:c
            ORDER BY created_at DESC
            """
        )
        if not USE_SQLITE:
            q = text(
                """
                SELECT batch_id, settled_at, note, provisional, snapshot_kind, revision_of,
                       (SELECT COUNT(*) FROM prediction_snapshots s WHERE s.batch_id=b.batch_id) AS n
                FROM prediction_snapshot_batches b
                WHERE racing_date = CAST(:d AS DATE) AND course=:c
                ORDER BY created_at DESC
                """
            )
        try:
            df = pd.read_sql(q, self.engine, params={"d": racing_date[:10], "c": course})
        except Exception:
            # 舊庫無 provisional 欄
            try:
                q2 = text(
                    """
                    SELECT batch_id, settled_at,
                           (SELECT COUNT(*) FROM prediction_snapshots s WHERE s.batch_id=b.batch_id) AS n
                    FROM prediction_snapshot_batches b
                    WHERE CAST(racing_date AS TEXT) LIKE :d AND course=:c
                    ORDER BY created_at DESC
                    """
                )
                if not USE_SQLITE:
                    q2 = text(
                        """
                        SELECT batch_id, settled_at,
                               (SELECT COUNT(*) FROM prediction_snapshots s WHERE s.batch_id=b.batch_id) AS n
                        FROM prediction_snapshot_batches b
                        WHERE racing_date = CAST(:d AS DATE) AND course=:c
                        ORDER BY created_at DESC
                        """
                    )
                df = pd.read_sql(q2, self.engine, params={"d": racing_date[:10], "c": course})
            except Exception:
                return STATUS_PENDING, "尚無快照表"
        if df.empty:
            return STATUS_PENDING, "尚未建立預測快照"
        row = df.iloc[0]
        tags = []
        if "snapshot_kind" in df.columns and pd.notna(row.get("snapshot_kind")):
            tags.append(str(row["snapshot_kind"]))
        if "provisional" in df.columns and bool(row.get("provisional")):
            tags.append("provisional")
        if "revision_of" in df.columns and pd.notna(row.get("revision_of")):
            tags.append(f"rev←{row['revision_of']}")
        tag_s = f" [{', '.join(tags)}]" if tags else ""
        return STATUS_OK, f"最新 batch `{row['batch_id']}`{tag_s}（{int(row['n'])} 列）"

    def check_results(self, racing_date: str, course: str) -> Tuple[str, str]:
        d = racing_date.replace("-", "")[:8]
        prefix = f"{d}{course}"
        q = text(
            """
            SELECT COUNT(DISTINCT ru.race_id) AS races,
                   COUNT(DISTINCT ru.race_id || ':' || CAST(ru.horse_no AS TEXT)) AS runners
            FROM runners ru
            WHERE ru.race_id LIKE :p || '%'
              AND ru.finish_order_num IS NOT NULL
            """
        )
        row = pd.read_sql(q, self.engine, params={"p": prefix}).iloc[0]
        races, runners = int(row["races"] or 0), int(row["runners"] or 0)
        if races == 0:
            return STATUS_WAITING, "歷史庫尚無名次（待 jjjc 同步或 J18 賽後更新）"
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
            "NLP": self.check_nlp(racing_date, course),
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

    def start_form_ai_background(
        self,
        racing_date: str,
        course: str,
        *,
        only_missing: bool = True,
    ) -> Dict[str, Any]:
        """
        後台啟動 Form AI（subprocess，關閉手機頁面不中斷）。
        進度寫入 background_jobs；用 get_form_ai_job 查詢。
        """
        import form_ai_batch_job as faj

        faj.ensure_jobs_table(self.engine)
        # 若已有 running，避免重複開
        latest = faj.latest_job(
            self.engine, job_type="form_ai", racing_date=racing_date, course=course
        )
        if latest and str(latest.get("status") or "") == "running":
            return {
                "ok": False,
                "error": "已有 Form AI 任務進行中",
                "job_id": latest.get("job_id"),
                "job": latest,
            }

        job_id = faj.create_job(
            self.engine,
            job_type="form_ai",
            racing_date=racing_date[:10],
            course=course.upper(),
            detail="ops background start",
        )
        root = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(root, "logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            log_dir = "/tmp"
        log_path = os.path.join(log_dir, f"form_ai_{job_id}.log")
        cmd = [
            sys.executable,
            "form_ai_batch_job.py",
            "--date",
            racing_date[:10],
            "--course",
            course.upper(),
            "--job-id",
            job_id,
            "--sleep",
            "0.15",
        ]
        if not only_missing:
            cmd.append("--all")

        env = os.environ.copy()
        try:
            with open(log_path, "ab", buffering=0) as logf:
                # 脫離 Streamlit session：關閉 stdin，stdout/err → log
                proc = subprocess.Popen(
                    cmd,
                    cwd=root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            faj.update_job(
                self.engine,
                job_id,
                status="running",
                detail=f"pid={proc.pid} log={log_path}",
                progress={"phase": "spawned", "pid": proc.pid, "log": log_path},
            )
            return {
                "ok": True,
                "job_id": job_id,
                "pid": proc.pid,
                "log_path": log_path,
                "message": "已後台啟動；可關閉本頁，稍後按「重新整理進度」",
            }
        except Exception as e:
            faj.update_job(
                self.engine, job_id, status="failed", detail=str(e), finished=True
            )
            return {"ok": False, "error": str(e), "job_id": job_id}

    def get_form_ai_job(
        self, racing_date: str, course: str, job_id: Optional[str] = None
    ) -> Dict[str, Any]:
        import form_ai_batch_job as faj

        faj.ensure_jobs_table(self.engine)
        if job_id:
            job = faj.get_job(self.engine, job_id)
        else:
            job = faj.latest_job(
                self.engine, job_type="form_ai", racing_date=racing_date, course=course
            )
        if not job:
            return {"ok": True, "job": None, "message": "尚無後台任務"}
        return {"ok": True, "job": job}

    def list_meeting_races(self, racing_date: str, course: str) -> pd.DataFrame:
        """賽日場次清單（作戰室 drill-down）。"""
        d = racing_date[:10]
        c = course.upper()
        if USE_SQLITE:
            q = text(
                """
                SELECT r.race_id, r.race_num, r.course, r.racing_date,
                       COUNT(u.runner_id) AS runner_n
                FROM upcoming_races r
                LEFT JOIN upcoming_runners u ON r.race_id = u.race_id
                WHERE CAST(r.racing_date AS TEXT) LIKE :d AND r.course = :c
                GROUP BY r.race_id, r.race_num, r.course, r.racing_date
                ORDER BY r.race_num
                """
            )
        else:
            q = text(
                """
                SELECT r.race_id, r.race_num, r.course, r.racing_date,
                       COUNT(u.runner_id) AS runner_n
                FROM upcoming_races r
                LEFT JOIN upcoming_runners u ON r.race_id = u.race_id
                WHERE r.racing_date = CAST(:d AS DATE) AND r.course = :c
                GROUP BY r.race_id, r.race_num, r.course, r.racing_date
                ORDER BY r.race_num
                """
            )
        try:
            return pd.read_sql(q, self.engine, params={"d": d, "c": c})
        except Exception:
            return pd.DataFrame()

    def list_race_runners(self, race_id: str) -> pd.DataFrame:
        """單場馬匹列（含 SG 若有）。"""
        try:
            from inference_engine import InferenceEngine

            return InferenceEngine().get_race_runners(str(race_id))
        except Exception:
            return pd.DataFrame()

    def stage_help(self, stage: str) -> str:
        return STAGE_HELP.get(stage, "")

    def stage_preview(self, racing_date: str, course: str) -> List[Dict[str, Any]]:
        """各階段就緒預覽（不寫庫；供 Ops Center 總覽）。"""
        ready = self.refresh_readiness(racing_date, course)
        rows: List[Dict[str, Any]] = []
        for stage, label in STAGES:
            info = ready.get(stage) or {}
            rows.append(
                {
                    "stage": stage,
                    "label": label,
                    "status": info.get("status", STATUS_PENDING),
                    "detail": info.get("detail", ""),
                    "manual": bool(info.get("manual")),
                    "primary_action": STAGE_PRIMARY_ACTION.get(stage),
                    "help": STAGE_HELP.get(stage, ""),
                }
            )
        return rows

    def complete_stage(
        self,
        racing_date: str,
        course: str,
        stage: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """一鍵完成該階段主路徑動作。"""
        stage = (stage or "").upper()
        action = STAGE_PRIMARY_ACTION.get(stage)
        if not action:
            return {"ok": False, "error": f"無主路徑對應：{stage}"}
        if action == "run_backlog_chain":
            return self.run_backlog_chain(racing_date, course, **kwargs)
        if action == "crawl_fixtures":
            return self.run_action("", "", action, **kwargs)
        out = self.run_action(racing_date, course, action, **kwargs)
        out.setdefault("stage", stage)
        out.setdefault("action", action)
        return out

    def run_backlog_chain(
        self,
        racing_date: str,
        course: str,
        *,
        force: bool = True,
        run_nlp: bool = True,
        run_factors: bool = True,
    ) -> Dict[str, Any]:
        """
        一鍵遺留鏈：同步 text-reports（評述）→ NLP → 因子（含干擾）。
        作戰室／人工介入用；與 tick 自動 backlog 路徑對齊。
        """
        d, c = racing_date[:10], course.upper()
        out: Dict[str, Any] = {
            "ok": True,
            "action": "run_backlog_chain",
            "racing_date": d,
            "course": c,
            "sync": None,
            "nlp": None,
            "factors": None,
        }
        try:
            from data_backlog import DataBacklogService

            bl = DataBacklogService(engine=self.engine)
            enroll = bl.enroll_meeting(d, c)
            sync = self.run_action(d, c, "sync_jjjc_text_reports")
            out["enroll"] = enroll
            out["sync"] = {
                k: sync.get(k)
                for k in (
                    "ok",
                    "waiting",
                    "runner_upserted",
                    "error",
                    "detail",
                    "upserted",
                )
                if sync.get(k) is not None
            }
            new_n = int(
                sync.get("runner_upserted")
                or sync.get("upserted")
                or sync.get("n_upserted")
                or 0
            )
            # 即使本輪 upsert=0，force 時仍可嘗試 NLP（庫內可能已有未解析評述）
            if run_nlp:
                nlp_out = bl.maybe_run_nlp_pipeline(
                    new_upserts=max(new_n, 1 if force else 0),
                    dry_run=False,
                )
                # maybe_run_nlp 受 AUTO_BACKLOG_* 開關影響；一鍵鏈可強制補跑
                if nlp_out.get("skipped") and force:
                    nlp_out = self._force_nlp_factors(
                        run_factors=run_factors
                    )
                elif run_factors and not (nlp_out.get("factors")):
                    # NLP 已跑但 AUTO_FACTORS=false 時補跑
                    try:
                        from factor_calculator import FactorCalculator

                        fac = FactorCalculator().run_all_factors(
                            persist=True, apply_nlp=True
                        )
                        nlp_out["factors"] = {
                            "ok": fac is not None,
                            "forced": True,
                            "result": str(fac)[:200] if fac is not None else None,
                        }
                    except Exception as e:
                        nlp_out["factors"] = {"ok": False, "error": str(e)}
                out["nlp"] = nlp_out.get("nlp")
                out["factors"] = nlp_out.get("factors")
                if nlp_out.get("skipped"):
                    out["nlp_note"] = nlp_out.get("skipped")
            self.refresh_readiness(d, c)
            if sync.get("ok") is False:
                out["ok"] = False
                out["error"] = sync.get("error") or "text_reports sync failed"
            return out
        except Exception as e:
            out["ok"] = False
            out["error"] = str(e)
            return out

    def _force_nlp_factors(self, *, run_factors: bool = True) -> Dict[str, Any]:
        """繞過 AUTO_BACKLOG_*：強制 NLP（再可選因子）。"""
        out: Dict[str, Any] = {"nlp": None, "factors": None}
        try:
            from factor_calculator import FactorCalculator
            from nlp_processor import NLPProcessor

            calc = FactorCalculator()
            nlp = NLPProcessor()
            if not nlp.is_ready():
                out["nlp"] = {"ok": False, "error": "OPENAI_API_KEY 未設定"}
                return out
            rows = calc.load_unprocessed_reports(limit=50, skip_trivial=True)
            done = 0
            errors = 0
            for r in rows:
                try:
                    parsed = nlp.analyze_report_sync(str(r.get("report_text") or ""))
                    calc.save_nlp_result(int(r["id"]), parsed)
                    done += 1
                except Exception:
                    errors += 1
            out["nlp"] = {"ok": True, "parsed": done, "errors": errors, "forced": True}
            if run_factors and done > 0:
                try:
                    fac = calc.run_all_factors(persist=True, apply_nlp=True)
                    out["factors"] = {"ok": True, "result": str(fac)[:200], "forced": True}
                except Exception as e:
                    out["factors"] = {"ok": False, "error": str(e)}
        except Exception as e:
            out["nlp"] = {"ok": False, "error": str(e)}
        return out

    def run_action(self, racing_date: str, course: str, action: str, **kwargs) -> Dict[str, Any]:
        """手動節點動作。kwargs：如 run_form_ai 的 only_missing、progress_cb。"""
        d_slash = racing_date.replace("-", "/")
        env = os.environ.copy()
        try:
            if action == "run_backlog_chain":
                return self.run_backlog_chain(
                    racing_date,
                    course,
                    force=bool(kwargs.get("force", True)),
                    run_nlp=bool(kwargs.get("run_nlp", True)),
                    run_factors=bool(kwargs.get("run_factors", True)),
                )

            if action == "complete_stage":
                return self.complete_stage(
                    racing_date,
                    course,
                    str(kwargs.get("stage") or ""),
                    **{k: v for k, v in kwargs.items() if k != "stage"},
                )

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

            if action == "sync_jjjc_racecard":
                from jjjc_racecard_sync import sync_meeting

                out = sync_meeting(
                    racing_date=racing_date,
                    course=course,
                    race_no=kwargs.get("race_no"),
                    from_file=kwargs.get("from_file"),
                    base_url=kwargs.get("base_url"),
                )
                self.refresh_readiness(racing_date, course)
                return out

            if action == "sync_jjjc_results":
                from jjjc_results_sync import sync_meeting as sync_results

                out = sync_results(
                    racing_date=racing_date,
                    course=course,
                    race_no=kwargs.get("race_no"),
                    from_file=kwargs.get("from_file"),
                    base_url=kwargs.get("base_url"),
                )
                self.refresh_readiness(racing_date, course)
                return out

            if action == "sync_jjjc_speedguide":
                from jjjc_speedguide_sync import sync_meeting as sync_sg

                out = sync_sg(
                    racing_date=racing_date,
                    course=course,
                    race_no=kwargs.get("race_no"),
                    from_file=kwargs.get("from_file"),
                    base_url=kwargs.get("base_url"),
                )
                self.refresh_readiness(racing_date, course)
                return out

            if action == "sync_jjjc_formguide":
                from jjjc_formguide_sync import sync_meeting as sync_fg

                out = sync_fg(
                    racing_date=racing_date,
                    course=course,
                    race_no=kwargs.get("race_no"),
                    from_file=kwargs.get("from_file"),
                    base_url=kwargs.get("base_url"),
                )
                self.refresh_readiness(racing_date, course)
                return out

            if action == "sync_jjjc_text_reports":
                from jjjc_text_reports_sync import sync_meeting as sync_tr

                out = sync_tr(
                    racing_date=racing_date,
                    course=course,
                    race_no=kwargs.get("race_no"),
                    report_type=kwargs.get("report_type"),
                    from_file=kwargs.get("from_file"),
                    base_url=kwargs.get("base_url"),
                )
                self.refresh_readiness(racing_date, course)
                return out

            if action == "crawl_speedguide":
                # 主路徑：JJJC export；空殼／waiting／失敗 → HKJC CMS 備援
                # （JJJC 爬蟲過渡期：waiting 也打 CMS，可用 MEETING_TICK_SG_CMS_ON_WAITING=false 關）
                from jjjc_speedguide_sync import sync_meeting as sync_sg

                cms_on_waiting = (
                    os.getenv("MEETING_TICK_SG_CMS_ON_WAITING", "true") or "true"
                ).lower() in ("1", "true", "yes")
                force_fallback = bool(kwargs.get("force_fallback"))

                jjjc = sync_sg(
                    racing_date=racing_date,
                    course=course,
                    race_no=kwargs.get("race_no"),
                    from_file=kwargs.get("from_file"),
                    base_url=kwargs.get("base_url"),
                )
                with_energy = int(
                    jjjc.get("runners_with_energy")
                    if jjjc.get("runners_with_energy") is not None
                    else jjjc.get("runner_upserted")
                    or 0
                )
                if (
                    jjjc.get("ok")
                    and not jjjc.get("waiting")
                    and with_energy > 0
                    and not force_fallback
                ):
                    self.refresh_readiness(racing_date, course)
                    return {**jjjc, "source": "jjjc"}
                if (
                    jjjc.get("ok")
                    and jjjc.get("waiting")
                    and not force_fallback
                    and not cms_on_waiting
                ):
                    # 僅當明確關閉 CMS-on-waiting 時才略過備援
                    self.refresh_readiness(racing_date, course)
                    return {**jjjc, "source": "jjjc", "fallback_skipped": "waiting"}
                py = env.get("PYTHON", "python3")
                r = subprocess.run(
                    [py, "speedguide_crawler.py", "--date", d_slash, "--course", course],
                    capture_output=True, text=True, env=env, timeout=600, cwd=root,
                )
                self.refresh_readiness(racing_date, course)
                return {
                    "ok": r.returncode == 0,
                    "source": "hkjc_cms_fallback",
                    "jjjc": {
                        k: jjjc.get(k)
                        for k in (
                            "ok",
                            "waiting",
                            "phase",
                            "error",
                            "runner_upserted",
                            "runners_with_energy",
                            "detail",
                        )
                        if k in jjjc
                    },
                    "stdout": r.stdout[-2000:],
                    "stderr": r.stderr[-1000:],
                }

            if action == "crawl_formguide":
                from jjjc_formguide_sync import sync_meeting as sync_fg

                jjjc = sync_fg(
                    racing_date=racing_date,
                    course=course,
                    race_no=kwargs.get("race_no"),
                    from_file=kwargs.get("from_file"),
                    base_url=kwargs.get("base_url"),
                )
                if jjjc.get("ok") and not jjjc.get("waiting") and int(jjjc.get("runners_with_text") or jjjc.get("runner_upserted") or 0) > 0:
                    self.refresh_readiness(racing_date, course)
                    return {**jjjc, "source": "jjjc"}
                if jjjc.get("ok") and jjjc.get("waiting") and not kwargs.get("force_fallback"):
                    self.refresh_readiness(racing_date, course)
                    return {**jjjc, "source": "jjjc", "fallback_skipped": "waiting"}
                py = env.get("PYTHON", "python3")
                r = subprocess.run(
                    [py, "formguide_crawler.py", "--date", d_slash, "--course", course],
                    capture_output=True, text=True, env=env, timeout=600, cwd=root,
                )
                self.refresh_readiness(racing_date, course)
                return {
                    "ok": r.returncode == 0,
                    "source": "hkjc_cms_fallback",
                    "jjjc": {
                        k: jjjc.get(k)
                        for k in ("ok", "waiting", "phase", "error", "runner_upserted", "detail")
                        if k in jjjc
                    },
                    "stdout": r.stdout[-2000:],
                    "stderr": r.stderr[-1000:],
                }

            if action == "run_factors":
                from factor_calculator import FactorCalculator
                calc = FactorCalculator()
                # stakeholder 模式：基礎因子不烤 NLP；干擾通道另行落庫（可低 coverage）
                result = calc.run_all_factors(persist=True, apply_nlp=False)
                if result is None or result[0] is None:
                    return {"ok": False, "error": "無歷史數據或計算失敗"}
                self.refresh_readiness(racing_date, course)
                return {"ok": True, "msg": "已重算並寫入 factor_scores（可降級／無 NLP）"}

            if action == "run_factors_with_nlp":
                from factor_calculator import FactorCalculator
                calc = FactorCalculator()
                result = calc.run_all_factors(persist=True, apply_nlp=True)
                if result is None or result[0] is None:
                    return {"ok": False, "error": "無歷史數據或計算失敗"}
                self.refresh_readiness(racing_date, course)
                return {"ok": True, "msg": "已重算 factor_scores（含干擾持份者／legacy NLP）"}

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
                race_ids = [str(x) for x in races["race_id"].tolist()]
                only_missing = bool(kwargs.get("only_missing", True))
                progress_cb = kwargs.get("progress_cb")
                done = 0
                n_races = len(race_ids)
                for i, rid in enumerate(race_ids, start=1):
                    def _cb(cur, tot, hno, res, _i=i, _rid=rid):
                        if not progress_cb:
                            return
                        progress_cb(
                            {
                                "race_index": _i,
                                "race_count": n_races,
                                "race_id": _rid,
                                "horse_done": cur,
                                "horse_total": tot,
                                "horse_no": hno,
                                "result": res,
                            }
                        )

                    out = analyst.analyze_race(
                        rid,
                        only_missing=only_missing,
                        progress_cb=_cb if progress_cb else None,
                    )
                    done += out.get("done", 0)
                self.refresh_readiness(racing_date, course)
                return {"ok": True, "done": done, "n_races": n_races}

            if action == "start_form_ai_background":
                out = self.start_form_ai_background(
                    racing_date,
                    course,
                    only_missing=bool(kwargs.get("only_missing", True)),
                )
                return out

            if action == "form_ai_job_status":
                return self.get_form_ai_job(
                    racing_date, course, job_id=kwargs.get("job_id")
                )

            if action == "start_ad_regen_background":
                from ops_jobs import start_background_job

                batch_id = kwargs.get("batch_id") or ""
                if not batch_id:
                    return {"ok": False, "error": "需要 batch_id"}
                return start_background_job(
                    job_type="ad_regen",
                    racing_date=racing_date or "",
                    course=course or "",
                    extra_args=["--batch", str(batch_id)],
                    detail=f"ad_regen {batch_id}",
                )

            if action == "start_nlp_meeting_background":
                from ops_jobs import start_background_job

                return start_background_job(
                    job_type="nlp_meeting",
                    racing_date=racing_date,
                    course=course,
                    detail="nlp_meeting",
                )

            if action == "start_factors_nlp_background":
                from ops_jobs import start_background_job

                return start_background_job(
                    job_type="factors_nlp",
                    racing_date=racing_date or "",
                    course=course or "",
                    detail="factors_nlp",
                )

            if action == "start_hit_snapshot_backfill":
                from ops_jobs import start_background_job

                extra = ["--all"] if kwargs.get("force_all") else []
                return start_background_job(
                    job_type="hit_snapshot_bf",
                    racing_date=racing_date or "",
                    course=course or "",
                    extra_args=extra,
                    detail="hit_rate day snapshot backfill",
                )

            if action == "job_status":
                from ops_jobs import get_job

                return get_job(
                    job_id=kwargs.get("job_id"),
                    job_type=kwargs.get("job_type") or "form_ai",
                    racing_date=racing_date or None,
                    course=course or None,
                )

            if action == "snapshot":
                from factor_calibration import FactorCalibration
                out = FactorCalibration().snapshot_meeting(racing_date, course)
                self.refresh_readiness(racing_date, course)
                return out

            if action == "revise_snapshot":
                from factor_calibration import FactorCalibration
                out = FactorCalibration().revise_snapshot(
                    racing_date,
                    course,
                    base_batch_id=kwargs.get("base_batch_id"),
                    note=kwargs.get("note") or "",
                )
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
