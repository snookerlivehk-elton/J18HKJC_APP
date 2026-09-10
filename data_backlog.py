"""
數據遺留清單（延遲資料／沿路走勢等）。

用途：
  - RESULTS 已齊但 running_comment／incident_report 覆蓋不足 → 入列
  - 超出 MEETING_TICK_LOOKBACK 仍可在保留窗（預設 14 日）內退避重試
  - 操作員 UI 一眼看清未入庫項目
  - 本輪有新評述寫入 → 可選觸發 NLP batch（不重結已 settled 快照）

表：data_backlog（見 AUTOMATION_HANDBOOK §11）
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from etl_pipeline import USE_SQLITE, resolve_database_url

# ----- 預設 -----
DEFAULT_RETENTION_DAYS = int(os.getenv("MEETING_TICK_BACKLOG_RETENTION_DAYS", "14") or 14)
DEFAULT_COVERAGE_OK = float(os.getenv("MEETING_TICK_BACKLOG_COVERAGE_OK", "0.8") or 0.8)
DEFAULT_PROCESS_LIMIT = int(os.getenv("MEETING_TICK_BACKLOG_LIMIT", "10") or 10)
AUTO_BACKLOG = (os.getenv("MEETING_TICK_AUTO_BACKLOG", "true") or "true").lower() in (
    "1",
    "true",
    "yes",
)
AUTO_BACKLOG_NLP = (
    os.getenv("MEETING_TICK_BACKLOG_AUTO_NLP", "true") or "true"
).lower() in ("1", "true", "yes")
AUTO_BACKLOG_FACTORS = (
    os.getenv("MEETING_TICK_BACKLOG_AUTO_FACTORS", "false") or "false"
).lower() in ("1", "true", "yes")

KIND_RUNNING = "running_comment"
KIND_INCIDENT = "incident_report"
DEFAULT_KINDS = (KIND_RUNNING, KIND_INCIDENT)

STATUS_OPEN = "open"
STATUS_RETRYING = "retrying"
STATUS_DONE = "done"
STATUS_EXPIRED = "expired"
STATUS_SKIPPED = "skipped_manual"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _meeting_prefix(racing_date: str, course: str) -> str:
    d = str(racing_date).replace("-", "")[:8]
    return f"{d}{str(course).upper()}"


def _coverage_label(cov: Dict[str, Any]) -> str:
    """例如：`8場 91/112`（有 race_n 時帶場次數）。"""
    race_n = int(cov.get("race_n") or 0)
    pair = f"{int(cov.get('covered_n') or 0)}/{int(cov.get('expected_n') or 0)}"
    if race_n:
        return f"{race_n}場 {pair}"
    return pair


def backoff_seconds(attempt_count: int, age_days: float) -> int:
    """
    無固定節奏評述：首日 6h → 其後每日 → 7 日後每 2～3 日。
    """
    if age_days < 1:
        return 6 * 3600
    if age_days < 7:
        return 24 * 3600
    return 72 * 3600


class DataBacklogService:
    def __init__(self, engine: Optional[Engine] = None) -> None:
        if engine is not None:
            self.engine = engine
            self._owns_engine = False
        else:
            if USE_SQLITE:
                from etl_pipeline import SQLITE_DB_PATH

                self.engine = create_engine(f"sqlite:///{SQLITE_DB_PATH}")
            else:
                self.engine = create_engine(resolve_database_url())
            self._owns_engine = True
        self.ensure_table()

    @property
    def _sqlite(self) -> bool:
        return str(self.engine.dialect.name) == "sqlite"

    def ensure_table(self) -> None:
        if self._sqlite:
            ddl = """
            CREATE TABLE IF NOT EXISTS data_backlog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                racing_date TEXT NOT NULL,
                course TEXT NOT NULL,
                race_id TEXT,
                data_kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                expected_n INTEGER DEFAULT 0,
                covered_n INTEGER DEFAULT 0,
                coverage REAL DEFAULT 0,
                first_seen_at TEXT,
                last_attempt_at TEXT,
                next_attempt_at TEXT,
                done_at TEXT,
                expired_at TEXT,
                attempt_count INTEGER DEFAULT 0,
                last_error TEXT,
                detail TEXT,
                source_hint TEXT DEFAULT 'jjjc',
                UNIQUE (racing_date, course, data_kind, race_id)
            )
            """
            idx = """
            CREATE INDEX IF NOT EXISTS idx_data_backlog_status
            ON data_backlog(status, next_attempt_at)
            """
        else:
            ddl = """
            CREATE TABLE IF NOT EXISTS data_backlog (
                id SERIAL PRIMARY KEY,
                racing_date DATE NOT NULL,
                course VARCHAR(10) NOT NULL,
                race_id VARCHAR(50),
                data_kind VARCHAR(50) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                expected_n INT DEFAULT 0,
                covered_n INT DEFAULT 0,
                coverage DOUBLE PRECISION DEFAULT 0,
                first_seen_at TIMESTAMPTZ,
                last_attempt_at TIMESTAMPTZ,
                next_attempt_at TIMESTAMPTZ,
                done_at TIMESTAMPTZ,
                expired_at TIMESTAMPTZ,
                attempt_count INT DEFAULT 0,
                last_error TEXT,
                detail TEXT,
                source_hint VARCHAR(40) DEFAULT 'jjjc',
                UNIQUE (racing_date, course, data_kind, race_id)
            )
            """
            idx = """
            CREATE INDEX IF NOT EXISTS idx_data_backlog_status
            ON data_backlog(status, next_attempt_at)
            """
        with self.engine.begin() as conn:
            conn.execute(text(ddl))
            conn.execute(text(idx))

    # ----- 覆蓋檢查 -----
    def _fetch_results_race_ids(
        self, racing_date: str, course: str
    ) -> List[str]:
        """輕拉 JJJC results export 的 race_id 清單（權威場次；失敗則 []）。"""
        try:
            from jjjc_results_sync import fetch_export

            payload = fetch_export(
                race_date=str(racing_date)[:10],
                venue=str(course).upper(),
                timeout=45.0,
            )
            ids: List[str] = []
            for race in payload.get("races") or []:
                rid = str((race or {}).get("race_id") or "").strip()
                if rid:
                    ids.append(rid)
            return sorted(set(ids))
        except Exception:
            return []

    def reconcile_meeting_results(
        self, racing_date: str, course: str
    ) -> Dict[str, Any]:
        """
        重拉 JJJC results 並 prune 同 prefix 幽靈場（如 HV09–10 → 140）。
        覆蓋分母依賴此步；只跑 text-reports 不夠。
        """
        try:
            from jjjc_results_sync import sync_meeting

            out = sync_meeting(str(racing_date)[:10], str(course).upper())
            return {
                "ok": bool(out.get("ok")),
                "race_count": out.get("race_count"),
                "pruned_orphan_races": out.get("pruned_orphan_races") or [],
                "pruned_runners": out.get("pruned_runners") or 0,
                "error": out.get("error"),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _canonical_race_ids(self, prefix: str) -> List[str]:
        """
        若該會議已有 jjjc results sync 的 runners，只認那些 race_id，
        避免 batch_crawler／舊 J18 歷史殘留的幽靈場次（例如 8 場日卻出現 HV09–10 → 140）。
        尚無 jjjc 標記時回傳 []，呼叫端改用全量 prefix。
        """
        q = text(
            """
            SELECT DISTINCT race_id
            FROM runners
            WHERE race_id LIKE :p || '%'
              AND finish_order_num IS NOT NULL
              AND (
                CAST(raw_json AS TEXT) LIKE '%jjjc_results_sync%'
                OR CAST(raw_json AS TEXT) LIKE '%"source": "official_hkjc"%'
                OR CAST(raw_json AS TEXT) LIKE '%"source":"official_hkjc"%'
              )
            ORDER BY race_id
            """
        )
        try:
            df = pd.read_sql(q, self.engine, params={"p": prefix})
        except Exception:
            return []
        if df is None or df.empty:
            return []
        return [str(x) for x in df["race_id"].tolist() if x]

    def measure_comment_coverage(
        self,
        racing_date: str,
        course: str,
        data_kind: str = KIND_RUNNING,
        *,
        keep_race_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """
        以歷史 runners（有名次）為期望母體；text_reports 有正文則計入覆蓋。

        分母優先序：
          1) 呼叫端傳入的 keep_race_ids（通常來自 JJJC results export）
          2) 即時拉 results export 的 race_id
          3) DB 內 jjjc_results_sync 標記場次
          4) 全量 prefix（最後手段）
        一律 DISTINCT(race_id, horse_no)，避免幽靈場把 8×14 算成 10×14=140。
        """
        prefix = _meeting_prefix(racing_date, course)
        rtype = str(data_kind)
        keep = [
            str(x).strip()
            for x in (keep_race_ids or [])
            if str(x).strip()
        ]
        source = "arg"
        if not keep:
            keep = self._fetch_results_race_ids(racing_date, course)
            source = "export" if keep else "none"
        if not keep:
            keep = self._canonical_race_ids(prefix)
            source = "db_canon" if keep else "prefix_all"

        use_keep = 1 if keep else 0
        # race_id 僅允許 YYYYMMDD+(ST|HV)+兩位，可安全拼 IN 清單（SQLite／PG 通用）
        safe_ids = [
            rid
            for rid in keep
            if len(rid) == 12
            and rid[:8].isdigit()
            and rid[8:10] in ("ST", "HV")
            and rid[10:12].isdigit()
        ]
        if keep and not safe_ids:
            safe_ids = []
            use_keep = 0
        in_sql = (
            "(" + ",".join(f"'{rid}'" for rid in safe_ids) + ")"
            if safe_ids
            else "('__none__')"
        )
        q = text(
            f"""
            SELECT
              COUNT(DISTINCT ru.race_id) AS race_n,
              COUNT(DISTINCT ru.race_id || ':' || CAST(ru.horse_no AS TEXT)) AS expected_n,
              COUNT(
                DISTINCT CASE WHEN EXISTS (
                  SELECT 1 FROM text_reports tr
                  WHERE tr.entity_type = 'runner'
                    AND tr.report_type = :rtype
                    AND LENGTH(TRIM(tr.report_text)) > 0
                    AND (
                      tr.entity_id = ru.runner_id
                      OR tr.entity_id = (ru.race_id || '_' || CAST(ru.horse_no AS TEXT))
                    )
                ) THEN ru.race_id || ':' || CAST(ru.horse_no AS TEXT) END
              ) AS covered_n
            FROM runners ru
            WHERE ru.race_id LIKE :p || '%'
              AND ru.finish_order_num IS NOT NULL
              AND (
                :use_keep = 0
                OR ru.race_id IN {in_sql}
              )
            """
        )
        try:
            row = pd.read_sql(
                q,
                self.engine,
                params={
                    "p": prefix,
                    "rtype": rtype,
                    "use_keep": use_keep,
                },
            ).iloc[0]
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "expected_n": 0,
                "covered_n": 0,
                "race_n": 0,
                "coverage": 0.0,
                "prefix": prefix,
                "data_kind": rtype,
            }
        expected = int(row["expected_n"] or 0)
        covered = int(row["covered_n"] or 0)
        race_n = int(row["race_n"] or 0)
        cov = (covered / expected) if expected else 0.0
        return {
            "ok": True,
            "expected_n": expected,
            "covered_n": covered,
            "race_n": race_n,
            "coverage": round(cov, 4),
            "prefix": prefix,
            "data_kind": rtype,
            "racing_date": str(racing_date)[:10],
            "course": str(course).upper(),
            "keep_source": source,
            "keep_race_n": len(keep),
        }

    def coverage_ok(
        self, cov: Dict[str, Any], *, threshold: float = DEFAULT_COVERAGE_OK
    ) -> bool:
        if int(cov.get("expected_n") or 0) <= 0:
            return False
        return float(cov.get("coverage") or 0) >= float(threshold)

    # ----- 入列／更新 -----
    def enroll_meeting(
        self,
        racing_date: str,
        course: str,
        *,
        kinds: Sequence[str] = DEFAULT_KINDS,
        threshold: float = DEFAULT_COVERAGE_OK,
        as_of: Optional[date] = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> List[Dict[str, Any]]:
        """
        RESULTS 有名次且覆蓋不足 → open／retrying；已達標 → done（若曾入列）。
        超過保留窗 → expired。
        """
        d = str(racing_date)[:10]
        c = str(course).upper()
        today = as_of or date.today()
        try:
            age_days = (today - date.fromisoformat(d)).days
        except ValueError:
            age_days = 0

        # 入列前對齊 results（prune 幽靈場），分母才會正確
        self.reconcile_meeting_results(d, c)
        keep_ids = self._fetch_results_race_ids(d, c) or None

        out: List[Dict[str, Any]] = []
        for kind in kinds:
            cov = self.measure_comment_coverage(
                d, c, kind, keep_race_ids=keep_ids
            )
            if not cov.get("ok"):
                out.append({"racing_date": d, "course": c, "data_kind": kind, **cov})
                continue
            expected = int(cov["expected_n"])
            if expected <= 0:
                # 尚無名次母體 — 不入列
                out.append(
                    {
                        "racing_date": d,
                        "course": c,
                        "data_kind": kind,
                        "action": "skip_no_results",
                        **cov,
                    }
                )
                continue

            if age_days > int(retention_days):
                self._upsert_row(
                    d,
                    c,
                    kind,
                    status=STATUS_EXPIRED,
                    cov=cov,
                    detail=f"超過保留窗 {retention_days} 日",
                    expire=True,
                )
                out.append(
                    {
                        "racing_date": d,
                        "course": c,
                        "data_kind": kind,
                        "action": "expired",
                        **cov,
                    }
                )
                continue

            if self.coverage_ok(cov, threshold=threshold):
                self._upsert_row(
                    d,
                    c,
                    kind,
                    status=STATUS_DONE,
                    cov=cov,
                    detail=f"覆蓋達標 {_coverage_label(cov)}",
                    done=True,
                )
                out.append(
                    {
                        "racing_date": d,
                        "course": c,
                        "data_kind": kind,
                        "action": "done",
                        **cov,
                    }
                )
            else:
                existing = self.get_item(d, c, kind)
                status = STATUS_RETRYING if existing and int(existing.get("attempt_count") or 0) > 0 else STATUS_OPEN
                next_at = _utcnow()
                if existing and existing.get("next_attempt_at") and status == STATUS_RETRYING:
                    # 保留既有 next_attempt，除非已過期該排程
                    pass
                self._upsert_row(
                    d,
                    c,
                    kind,
                    status=status,
                    cov=cov,
                    detail=f"覆蓋不足 {_coverage_label(cov)} ({cov['coverage']:.0%})",
                    next_attempt_at=next_at if not existing else None,
                    keep_next_if_set=True,
                )
                out.append(
                    {
                        "racing_date": d,
                        "course": c,
                        "data_kind": kind,
                        "action": "enrolled",
                        "status": status,
                        **cov,
                    }
                )
        return out

    def get_item(
        self,
        racing_date: str,
        course: str,
        data_kind: str,
        race_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        df = pd.read_sql(
            text(
                """
                SELECT * FROM data_backlog
                WHERE CAST(racing_date AS TEXT) LIKE :d
                  AND course = :c AND data_kind = :k
                  AND (race_id IS NULL OR race_id = '' OR race_id = :rid)
                ORDER BY id DESC LIMIT 1
                """
            ),
            self.engine,
            params={
                "d": str(racing_date)[:10],
                "c": str(course).upper(),
                "k": data_kind,
                "rid": race_id or "",
            },
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def _upsert_row(
        self,
        racing_date: str,
        course: str,
        data_kind: str,
        *,
        status: str,
        cov: Dict[str, Any],
        detail: str = "",
        next_attempt_at: Optional[datetime] = None,
        keep_next_if_set: bool = False,
        done: bool = False,
        expire: bool = False,
        last_error: Optional[str] = None,
        bump_attempt: bool = False,
        source_hint: str = "jjjc",
        race_id: Optional[str] = None,
    ) -> None:
        d, c = str(racing_date)[:10], str(course).upper()
        now = _utcnow_iso()
        existing = self.get_item(d, c, data_kind, race_id)
        attempt = int((existing or {}).get("attempt_count") or 0)
        if bump_attempt:
            attempt += 1

        next_iso: Optional[str]
        if next_attempt_at is not None:
            next_iso = next_attempt_at.isoformat()
        elif keep_next_if_set and existing and existing.get("next_attempt_at"):
            next_iso = str(existing.get("next_attempt_at"))
        elif status in (STATUS_OPEN, STATUS_RETRYING):
            next_iso = now
        else:
            next_iso = None

        first_seen = str((existing or {}).get("first_seen_at") or now)
        done_at = now if done else (existing or {}).get("done_at")
        expired_at = now if expire else (existing or {}).get("expired_at")
        last_attempt = (
            now
            if bump_attempt
            else (existing or {}).get("last_attempt_at")
        )
        err = last_error if last_error is not None else (existing or {}).get("last_error")

        rid = race_id  # meeting-level：NULL／空
        params = {
            "d": d,
            "c": c,
            "rid": rid,
            "k": data_kind,
            "st": status,
            "en": int(cov.get("expected_n") or 0),
            "cn": int(cov.get("covered_n") or 0),
            "cv": float(cov.get("coverage") or 0),
            "fs": first_seen,
            "la": last_attempt,
            "na": next_iso,
            "da": done_at,
            "ea": expired_at,
            "ac": attempt,
            "le": err,
            "de": detail,
            "sh": source_hint,
        }

        with self.engine.begin() as conn:
            if existing:
                conn.execute(
                    text(
                        """
                        UPDATE data_backlog SET
                          status = :st,
                          expected_n = :en,
                          covered_n = :cn,
                          coverage = :cv,
                          last_attempt_at = :la,
                          next_attempt_at = :na,
                          done_at = :da,
                          expired_at = :ea,
                          attempt_count = :ac,
                          last_error = :le,
                          detail = :de,
                          source_hint = :sh
                        WHERE id = :id
                        """
                    ),
                    {**params, "id": int(existing["id"])},
                )
            else:
                # UNIQUE (racing_date, course, data_kind, race_id) — race_id NULL 在 PG 可多筆；
                # 用空字串統一 meeting 粒度
                params["rid"] = rid or ""
                if self._sqlite:
                    conn.execute(
                        text(
                            """
                            INSERT INTO data_backlog
                              (racing_date, course, race_id, data_kind, status,
                               expected_n, covered_n, coverage,
                               first_seen_at, last_attempt_at, next_attempt_at,
                               done_at, expired_at, attempt_count, last_error, detail, source_hint)
                            VALUES
                              (:d, :c, :rid, :k, :st, :en, :cn, :cv,
                               :fs, :la, :na, :da, :ea, :ac, :le, :de, :sh)
                            ON CONFLICT(racing_date, course, data_kind, race_id) DO UPDATE SET
                              status=excluded.status,
                              expected_n=excluded.expected_n,
                              covered_n=excluded.covered_n,
                              coverage=excluded.coverage,
                              last_attempt_at=excluded.last_attempt_at,
                              next_attempt_at=excluded.next_attempt_at,
                              done_at=excluded.done_at,
                              expired_at=excluded.expired_at,
                              attempt_count=excluded.attempt_count,
                              last_error=excluded.last_error,
                              detail=excluded.detail,
                              source_hint=excluded.source_hint
                            """
                        ),
                        params,
                    )
                else:
                    conn.execute(
                        text(
                            """
                            INSERT INTO data_backlog
                              (racing_date, course, race_id, data_kind, status,
                               expected_n, covered_n, coverage,
                               first_seen_at, last_attempt_at, next_attempt_at,
                               done_at, expired_at, attempt_count, last_error, detail, source_hint)
                            VALUES
                              (CAST(:d AS DATE), :c, :rid, :k, :st, :en, :cn, :cv,
                               CAST(:fs AS TIMESTAMPTZ), CAST(:la AS TIMESTAMPTZ),
                               CAST(:na AS TIMESTAMPTZ), CAST(:da AS TIMESTAMPTZ),
                               CAST(:ea AS TIMESTAMPTZ), :ac, :le, :de, :sh)
                            ON CONFLICT (racing_date, course, data_kind, race_id) DO UPDATE SET
                              status=EXCLUDED.status,
                              expected_n=EXCLUDED.expected_n,
                              covered_n=EXCLUDED.covered_n,
                              coverage=EXCLUDED.coverage,
                              last_attempt_at=EXCLUDED.last_attempt_at,
                              next_attempt_at=EXCLUDED.next_attempt_at,
                              done_at=EXCLUDED.done_at,
                              expired_at=EXCLUDED.expired_at,
                              attempt_count=EXCLUDED.attempt_count,
                              last_error=EXCLUDED.last_error,
                              detail=EXCLUDED.detail,
                              source_hint=EXCLUDED.source_hint
                            """
                        ),
                        params,
                    )

    # ----- 查詢 -----
    def list_items(
        self,
        *,
        statuses: Optional[Sequence[str]] = None,
        racing_date: Optional[str] = None,
        course: Optional[str] = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        clauses = ["1=1"]
        params: Dict[str, Any] = {"lim": int(limit)}
        if statuses:
            ph = ", ".join([f":s{i}" for i in range(len(statuses))])
            clauses.append(f"status IN ({ph})")
            for i, s in enumerate(statuses):
                params[f"s{i}"] = s
        if racing_date:
            clauses.append("CAST(racing_date AS TEXT) LIKE :d")
            params["d"] = str(racing_date)[:10]
        if course:
            clauses.append("course = :c")
            params["c"] = str(course).upper()
        where = " AND ".join(clauses)
        try:
            return pd.read_sql(
                text(
                    f"""
                    SELECT * FROM data_backlog
                    WHERE {where}
                    ORDER BY
                      CASE status
                        WHEN 'open' THEN 0
                        WHEN 'retrying' THEN 1
                        WHEN 'expired' THEN 2
                        WHEN 'skipped_manual' THEN 3
                        ELSE 4
                      END,
                      racing_date DESC, course, data_kind
                    LIMIT :lim
                    """
                ),
                self.engine,
                params=params,
            )
        except Exception:
            return pd.DataFrame()

    def summary_counts(self) -> Dict[str, int]:
        try:
            df = pd.read_sql(
                text(
                    "SELECT status, COUNT(*) AS n FROM data_backlog GROUP BY status"
                ),
                self.engine,
            )
        except Exception:
            return {}
        return {str(r.status): int(r.n) for r in df.itertuples()}

    def list_due(
        self, *, now: Optional[datetime] = None, limit: int = DEFAULT_PROCESS_LIMIT
    ) -> pd.DataFrame:
        now = now or _utcnow()
        now_s = now.isoformat()
        return pd.read_sql(
            text(
                """
                SELECT * FROM data_backlog
                WHERE status IN ('open', 'retrying')
                  AND (next_attempt_at IS NULL OR CAST(next_attempt_at AS TEXT) <= :now)
                ORDER BY next_attempt_at ASC NULLS FIRST, racing_date ASC
                LIMIT :lim
                """
                if not self._sqlite
                else """
                SELECT * FROM data_backlog
                WHERE status IN ('open', 'retrying')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                ORDER BY CASE WHEN next_attempt_at IS NULL THEN 0 ELSE 1 END,
                         next_attempt_at ASC, racing_date ASC
                LIMIT :lim
                """
            ),
            self.engine,
            params={"now": now_s, "lim": int(limit)},
        )

    def mark_skipped(
        self, racing_date: str, course: str, data_kind: str, *, reason: str = "人工略過"
    ) -> None:
        cov = self.measure_comment_coverage(racing_date, course, data_kind)
        self._upsert_row(
            racing_date,
            course,
            data_kind,
            status=STATUS_SKIPPED,
            cov=cov,
            detail=reason,
            next_attempt_at=None,
        )

    def reopen(
        self, racing_date: str, course: str, data_kind: str
    ) -> None:
        cov = self.measure_comment_coverage(racing_date, course, data_kind)
        self._upsert_row(
            racing_date,
            course,
            data_kind,
            status=STATUS_OPEN,
            cov=cov,
            detail="人工重開",
            next_attempt_at=_utcnow(),
        )

    # ----- 候選賽日 -----
    def candidate_meetings(
        self, *, as_of: Optional[date] = None, retention_days: int = DEFAULT_RETENTION_DAYS
    ) -> List[Tuple[str, str]]:
        """保留窗內、歷史庫已有名次的 meeting（fixtures ∪ runners）。"""
        today = as_of or date.today()
        start = today - timedelta(days=max(0, int(retention_days)))
        meetings: Dict[Tuple[str, str], None] = {}

        # fixtures
        try:
            fx = pd.read_sql(
                text(
                    """
                    SELECT DISTINCT CAST(racing_date AS TEXT) AS racing_date, course
                    FROM fixtures
                    WHERE CAST(racing_date AS TEXT) >= :s
                      AND CAST(racing_date AS TEXT) <= :e
                    """
                ),
                self.engine,
                params={"s": start.isoformat(), "e": today.isoformat()},
            )
            for r in fx.itertuples():
                meetings[(str(r.racing_date)[:10], str(r.course).upper())] = None
        except Exception:
            pass

        # runners with finish
        try:
            # race_id 形如 20260906ST01 → 切日期／場地
            ru = pd.read_sql(
                text(
                    """
                    SELECT DISTINCT race_id FROM runners
                    WHERE finish_order_num IS NOT NULL
                    """
                ),
                self.engine,
            )
            for rid in ru["race_id"].astype(str):
                if len(rid) < 10:
                    continue
                ymd, course = rid[:8], rid[8:10]
                if course not in ("ST", "HV"):
                    continue
                d = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                try:
                    dd = date.fromisoformat(d)
                except ValueError:
                    continue
                if start <= dd <= today:
                    meetings[(d, course)] = None
        except Exception:
            pass

        # 既有 open backlog（即使超出 fixtures 掃描仍要續跑）
        try:
            open_df = self.list_items(
                statuses=[STATUS_OPEN, STATUS_RETRYING], limit=500
            )
            for r in open_df.itertuples():
                meetings[(str(r.racing_date)[:10], str(r.course).upper())] = None
        except Exception:
            pass

        return sorted(meetings.keys(), reverse=True)

    def refresh_open_coverage(
        self,
        *,
        statuses: Optional[Sequence[str]] = None,
        threshold: float = DEFAULT_COVERAGE_OK,
        reconcile: bool = True,
        limit: int = 300,
    ) -> Dict[str, Any]:
        """
        重算 open／retrying 列的覆蓋分母（拉 JJJC results 場次＋必要時 prune），
        不重拉 text-reports。給 UI「重新整理」用，避免畫面上仍顯示舊的 140。
        """
        want = list(statuses or (STATUS_OPEN, STATUS_RETRYING))
        df = self.list_items(statuses=want, limit=limit)
        if df is None or df.empty:
            return {"ok": True, "n_updated": 0, "meetings": 0}

        meetings = sorted(
            {
                (str(r.racing_date)[:10], str(r.course).upper())
                for r in df.itertuples()
            }
        )
        keep_by_meeting: Dict[Tuple[str, str], Optional[List[str]]] = {}
        recon_report = []
        for d, c in meetings:
            if reconcile:
                recon_report.append(
                    {"racing_date": d, "course": c, **self.reconcile_meeting_results(d, c)}
                )
            keep_by_meeting[(d, c)] = self._fetch_results_race_ids(d, c) or None

        updated = 0
        for r in df.itertuples():
            d = str(r.racing_date)[:10]
            c = str(r.course).upper()
            kind = str(r.data_kind)
            cov = self.measure_comment_coverage(
                d, c, kind, keep_race_ids=keep_by_meeting.get((d, c))
            )
            if not cov.get("ok"):
                continue
            status = str(r.status)
            if self.coverage_ok(cov, threshold=threshold):
                status = STATUS_DONE
            self._upsert_row(
                d,
                c,
                kind,
                status=status,
                cov=cov,
                detail=(
                    f"覆蓋達標 {_coverage_label(cov)}"
                    if status == STATUS_DONE
                    else f"覆蓋不足 {_coverage_label(cov)} ({float(cov.get('coverage') or 0):.0%})"
                ),
                done=(status == STATUS_DONE),
                keep_next_if_set=True,
            )
            updated += 1
        return {
            "ok": True,
            "n_updated": updated,
            "meetings": len(meetings),
            "reconcile": recon_report,
        }

    # ----- 處理 -----
    def process_item(
        self,
        row: Dict[str, Any],
        *,
        dry_run: bool = False,
        threshold: float = DEFAULT_COVERAGE_OK,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        as_of: Optional[date] = None,
    ) -> Dict[str, Any]:
        d = str(row.get("racing_date"))[:10]
        c = str(row.get("course") or "").upper()
        kind = str(row.get("data_kind") or KIND_RUNNING)
        today = as_of or date.today()
        try:
            age_days = float((today - date.fromisoformat(d)).days)
        except ValueError:
            age_days = 0.0

        result: Dict[str, Any] = {
            "racing_date": d,
            "course": c,
            "data_kind": kind,
            "dry_run": dry_run,
        }

        if age_days > retention_days:
            if not dry_run:
                cov = self.measure_comment_coverage(d, c, kind)
                self._upsert_row(
                    d,
                    c,
                    kind,
                    status=STATUS_EXPIRED,
                    cov=cov,
                    detail=f"超過保留窗 {retention_days} 日",
                    expire=True,
                    bump_attempt=True,
                )
            result.update({"ok": True, "action": "expired"})
            return result

        if dry_run:
            result.update({"ok": True, "action": "would_sync"})
            return result

        # 先對齊 results 並 prune 幽靈場，再量覆蓋／拉 text-reports
        reconcile = self.reconcile_meeting_results(d, c)
        result["results_reconcile"] = {
            k: reconcile.get(k)
            for k in (
                "ok",
                "race_count",
                "pruned_orphan_races",
                "pruned_runners",
                "error",
            )
        }
        keep_ids = None
        if reconcile.get("ok") and reconcile.get("race_count"):
            # sync 成功後再拉一次 export id（或用 DB canon）；measure 內會自行 export
            keep_ids = self._fetch_results_race_ids(d, c) or None

        # 拉取 text-reports（指定 report_type）
        sync_out: Dict[str, Any] = {}
        try:
            from jjjc_text_reports_sync import sync_meeting

            sync_out = sync_meeting(d, c, report_type=kind)
        except Exception as e:
            sync_out = {"ok": False, "error": str(e)}

        cov = self.measure_comment_coverage(
            d, c, kind, keep_race_ids=keep_ids
        )
        upserted = int(sync_out.get("runner_upserted") or 0)
        attempt = int(row.get("attempt_count") or 0) + 1
        delay = backoff_seconds(attempt, age_days)
        next_at = _utcnow() + timedelta(seconds=delay)

        if self.coverage_ok(cov, threshold=threshold):
            self._upsert_row(
                d,
                c,
                kind,
                status=STATUS_DONE,
                cov=cov,
                detail=f"覆蓋達標 {_coverage_label(cov)}",
                done=True,
                bump_attempt=True,
                last_error=None,
            )
            result.update(
                {
                    "ok": True,
                    "action": "done",
                    "new_upserts": upserted,
                    "coverage": cov,
                    "sync": {
                        k: sync_out.get(k)
                        for k in ("ok", "waiting", "phase", "runner_upserted", "error")
                        if k in sync_out
                    },
                }
            )
            return result

        err = None
        if not sync_out.get("ok"):
            err = str(sync_out.get("error") or "sync failed")
        elif sync_out.get("waiting"):
            err = str(sync_out.get("detail") or "export waiting")

        self._upsert_row(
            d,
            c,
            kind,
            status=STATUS_RETRYING,
            cov=cov,
            detail=f"覆蓋不足 {_coverage_label(cov)}；下次 {delay // 3600}h 後",
            next_attempt_at=next_at,
            bump_attempt=True,
            last_error=err,
        )
        result.update(
            {
                "ok": True,
                "action": "retry",
                "waiting": bool(sync_out.get("waiting")),
                "new_upserts": upserted,
                "coverage": cov,
                "next_attempt_at": next_at.isoformat(),
                "sync": {
                    k: sync_out.get(k)
                    for k in ("ok", "waiting", "phase", "runner_upserted", "error", "detail")
                    if k in sync_out
                },
            }
        )
        return result

    def maybe_run_nlp_pipeline(
        self, *, new_upserts: int, dry_run: bool = False
    ) -> Dict[str, Any]:
        """新評述入庫後：可選 NLP（再可選因子重算）。"""
        out: Dict[str, Any] = {"new_upserts": new_upserts, "nlp": None, "factors": None}
        if new_upserts <= 0:
            out["skipped"] = "no new upserts"
            return out
        if not AUTO_BACKLOG_NLP:
            out["skipped"] = "AUTO_BACKLOG_NLP disabled"
            return out
        if dry_run:
            out["nlp"] = {"dry_run": True}
            return out
        try:
            from factor_calculator import FactorCalculator
            from nlp_processor import NLPProcessor

            calc = FactorCalculator()
            nlp = NLPProcessor()
            if not nlp.is_ready():
                out["nlp"] = {"ok": False, "error": "OPENAI_API_KEY 未設定"}
                return out
            limit = min(50, max(new_upserts * 2, 10))
            rows = calc.load_unprocessed_reports(limit=limit, skip_trivial=True)
            done = 0
            errors = 0
            for r in rows:
                try:
                    parsed = nlp.analyze_report_sync(str(r.get("report_text") or ""))
                    calc.save_nlp_result(int(r["id"]), parsed)
                    done += 1
                except Exception:
                    errors += 1
            out["nlp"] = {"ok": True, "parsed": done, "errors": errors, "limit": limit}
            if AUTO_BACKLOG_FACTORS and done > 0:
                try:
                    fac = calc.run_all_factors()
                    out["factors"] = {"ok": True, "result": str(fac)[:200]}
                except Exception as e:
                    out["factors"] = {"ok": False, "error": str(e)}
        except Exception as e:
            out["nlp"] = {"ok": False, "error": str(e)}
        return out

    def run_tick_pass(
        self,
        *,
        as_of: Optional[date] = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        limit: int = DEFAULT_PROCESS_LIMIT,
        threshold: float = DEFAULT_COVERAGE_OK,
        dry_run: bool = False,
        force: bool = False,
        enroll_meetings: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        tick 一輪：入列掃描 → 處理到期項 →（可選）NLP。
        force：忽略 next_attempt_at，處理所有 open／retrying（仍受 limit）。
        """
        today = as_of or date.today()
        meetings = list(enroll_meetings) if enroll_meetings is not None else self.candidate_meetings(
            as_of=today, retention_days=retention_days
        )
        enroll_report: List[Dict[str, Any]] = []
        for d, c in meetings:
            enroll_report.extend(
                self.enroll_meeting(
                    d,
                    c,
                    as_of=today,
                    retention_days=retention_days,
                    threshold=threshold,
                )
            )

        if force:
            due = self.list_items(
                statuses=[STATUS_OPEN, STATUS_RETRYING], limit=limit
            )
        else:
            due = self.list_due(now=_utcnow(), limit=limit)

        processed: List[Dict[str, Any]] = []
        new_upserts = 0
        for row in due.to_dict(orient="records"):
            # enroll 剛標 done 的略過
            if str(row.get("status")) not in (STATUS_OPEN, STATUS_RETRYING):
                continue
            # 若 force 以外但剛 enroll 且覆蓋仍不足，list_due 會納入 next<=now
            pr = self.process_item(
                row,
                dry_run=dry_run,
                threshold=threshold,
                retention_days=retention_days,
                as_of=today,
            )
            processed.append(pr)
            new_upserts += int(pr.get("new_upserts") or 0)

        nlp_out = self.maybe_run_nlp_pipeline(
            new_upserts=new_upserts, dry_run=dry_run
        )
        counts = self.summary_counts()
        return {
            "ok": True,
            "as_of": today.isoformat(),
            "retention_days": retention_days,
            "n_meetings_scanned": len(meetings),
            "n_enroll_actions": len(enroll_report),
            "n_processed": len(processed),
            "new_upserts": new_upserts,
            "counts": counts,
            "enroll": enroll_report,
            "processed": processed,
            "nlp_pipeline": nlp_out,
            "dry_run": dry_run,
            "force": force,
        }


def build_arg_parser():
    import argparse

    p = argparse.ArgumentParser(description="Data backlog (delayed text reports)")
    p.add_argument("--list", action="store_true", help="列出 open／retrying")
    p.add_argument("--process", action="store_true", help="處理到期項")
    p.add_argument("--enroll-only", action="store_true", help="只掃描入列")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int, default=DEFAULT_PROCESS_LIMIT)
    p.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    p.add_argument("--date", dest="racing_date")
    p.add_argument("--course")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys

    args = build_arg_parser().parse_args(argv)
    svc = DataBacklogService()
    if args.list:
        df = svc.list_items(
            statuses=[STATUS_OPEN, STATUS_RETRYING, STATUS_EXPIRED],
            racing_date=args.racing_date,
            course=args.course,
        )
        if args.json:
            print(df.to_json(orient="records", force_ascii=False))
        else:
            print(df.to_string(index=False) if not df.empty else "(empty)")
        return 0

    enroll_meetings = None
    if args.racing_date:
        enroll_meetings = [
            (args.racing_date[:10], (args.course or "ST").upper())
        ]

    if args.enroll_only:
        meetings = enroll_meetings or svc.candidate_meetings(
            retention_days=args.retention_days
        )
        report = {"enroll": []}
        for d, c in meetings:
            report["enroll"].extend(
                svc.enroll_meeting(d, c, retention_days=args.retention_days)
            )
    else:
        report = svc.run_tick_pass(
            retention_days=args.retention_days,
            limit=args.limit,
            dry_run=bool(args.dry_run),
            force=bool(args.force),
            enroll_meetings=enroll_meetings,
        )

    text_out = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.json:
        print(text_out)
    else:
        print(text_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
