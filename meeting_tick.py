"""
賽日自動 tick（賽前 pre_race + 賽後 post_race）。

賽前硬依賴鏈（環環緊扣；缺上游則下游 skip_reasons 可監察）：
  RACECARD
    → SPEEDGUIDE ∥ FORMGUIDE（排位齊後可並行）
    → FACTORS（需排位；基礎因子可不待 NLP）
    → FORM_AI（硬閘：SPEEDGUIDE＋FORMGUIDE＋FACTORS 皆 ok）
    → SNAPSHOT（硬閘：SPEEDGUIDE＋FORMGUIDE＋FACTORS＋FORM_AI）
    → social_copy（需快照）

  NLP／沿路走勢：賽後／遺留鏈（評述→NLP→含干擾因子→revision），不擋賽前 Form AI／正式快照。

賽前動作：
  1) sync_jjjc_racecard
  2) crawl_speedguide／crawl_formguide（JJJC 主路徑，CMS 備援）
  3) run_factors（每輪最多一次）
  4) start_form_ai_background（僅上游齊備後）
  5) snapshot
  6) social_copy（MEETING_TICK_AUTO_SOCIAL_COPY）

賽後（lookback）：
  1) sync_jjjc_results
  2) sync_jjjc_text_reports
  3) settle_pending
  4) promo_hits → post_race_copy（SETTLED 後；可開關）
  5) data_backlog 掃遺留（保留窗內沿途評述等；見 data_backlog.py）

原則：
  - 短週期 Cron 呼叫本 CLI；勿塞進 Streamlit request
  - 依 readiness 重試；禁止無限狂爬（cooldown + max fails）
  - 人工略過／放行（manual_override）不覆蓋、不強跑
  - 同輪可樂觀排下游，但 execute 必須以 refresh 後真實 status 再開閘

用法：
  python meeting_tick.py --mode all --dry-run --json
  python meeting_tick.py --mode pre_race --lookahead-days 3
  python meeting_tick.py --mode post_race --lookback-days 3
  python meeting_tick.py --date 2026-09-13 --course ST --mode pre_race
  python meeting_tick.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import text

from etl_pipeline import USE_SQLITE
from meeting_pipeline import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PENDING,
    STATUS_SKIPPED,
    STATUS_WAITING,
    MeetingPipeline,
)

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

# ----- 預設護欄（可用 CLI／環境覆寫）-----
DEFAULT_LOOKBACK_DAYS = int(os.getenv("MEETING_TICK_LOOKBACK_DAYS", "3") or 3)
DEFAULT_LOOKAHEAD_DAYS = int(os.getenv("MEETING_TICK_LOOKAHEAD_DAYS", "3") or 3)
DEFAULT_BACKLOG_RETENTION_DAYS = int(
    os.getenv("MEETING_TICK_BACKLOG_RETENTION_DAYS", "14") or 14
)
DEFAULT_BACKLOG_LIMIT = int(os.getenv("MEETING_TICK_BACKLOG_LIMIT", "10") or 10)
AUTO_BACKLOG = (os.getenv("MEETING_TICK_AUTO_BACKLOG", "true") or "true").lower() in (
    "1",
    "true",
    "yes",
)
DEFAULT_COOLDOWN_WAITING_SEC = int(
    os.getenv("MEETING_TICK_COOLDOWN_WAITING_SEC", str(30 * 60)) or 30 * 60
)
DEFAULT_COOLDOWN_FAILED_SEC = int(
    os.getenv("MEETING_TICK_COOLDOWN_FAILED_SEC", str(60 * 60)) or 60 * 60
)
DEFAULT_MAX_FAILS = int(os.getenv("MEETING_TICK_MAX_FAILS", "5") or 5)
DEFAULT_TICK_MODE = (os.getenv("MEETING_TICK_MODE") or "all").strip().lower()

AUTO_FACTORS = (os.getenv("MEETING_TICK_AUTO_FACTORS", "true") or "true").lower() in (
    "1",
    "true",
    "yes",
)
AUTO_FORM_AI = (os.getenv("MEETING_TICK_AUTO_FORM_AI", "true") or "true").lower() in (
    "1",
    "true",
    "yes",
)
AUTO_SOCIAL_COPY = (
    os.getenv("MEETING_TICK_AUTO_SOCIAL_COPY", "true") or "true"
).lower() in (
    "1",
    "true",
    "yes",
)
AUTO_PROMO_HITS = (
    os.getenv("MEETING_TICK_AUTO_PROMO_HITS", "true") or "true"
).lower() in (
    "1",
    "true",
    "yes",
)
AUTO_POST_RACE_COPY = (
    os.getenv("MEETING_TICK_AUTO_POST_RACE_COPY", "true") or "true"
).lower() in (
    "1",
    "true",
    "yes",
)
AUTO_SNAPSHOT = (os.getenv("MEETING_TICK_AUTO_SNAPSHOT", "true") or "true").lower() in (
    "1",
    "true",
    "yes",
)

POST_RACE_MODE = "post_race"
PRE_RACE_MODE = "pre_race"
ALL_MODE = "all"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        # SQLite CURRENT_TIMESTAMP often "YYYY-MM-DD HH:MM:SS"
        if "T" not in s and " " in s:
            s = s.replace(" ", "T")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def stage_row_map(stages_df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if stages_df is None or stages_df.empty:
        return out
    for row in stages_df.to_dict(orient="records"):
        st = str(row.get("stage") or "")
        if st:
            out[st] = row
    return out


def is_manual_blocked(row: Optional[Dict[str, Any]]) -> bool:
    """人工略過，或人工放行且已標 ok — tick 不強跑動作。"""
    if not row:
        return False
    if not row.get("manual_override"):
        return False
    status = str(row.get("status") or "")
    return status in (STATUS_OK, STATUS_SKIPPED)


def cooldown_seconds_for(status: str, *, waiting_sec: int, failed_sec: int) -> int:
    if status == STATUS_WAITING:
        return waiting_sec
    if status == STATUS_FAILED:
        return failed_sec
    return waiting_sec


@dataclass
class TickGuards:
    cooldown_waiting_sec: int = DEFAULT_COOLDOWN_WAITING_SEC
    cooldown_failed_sec: int = DEFAULT_COOLDOWN_FAILED_SEC
    max_fails: int = DEFAULT_MAX_FAILS
    force: bool = False


@dataclass
class MeetingActionPlan:
    racing_date: str
    course: str
    sync_results: bool = False
    sync_text_reports: bool = False
    settle: bool = False
    promo_hits: bool = False
    post_race_copy: bool = False
    skip_reasons: List[str] = field(default_factory=list)
    readiness: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PreRaceActionPlan:
    racing_date: str
    course: str
    sync_racecard: bool = False
    pull_speedguide: bool = False
    pull_formguide: bool = False
    run_factors: bool = False
    start_form_ai: bool = False
    snapshot: bool = False
    social_copy: bool = False
    skip_reasons: List[str] = field(default_factory=list)
    readiness: Dict[str, Any] = field(default_factory=dict)


class MeetingTickRunner:
    """可單測的 tick 邏輯；真正 I/O 經 MeetingPipeline.run_action。"""

    def __init__(
        self,
        pipeline: Optional[MeetingPipeline] = None,
        *,
        guards: Optional[TickGuards] = None,
    ) -> None:
        self.pipe = pipeline or MeetingPipeline()
        self.guards = guards or TickGuards()
        self.ensure_tick_state_table()
        self._factors_ran = False

    def ensure_tick_state_table(self) -> None:
        if USE_SQLITE:
            ddl = """
            CREATE TABLE IF NOT EXISTS meeting_tick_state (
                racing_date TEXT NOT NULL,
                course TEXT NOT NULL,
                stage TEXT NOT NULL,
                fail_count INTEGER DEFAULT 0,
                last_attempt_at TEXT,
                last_ok_at TEXT,
                last_status TEXT,
                last_detail TEXT,
                PRIMARY KEY (racing_date, course, stage)
            )
            """
        else:
            ddl = """
            CREATE TABLE IF NOT EXISTS meeting_tick_state (
                racing_date DATE NOT NULL,
                course VARCHAR(10) NOT NULL,
                stage VARCHAR(40) NOT NULL,
                fail_count INT DEFAULT 0,
                last_attempt_at TIMESTAMPTZ,
                last_ok_at TIMESTAMPTZ,
                last_status VARCHAR(40),
                last_detail TEXT,
                PRIMARY KEY (racing_date, course, stage)
            )
            """
        with self.pipe.engine.begin() as conn:
            conn.execute(text(ddl))

    def get_tick_state(
        self, racing_date: str, course: str, stage: str
    ) -> Dict[str, Any]:
        df = pd.read_sql(
            text(
                "SELECT * FROM meeting_tick_state "
                "WHERE racing_date=:d AND course=:c AND stage=:s"
            ),
            self.pipe.engine,
            params={"d": racing_date[:10], "c": course, "s": stage},
        )
        if df.empty:
            return {
                "fail_count": 0,
                "last_attempt_at": None,
                "last_ok_at": None,
                "last_status": None,
                "last_detail": None,
            }
        return df.iloc[0].to_dict()

    def record_tick_attempt(
        self,
        racing_date: str,
        course: str,
        stage: str,
        *,
        ok: bool,
        status: str,
        detail: str = "",
    ) -> None:
        prev = self.get_tick_state(racing_date, course, stage)
        fail_count = 0 if ok else int(prev.get("fail_count") or 0) + 1
        now = _utcnow().isoformat()
        last_ok = now if ok else prev.get("last_ok_at")
        with self.pipe.engine.begin() as conn:
            if USE_SQLITE:
                conn.execute(
                    text(
                        """
                        INSERT INTO meeting_tick_state
                        (racing_date, course, stage, fail_count, last_attempt_at,
                         last_ok_at, last_status, last_detail)
                        VALUES (:d, :c, :s, :fc, :la, :lo, :st, :de)
                        ON CONFLICT (racing_date, course, stage) DO UPDATE SET
                          fail_count=excluded.fail_count,
                          last_attempt_at=excluded.last_attempt_at,
                          last_ok_at=excluded.last_ok_at,
                          last_status=excluded.last_status,
                          last_detail=excluded.last_detail
                        """
                    ),
                    {
                        "d": racing_date[:10],
                        "c": course,
                        "s": stage,
                        "fc": fail_count,
                        "la": now,
                        "lo": last_ok,
                        "st": status,
                        "de": (detail or "")[:2000],
                    },
                )
            else:
                conn.execute(
                    text(
                        """
                        INSERT INTO meeting_tick_state
                        (racing_date, course, stage, fail_count, last_attempt_at,
                         last_ok_at, last_status, last_detail)
                        VALUES (:d, :c, :s, :fc, CAST(:la AS TIMESTAMPTZ),
                                CAST(:lo AS TIMESTAMPTZ), :st, :de)
                        ON CONFLICT (racing_date, course, stage) DO UPDATE SET
                          fail_count=EXCLUDED.fail_count,
                          last_attempt_at=EXCLUDED.last_attempt_at,
                          last_ok_at=EXCLUDED.last_ok_at,
                          last_status=EXCLUDED.last_status,
                          last_detail=EXCLUDED.last_detail
                        """
                    ),
                    {
                        "d": racing_date[:10],
                        "c": course,
                        "s": stage,
                        "fc": fail_count,
                        "la": now,
                        "lo": last_ok if last_ok else None,
                        "st": status,
                        "de": (detail or "")[:2000],
                    },
                )

    def list_meetings_in_range(
        self, start: date, end: date
    ) -> List[Tuple[str, str]]:
        """fixtures ∪ 未結算快照批次（日期區間）。"""
        start_s, end_s = start.isoformat(), end.isoformat()
        found: Dict[Tuple[str, str], None] = {}

        try:
            fx = pd.read_sql(
                text(
                    """
                    SELECT racing_date, course FROM fixtures
                    WHERE CAST(racing_date AS TEXT) >= :a
                      AND CAST(racing_date AS TEXT) <= :b
                    """
                    if USE_SQLITE
                    else """
                    SELECT racing_date, course FROM fixtures
                    WHERE racing_date >= CAST(:a AS DATE)
                      AND racing_date <= CAST(:b AS DATE)
                    """
                ),
                self.pipe.engine,
                params={"a": start_s, "b": end_s},
            )
            for r in fx.itertuples():
                found[(str(r.racing_date)[:10], str(r.course).upper())] = None
        except Exception:
            pass

        try:
            snaps = pd.read_sql(
                text(
                    """
                    SELECT DISTINCT racing_date, course
                    FROM prediction_snapshot_batches
                    WHERE settled_at IS NULL
                      AND CAST(racing_date AS TEXT) >= :a
                      AND CAST(racing_date AS TEXT) <= :b
                    """
                    if USE_SQLITE
                    else """
                    SELECT DISTINCT racing_date, course
                    FROM prediction_snapshot_batches
                    WHERE settled_at IS NULL
                      AND racing_date >= CAST(:a AS DATE)
                      AND racing_date <= CAST(:b AS DATE)
                    """
                ),
                self.pipe.engine,
                params={"a": start_s, "b": end_s},
            )
            for r in snaps.itertuples():
                found[(str(r.racing_date)[:10], str(r.course).upper())] = None
        except Exception:
            pass

        return sorted(found.keys())

    def list_upcoming_meetings(
        self, start: date, end: date
    ) -> List[Tuple[str, str]]:
        """fixtures 賽日前瞻區間（含當日）。"""
        start_s, end_s = start.isoformat(), end.isoformat()
        found: Dict[Tuple[str, str], None] = {}
        try:
            fx = pd.read_sql(
                text(
                    """
                    SELECT DISTINCT racing_date, course
                    FROM fixtures
                    WHERE CAST(racing_date AS TEXT) >= :a
                      AND CAST(racing_date AS TEXT) <= :b
                    """
                    if USE_SQLITE
                    else """
                    SELECT DISTINCT racing_date, course
                    FROM fixtures
                    WHERE racing_date >= CAST(:a AS DATE)
                      AND racing_date <= CAST(:b AS DATE)
                    """
                ),
                self.pipe.engine,
                params={"a": start_s, "b": end_s},
            )
            for r in fx.itertuples():
                found[(str(r.racing_date)[:10], str(r.course).upper())] = None
        except Exception:
            pass
        return sorted(found.keys())

    def _attempt_allowed(
        self,
        racing_date: str,
        course: str,
        stage: str,
        stage_status: str,
        *,
        now: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        g = self.guards
        if g.force:
            return True, "force"

        state = self.get_tick_state(racing_date, course, stage)
        fail_count = int(state.get("fail_count") or 0)
        if fail_count >= g.max_fails and stage_status == STATUS_FAILED:
            return False, f"fail_count={fail_count}>={g.max_fails}"

        last = _parse_ts(state.get("last_attempt_at"))
        if last is None:
            return True, "no_prior_attempt"

        now = now or _utcnow()
        cd = cooldown_seconds_for(
            stage_status,
            waiting_sec=g.cooldown_waiting_sec,
            failed_sec=g.cooldown_failed_sec,
        )
        # pending／ok 不需要長冷卻；但若剛嘗試過仍給最短 60s 防狂打
        if stage_status in (STATUS_PENDING, STATUS_OK):
            cd = min(cd, 60)
        elapsed = (now - last).total_seconds()
        if elapsed < cd:
            return False, f"cooldown {int(cd - elapsed)}s left (status={stage_status})"
        return True, "cooldown_ok"

    @staticmethod
    def _stage_status(readiness: Dict[str, Any], stage: str) -> str:
        return str((readiness.get(stage) or {}).get("status") or STATUS_PENDING)

    # 正式快照硬閘（順序即依賴說明；NLP 刻意不在此列）
    FORMAL_SNAPSHOT_GATES: Tuple[str, ...] = (
        "SPEEDGUIDE",
        "FORMGUIDE",
        "FACTORS",
        "FORM_AI",
    )
    # Form AI 啟動硬閘（不含自身）
    FORM_AI_PREREQ_GATES: Tuple[str, ...] = (
        "SPEEDGUIDE",
        "FORMGUIDE",
        "FACTORS",
    )

    @staticmethod
    def _gates_ok(
        readiness: Dict[str, Any], stages: Sequence[str]
    ) -> Tuple[bool, List[str]]:
        missing: List[str] = []
        for st in stages:
            if MeetingTickRunner._stage_status(readiness, st) != STATUS_OK:
                missing.append(st)
        return (len(missing) == 0, missing)

    @classmethod
    def _gates_for_formal_snapshot(
        cls, readiness: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """正式快照硬閘：SG + FormGuide + Factors + Form AI 皆 ok。"""
        return cls._gates_ok(readiness, cls.FORMAL_SNAPSHOT_GATES)

    @classmethod
    def _gates_for_form_ai(
        cls, readiness: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """Form AI 啟動硬閘：SG + FormGuide + Factors 皆 ok。"""
        return cls._gates_ok(readiness, cls.FORM_AI_PREREQ_GATES)

    def plan_pre_race_meeting(
        self,
        racing_date: str,
        course: str,
        *,
        readiness: Optional[Dict[str, Any]] = None,
        stages_df: Optional[pd.DataFrame] = None,
        now: Optional[datetime] = None,
        auto_factors: bool = AUTO_FACTORS,
        auto_form_ai: bool = AUTO_FORM_AI,
        auto_snapshot: bool = AUTO_SNAPSHOT,
        auto_social_copy: bool = AUTO_SOCIAL_COPY,
    ) -> PreRaceActionPlan:
        """純決策：賽前要不要拉排位／SG／FG／因子／Form AI／快照。"""
        d, c = racing_date[:10], course.upper()
        plan = PreRaceActionPlan(racing_date=d, course=c)
        readiness = readiness or self.pipe.refresh_readiness(d, c)
        plan.readiness = readiness
        stages = stage_row_map(
            stages_df if stages_df is not None else self.pipe.get_stages(d, c)
        )
        now = now or _utcnow()

        rc = self._stage_status(readiness, "RACECARD")
        sg = self._stage_status(readiness, "SPEEDGUIDE")
        fg = self._stage_status(readiness, "FORMGUIDE")
        fac = self._stage_status(readiness, "FACTORS")
        ai = self._stage_status(readiness, "FORM_AI")
        snap = self._stage_status(readiness, "SNAPSHOT")

        # --- RACECARD ---
        if is_manual_blocked(stages.get("RACECARD")):
            plan.skip_reasons.append("RACECARD manual block")
        elif rc == STATUS_OK:
            plan.skip_reasons.append("RACECARD already ok")
        else:
            allowed, why = self._attempt_allowed(d, c, "RACECARD", rc, now=now)
            if not allowed:
                plan.skip_reasons.append(f"RACECARD skip: {why}")
            else:
                plan.sync_racecard = True

        racecard_ready_soon = rc == STATUS_OK or plan.sync_racecard

        # --- SPEEDGUIDE ---
        if is_manual_blocked(stages.get("SPEEDGUIDE")):
            plan.skip_reasons.append("SPEEDGUIDE manual block")
        elif not racecard_ready_soon:
            plan.skip_reasons.append("SPEEDGUIDE wait: RACECARD not ready")
        elif sg == STATUS_OK:
            plan.skip_reasons.append("SPEEDGUIDE already ok")
        else:
            allowed, why = self._attempt_allowed(d, c, "SPEEDGUIDE", sg, now=now)
            if not allowed:
                plan.skip_reasons.append(f"SPEEDGUIDE skip: {why}")
            else:
                plan.pull_speedguide = True

        # --- FORMGUIDE ---
        if is_manual_blocked(stages.get("FORMGUIDE")):
            plan.skip_reasons.append("FORMGUIDE manual block")
        elif not racecard_ready_soon:
            plan.skip_reasons.append("FORMGUIDE wait: RACECARD not ready")
        elif fg == STATUS_OK:
            plan.skip_reasons.append("FORMGUIDE already ok")
        else:
            allowed, why = self._attempt_allowed(d, c, "FORMGUIDE", fg, now=now)
            if not allowed:
                plan.skip_reasons.append(f"FORMGUIDE skip: {why}")
            else:
                plan.pull_formguide = True

        speedguide_ready_soon = sg == STATUS_OK or plan.pull_speedguide
        formguide_ready_soon = fg == STATUS_OK or plan.pull_formguide

        # --- FACTORS（需排位；可不待 SG／FG／NLP）---
        if not auto_factors:
            plan.skip_reasons.append("FACTORS disabled by env")
        elif is_manual_blocked(stages.get("FACTORS")):
            plan.skip_reasons.append("FACTORS manual block")
        elif not racecard_ready_soon:
            plan.skip_reasons.append("FACTORS wait: RACECARD not ready")
        elif fac == STATUS_OK:
            plan.skip_reasons.append("FACTORS already ok")
        else:
            allowed, why = self._attempt_allowed(d, c, "FACTORS", fac, now=now)
            if not allowed:
                plan.skip_reasons.append(f"FACTORS skip: {why}")
            else:
                plan.run_factors = True

        factors_ready_soon = fac == STATUS_OK or plan.run_factors

        # --- FORM_AI（硬閘：SG＋FG＋FACTORS；同輪可樂觀排，execute 再驗真實 status）---
        if not auto_form_ai:
            plan.skip_reasons.append("FORM_AI disabled by env")
        elif is_manual_blocked(stages.get("FORM_AI")):
            plan.skip_reasons.append("FORM_AI manual block")
        elif not racecard_ready_soon:
            plan.skip_reasons.append("FORM_AI wait: RACECARD not ready")
        elif not speedguide_ready_soon:
            plan.skip_reasons.append("FORM_AI wait: SPEEDGUIDE not ready")
        elif not formguide_ready_soon:
            plan.skip_reasons.append("FORM_AI wait: FORMGUIDE not ready")
        elif not factors_ready_soon:
            plan.skip_reasons.append("FORM_AI wait: FACTORS not ready")
        elif ai == STATUS_OK:
            plan.skip_reasons.append("FORM_AI already ok")
        else:
            # 計劃層：上游已 ok 或本輪將嘗試；缺料時 execute 會 skip
            allowed, why = self._attempt_allowed(d, c, "FORM_AI", ai, now=now)
            if not allowed:
                plan.skip_reasons.append(f"FORM_AI skip: {why}")
            else:
                plan.start_form_ai = True
                if sg != STATUS_OK or fg != STATUS_OK or fac != STATUS_OK:
                    pending = [
                        st
                        for st, st_ok in (
                            ("SPEEDGUIDE", sg == STATUS_OK),
                            ("FORMGUIDE", fg == STATUS_OK),
                            ("FACTORS", fac == STATUS_OK),
                        )
                        if not st_ok
                    ]
                    plan.skip_reasons.append(
                        "FORM_AI deferred_until_execute: waiting "
                        + ",".join(pending)
                    )

        # --- SNAPSHOT（硬閘：SG+FG+FACTORS+FORM_AI）---
        gates_ok, missing = self._gates_for_formal_snapshot(readiness)
        if not auto_snapshot:
            plan.skip_reasons.append("SNAPSHOT disabled by env")
        elif is_manual_blocked(stages.get("SNAPSHOT")):
            plan.skip_reasons.append("SNAPSHOT manual block")
        elif snap == STATUS_OK:
            plan.skip_reasons.append("SNAPSHOT already ok")
        elif not gates_ok:
            plan.skip_reasons.append(
                "SNAPSHOT wait: gates " + ",".join(missing)
            )
        else:
            allowed, why = self._attempt_allowed(d, c, "SNAPSHOT", snap, now=now)
            if not allowed:
                plan.skip_reasons.append(f"SNAPSHOT skip: {why}")
            else:
                plan.snapshot = True

        # --- SOCIAL_COPY（快照後附屬；不擋主鏈）---
        snapshot_ready_soon = snap == STATUS_OK or plan.snapshot
        if not auto_social_copy:
            plan.skip_reasons.append("SOCIAL_COPY disabled by env")
        elif not snapshot_ready_soon:
            plan.skip_reasons.append("SOCIAL_COPY wait: SNAPSHOT not ready")
        else:
            already = False
            try:
                from ad_copy_jobs import job_done_for_batch, resolve_meeting_batch_id
                from ad_poster import default_output_dir

                bid = resolve_meeting_batch_id(d, c) or ""
                if (
                    bid
                    and not self.guards.force
                    and job_done_for_batch(default_output_dir(), d, c, "social", bid)
                ):
                    already = True
            except Exception:
                already = False
            if already:
                plan.skip_reasons.append("SOCIAL_COPY already archived")
            else:
                # 用 tick_state 冷卻（waiting／failed）
                st_row = self.get_tick_state(d, c, "SOCIAL_COPY")
                last_st = str((st_row or {}).get("last_status") or STATUS_PENDING)
                allowed, why = self._attempt_allowed(d, c, "SOCIAL_COPY", last_st, now=now)
                if not allowed:
                    plan.skip_reasons.append(f"SOCIAL_COPY skip: {why}")
                else:
                    plan.social_copy = True

        return plan

    def _record_pull_attempt(
        self,
        d: str,
        c: str,
        stage: str,
        result: Dict[str, Any],
        *,
        waiting_hints: Sequence[str] = (),
    ) -> Tuple[bool, str]:
        """依 run_action 結果寫 tick_state；回傳 (ok_for_cron, status)。"""
        ok = bool(result.get("ok"))
        waiting = bool(result.get("waiting"))
        err = str(result.get("error") or "")
        detail = str(
            result.get("detail")
            or result.get("msg")
            or result.get("message")
            or err
            or ""
        )
        if ok and waiting:
            status = STATUS_WAITING
            count_as_success = True
        elif ok:
            status = STATUS_OK
            count_as_success = True
        elif any(h in err for h in waiting_hints) or "empty" in err.lower():
            status = STATUS_WAITING
            count_as_success = True
        else:
            status = STATUS_FAILED
            count_as_success = False
        self.record_tick_attempt(
            d, c, stage, ok=count_as_success, status=status, detail=detail or err
        )
        return ok, status

    def execute_pre_race_meeting(
        self, plan: PreRaceActionPlan, *, dry_run: bool = False
    ) -> Dict[str, Any]:
        d, c = plan.racing_date, plan.course
        out: Dict[str, Any] = {
            "racing_date": d,
            "course": c,
            "dry_run": dry_run,
            "plan": {
                "sync_racecard": plan.sync_racecard,
                "pull_speedguide": plan.pull_speedguide,
                "pull_formguide": plan.pull_formguide,
                "run_factors": plan.run_factors,
                "start_form_ai": plan.start_form_ai,
                "snapshot": plan.snapshot,
                "social_copy": plan.social_copy,
                "skip_reasons": list(plan.skip_reasons),
            },
            "actions": [],
        }

        def _act(name: str, **kwargs: Any) -> Dict[str, Any]:
            rec: Dict[str, Any] = {"action": name}
            if dry_run:
                rec["ok"] = True
                rec["dry_run"] = True
                out["actions"].append(rec)
                return rec
            result = self.pipe.run_action(d, c, name, **kwargs)
            rec["ok"] = bool(result.get("ok"))
            rec["result"] = result
            out["actions"].append(rec)
            return rec

        if plan.sync_racecard:
            rec = _act("sync_jjjc_racecard")
            if not dry_run:
                self._record_pull_attempt(
                    d,
                    c,
                    "RACECARD",
                    rec.get("result") or {},
                    waiting_hints=("無排位", "尚未", "empty", "404"),
                )
                out["readiness_after_racecard"] = self.pipe.refresh_readiness(d, c)

        # 本輪拉完排位後才有意義；若計劃拉但失敗，下游仍可能 skip
        ready_now = (
            out.get("readiness_after_racecard")
            or plan.readiness
            or self.pipe.refresh_readiness(d, c)
        )
        racecard_ok = self._stage_status(ready_now, "RACECARD") == STATUS_OK

        if plan.pull_speedguide:
            if not racecard_ok and not dry_run:
                out["actions"].append(
                    {
                        "action": "crawl_speedguide",
                        "ok": False,
                        "skipped": True,
                        "reason": "RACECARD not ok",
                    }
                )
            else:
                rec = _act("crawl_speedguide")
                if not dry_run:
                    res = rec.get("result") or {}
                    # CMS 備援成功亦算 ok
                    if res.get("source") == "hkjc_cms_fallback" and res.get("ok"):
                        res = {**res, "waiting": False}
                    self._record_pull_attempt(
                        d,
                        c,
                        "SPEEDGUIDE",
                        res,
                        waiting_hints=("尚未", "waiting", "404", "No route"),
                    )
                    out["readiness_after_speedguide"] = self.pipe.refresh_readiness(d, c)

        if plan.pull_formguide:
            if not racecard_ok and not dry_run:
                out["actions"].append(
                    {
                        "action": "crawl_formguide",
                        "ok": False,
                        "skipped": True,
                        "reason": "RACECARD not ok",
                    }
                )
            else:
                rec = _act("crawl_formguide")
                if not dry_run:
                    res = rec.get("result") or {}
                    if res.get("source") == "hkjc_cms_fallback" and res.get("ok"):
                        res = {**res, "waiting": False}
                    self._record_pull_attempt(
                        d,
                        c,
                        "FORMGUIDE",
                        res,
                        waiting_hints=("尚未", "waiting", "404", "No route"),
                    )
                    out["readiness_after_formguide"] = self.pipe.refresh_readiness(d, c)

        if plan.run_factors:
            if self._factors_ran and not dry_run:
                out["actions"].append(
                    {
                        "action": "run_factors",
                        "ok": True,
                        "skipped": True,
                        "reason": "already ran this tick",
                    }
                )
            else:
                rec = _act("run_factors")
                if not dry_run:
                    res = rec.get("result") or {}
                    self._record_pull_attempt(d, c, "FACTORS", res)
                    if rec.get("ok"):
                        self._factors_ran = True
                    out["readiness_after_factors"] = self.pipe.refresh_readiness(d, c)

        if plan.start_form_ai:
            if not dry_run:
                # 同輪拉完 SG／FG／factors 後再驗硬閘（計劃層可樂觀，執行層必須真實 ok）
                ready_for_ai = self.pipe.refresh_readiness(d, c)
                out["readiness_before_form_ai"] = ready_for_ai
                racecard_ok = self._stage_status(ready_for_ai, "RACECARD") == STATUS_OK
                ai_gates_ok, ai_missing = self._gates_for_form_ai(ready_for_ai)
            else:
                ai_gates_ok, ai_missing = True, []

            if not racecard_ok and not dry_run:
                out["actions"].append(
                    {
                        "action": "start_form_ai_background",
                        "ok": False,
                        "skipped": True,
                        "reason": "RACECARD not ok",
                    }
                )
            elif not ai_gates_ok and not dry_run:
                out["actions"].append(
                    {
                        "action": "start_form_ai_background",
                        "ok": False,
                        "skipped": True,
                        "reason": "gates " + ",".join(ai_missing),
                    }
                )
                self.record_tick_attempt(
                    d,
                    c,
                    "FORM_AI",
                    ok=True,
                    status=STATUS_WAITING,
                    detail="wait gates " + ",".join(ai_missing),
                )
            else:
                rec = _act("start_form_ai_background")
                if not dry_run:
                    res = dict(rec.get("result") or {})
                    err = str(res.get("error") or "")
                    if "進行中" in err:
                        res["ok"] = True
                        res["waiting"] = True
                        res["detail"] = err
                    elif not res.get("ok") and "OPENAI" in err.upper():
                        res["waiting"] = False
                    self._record_pull_attempt(
                        d,
                        c,
                        "FORM_AI",
                        res,
                        waiting_hints=("進行中", "尚未"),
                    )
                    out["readiness_after_form_ai"] = self.pipe.refresh_readiness(d, c)

        # 正式快照：計劃已開，或本輪補齊閘門後 opportunistically
        if not dry_run:
            ready_final = self.pipe.refresh_readiness(d, c)
            out["readiness_final"] = ready_final
            gates_ok, missing = self._gates_for_formal_snapshot(ready_final)
            snap_st = self._stage_status(ready_final, "SNAPSHOT")
            want_snap = plan.snapshot or (
                AUTO_SNAPSHOT
                and gates_ok
                and snap_st != STATUS_OK
                and not is_manual_blocked(
                    stage_row_map(self.pipe.get_stages(d, c)).get("SNAPSHOT")
                )
            )
            if want_snap and gates_ok and snap_st != STATUS_OK:
                allowed, why = self._attempt_allowed(d, c, "SNAPSHOT", snap_st)
                if allowed:
                    rec = _act("snapshot")
                    res = rec.get("result") or {}
                    # FactorCalibration 可能回 batch_id 而無 ok
                    if res.get("batch_id") and res.get("ok") is None:
                        res = {**res, "ok": True}
                    self._record_pull_attempt(d, c, "SNAPSHOT", res)
                    out["readiness_after_snapshot"] = self.pipe.refresh_readiness(d, c)
                else:
                    out["actions"].append(
                        {
                            "action": "snapshot",
                            "ok": False,
                            "skipped": True,
                            "reason": why,
                        }
                    )
            elif want_snap and not gates_ok:
                out["actions"].append(
                    {
                        "action": "snapshot",
                        "ok": False,
                        "skipped": True,
                        "reason": "gates " + ",".join(missing),
                    }
                )
        elif plan.snapshot:
            _act("snapshot")

        # --- SOCIAL_COPY：本輪快照成功，或快照已 ok 且計劃要跑 ---
        want_social = plan.social_copy
        if not dry_run and AUTO_SOCIAL_COPY and not want_social:
            # opportunistic：剛建完快照
            snap_actions = [
                a
                for a in out["actions"]
                if a.get("action") == "snapshot" and a.get("ok") and not a.get("skipped")
            ]
            if snap_actions:
                want_social = True
        if want_social:
            action_rec: Dict[str, Any] = {"action": "social_copy"}
            if dry_run:
                action_rec["ok"] = True
                action_rec["dry_run"] = True
                out["actions"].append(action_rec)
            else:
                try:
                    from ad_copy_jobs import run_auto_social_copy

                    batch_id = None
                    for a in reversed(out["actions"]):
                        if a.get("action") == "snapshot":
                            res = a.get("result") or {}
                            batch_id = res.get("batch_id")
                            break
                    result = run_auto_social_copy(
                        racing_date=d,
                        course=c,
                        batch_id=batch_id,
                        force=self.guards.force,
                    )
                    action_rec["ok"] = bool(result.get("ok"))
                    action_rec["result"] = {
                        k: result.get(k)
                        for k in (
                            "ok",
                            "skipped",
                            "waiting",
                            "error",
                            "reason",
                            "batch_id",
                            "source",
                            "n_featured",
                            "social_copy",
                            "archive",
                        )
                        if k in result
                    } or result
                    self._record_pull_attempt(
                        d,
                        c,
                        "SOCIAL_COPY",
                        result,
                        waiting_hints=("copy.json", "尚未", "waiting", "≠"),
                    )
                except Exception as e:
                    action_rec["ok"] = False
                    action_rec["result"] = {"ok": False, "error": str(e)}
                    self.record_tick_attempt(
                        d, c, "SOCIAL_COPY", ok=False, status=STATUS_FAILED, detail=str(e)
                    )
                out["actions"].append(action_rec)

        if not out["actions"]:
            out["noop"] = True
        return out

    def run_pre_race(
        self,
        *,
        lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
        racing_date: Optional[str] = None,
        course: Optional[str] = None,
        dry_run: bool = False,
        as_of: Optional[date] = None,
    ) -> Dict[str, Any]:
        today = as_of or date.today()
        if racing_date:
            meetings = [(racing_date[:10], (course or "ST").upper())]
            if course is None:
                start = date.fromisoformat(racing_date[:10])
                meetings = [
                    m for m in self.list_upcoming_meetings(start, start)
                ] or meetings
        else:
            end = today + timedelta(days=max(0, int(lookahead_days)))
            meetings = self.list_upcoming_meetings(today, end)

        report: Dict[str, Any] = {
            "mode": PRE_RACE_MODE,
            "dry_run": dry_run,
            "as_of": today.isoformat(),
            "lookahead_days": lookahead_days,
            "guards": {
                "cooldown_waiting_sec": self.guards.cooldown_waiting_sec,
                "cooldown_failed_sec": self.guards.cooldown_failed_sec,
                "max_fails": self.guards.max_fails,
                "force": self.guards.force,
            },
            "flags": {
                "auto_factors": AUTO_FACTORS,
                "auto_form_ai": AUTO_FORM_AI,
                "auto_snapshot": AUTO_SNAPSHOT,
            },
            "meetings": [],
            "n_meetings": 0,
            "n_actions": 0,
        }

        for d, c in meetings:
            plan = self.plan_pre_race_meeting(d, c)
            meeting_out = self.execute_pre_race_meeting(plan, dry_run=dry_run)
            report["meetings"].append(meeting_out)
            report["n_actions"] += len(meeting_out.get("actions") or [])

        if not dry_run:
            report["incidents"] = self.scan_ops_incidents(report)
            report["n_actions"] += int(
                (report.get("incidents") or {}).get("n_created") or 0
            )

        report["n_meetings"] = len(report["meetings"])
        return report

    def run_all(
        self,
        *,
        lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        racing_date: Optional[str] = None,
        course: Optional[str] = None,
        dry_run: bool = False,
        as_of: Optional[date] = None,
    ) -> Dict[str, Any]:
        pre = self.run_pre_race(
            lookahead_days=lookahead_days,
            racing_date=racing_date,
            course=course,
            dry_run=dry_run,
            as_of=as_of,
        )
        post = self.run_post_race(
            lookback_days=lookback_days,
            racing_date=racing_date,
            course=course,
            dry_run=dry_run,
            as_of=as_of,
        )
        return {
            "mode": ALL_MODE,
            "dry_run": dry_run,
            "pre_race": pre,
            "post_race": post,
            "n_meetings": int(pre.get("n_meetings") or 0)
            + int(post.get("n_meetings") or 0),
            "n_actions": int(pre.get("n_actions") or 0)
            + int(post.get("n_actions") or 0)
            + (1 if post.get("settle") else 0),
        }

    def plan_post_race_meeting(
        self,
        racing_date: str,
        course: str,
        *,
        readiness: Optional[Dict[str, Any]] = None,
        stages_df: Optional[pd.DataFrame] = None,
        now: Optional[datetime] = None,
    ) -> MeetingActionPlan:
        """純決策：要不要 sync results／text-reports／settle（不執行）。"""
        d, c = racing_date[:10], course.upper()
        plan = MeetingActionPlan(racing_date=d, course=c)
        readiness = readiness or self.pipe.refresh_readiness(d, c)
        plan.readiness = readiness
        stages = stage_row_map(stages_df if stages_df is not None else self.pipe.get_stages(d, c))

        results_st = str((readiness.get("RESULTS") or {}).get("status") or STATUS_PENDING)
        settled_st = str((readiness.get("SETTLED") or {}).get("status") or STATUS_PENDING)
        snapshot_st = str((readiness.get("SNAPSHOT") or {}).get("status") or STATUS_PENDING)
        nlp_st = str((readiness.get("NLP") or {}).get("status") or STATUS_PENDING)

        # --- RESULTS ---
        if is_manual_blocked(stages.get("RESULTS")):
            plan.skip_reasons.append("RESULTS manual block")
        elif results_st == STATUS_OK:
            plan.skip_reasons.append("RESULTS already ok")
        else:
            allowed, why = self._attempt_allowed(d, c, "RESULTS", results_st, now=now)
            if not allowed:
                plan.skip_reasons.append(f"RESULTS skip: {why}")
            else:
                plan.sync_results = True

        # --- TEXT REPORTS（沿途／事故；賽後分批補齊，RESULTS 有貨或本輪會 sync 才探）---
        if is_manual_blocked(stages.get("NLP")):
            plan.skip_reasons.append("TEXT_REPORTS manual block (NLP)")
        elif results_st != STATUS_OK and not plan.sync_results:
            plan.skip_reasons.append("TEXT_REPORTS wait: RESULTS not ready")
        else:
            # 用 waiting 冷卻：評述常分場補齊，允許週期重探
            probe_st = STATUS_WAITING if nlp_st == STATUS_OK else nlp_st or STATUS_WAITING
            allowed, why = self._attempt_allowed(d, c, "TEXT_REPORTS", probe_st, now=now)
            if not allowed:
                plan.skip_reasons.append(f"TEXT_REPORTS skip: {why}")
            else:
                plan.sync_text_reports = True

        # --- SETTLED ---
        if is_manual_blocked(stages.get("SETTLED")):
            plan.skip_reasons.append("SETTLED manual block")
        elif settled_st == STATUS_OK:
            plan.skip_reasons.append("SETTLED already ok")
        elif snapshot_st != STATUS_OK:
            plan.skip_reasons.append("SETTLED wait: SNAPSHOT not ok")
        elif results_st != STATUS_OK and not plan.sync_results:
            # 無名次且本輪也不會去同步 → 結算無意義
            plan.skip_reasons.append("SETTLED wait: RESULTS not ok")
        else:
            allowed, why = self._attempt_allowed(d, c, "SETTLED", settled_st, now=now)
            if not allowed:
                plan.skip_reasons.append(f"SETTLED skip: {why}")
            else:
                plan.settle = True

        # --- PROMO_HITS / POST_RACE_COPY（SETTLED 後附屬）---
        settled_ready_soon = settled_st == STATUS_OK or plan.settle
        if not AUTO_PROMO_HITS and not AUTO_POST_RACE_COPY:
            plan.skip_reasons.append("PROMO/POST_COPY disabled by env")
        elif not settled_ready_soon:
            plan.skip_reasons.append("PROMO wait: SETTLED not ready")
        else:
            already_promo = False
            try:
                from ad_copy_jobs import job_done_for_batch, resolve_meeting_batch_id
                from ad_poster import default_output_dir

                bid = resolve_meeting_batch_id(d, c, prefer_settled=True) or ""
                out_root = default_output_dir()
                if (
                    bid
                    and not self.guards.force
                    and job_done_for_batch(out_root, d, c, "promo_hits", bid)
                ):
                    already_promo = True
            except Exception:
                bid = ""
                already_promo = False

            if AUTO_PROMO_HITS:
                if already_promo:
                    plan.skip_reasons.append("PROMO_HITS already archived")
                else:
                    st_row = self.get_tick_state(d, c, "PROMO_HITS")
                    last_st = str((st_row or {}).get("last_status") or STATUS_PENDING)
                    allowed, why = self._attempt_allowed(
                        d, c, "PROMO_HITS", last_st, now=now
                    )
                    if not allowed:
                        plan.skip_reasons.append(f"PROMO_HITS skip: {why}")
                    else:
                        plan.promo_hits = True

            if AUTO_POST_RACE_COPY:
                already_copy = False
                try:
                    from ad_copy_jobs import job_done_for_batch
                    from ad_poster import default_output_dir

                    if (
                        bid
                        and not self.guards.force
                        and job_done_for_batch(
                            default_output_dir(), d, c, "post_race", bid
                        )
                    ):
                        already_copy = True
                except Exception:
                    already_copy = False
                if already_copy:
                    plan.skip_reasons.append("POST_RACE_COPY already archived")
                else:
                    st_row = self.get_tick_state(d, c, "POST_RACE_COPY")
                    last_st = str((st_row or {}).get("last_status") or STATUS_PENDING)
                    allowed, why = self._attempt_allowed(
                        d, c, "POST_RACE_COPY", last_st, now=now
                    )
                    if not allowed:
                        plan.skip_reasons.append(f"POST_RACE_COPY skip: {why}")
                    else:
                        # 即使 promo=0 也會跑（job 內 skip）；確保評估後有機會產文
                        plan.post_race_copy = True

        return plan

    def execute_post_race_meeting(
        self, plan: MeetingActionPlan, *, dry_run: bool = False
    ) -> Dict[str, Any]:
        d, c = plan.racing_date, plan.course
        out: Dict[str, Any] = {
            "racing_date": d,
            "course": c,
            "dry_run": dry_run,
            "plan": {
                "sync_results": plan.sync_results,
                "sync_text_reports": plan.sync_text_reports,
                "settle": plan.settle,
                "promo_hits": plan.promo_hits,
                "post_race_copy": plan.post_race_copy,
                "skip_reasons": list(plan.skip_reasons),
            },
            "actions": [],
        }

        if plan.sync_results:
            action_rec: Dict[str, Any] = {"action": "sync_jjjc_results"}
            if dry_run:
                action_rec["ok"] = True
                action_rec["dry_run"] = True
            else:
                result = self.pipe.run_action(d, c, "sync_jjjc_results")
                ok = bool(result.get("ok"))
                detail = str(
                    result.get("error")
                    or result.get("msg")
                    or result.get("detail")
                    or ""
                )
                err = str(result.get("error") or "")
                if ok:
                    status = STATUS_OK
                    count_as_success = True
                elif "尚未" in err or "無賽果" in err or "empty" in err.lower():
                    status = STATUS_WAITING
                    count_as_success = True  # 官方未上架：唔累加 fail_count
                else:
                    status = STATUS_FAILED
                    count_as_success = False
                self.record_tick_attempt(
                    d,
                    c,
                    "RESULTS",
                    ok=count_as_success,
                    status=status,
                    detail=detail or err,
                )
                action_rec["ok"] = ok
                action_rec["result"] = {
                    k: result.get(k)
                    for k in ("ok", "error", "n_races", "n_runners", "msg")
                    if k in result
                } or result
                # 刷新 readiness
                out["readiness_after_sync"] = self.pipe.refresh_readiness(d, c)
            out["actions"].append(action_rec)

        if plan.sync_text_reports:
            action_rec = {"action": "sync_jjjc_text_reports"}
            if dry_run:
                action_rec["ok"] = True
                action_rec["dry_run"] = True
            else:
                result = self.pipe.run_action(d, c, "sync_jjjc_text_reports")
                ok = bool(result.get("ok"))
                waiting = bool(result.get("waiting"))
                detail = str(
                    result.get("error")
                    or result.get("detail")
                    or result.get("msg")
                    or ""
                )
                err = str(result.get("error") or "")
                if ok and waiting:
                    status = STATUS_WAITING
                    count_as_success = True
                elif ok:
                    status = STATUS_OK
                    count_as_success = True
                else:
                    # 404／unavailable：failed（可改打 J18 history 備援；本階段先記 failed）
                    status = STATUS_FAILED
                    count_as_success = False
                self.record_tick_attempt(
                    d,
                    c,
                    "TEXT_REPORTS",
                    ok=count_as_success,
                    status=status,
                    detail=detail or err,
                )
                action_rec["ok"] = ok
                action_rec["waiting"] = waiting
                action_rec["result"] = {
                    k: result.get(k)
                    for k in (
                        "ok",
                        "waiting",
                        "phase",
                        "error",
                        "runner_upserted",
                        "content_updated_at",
                        "detail",
                    )
                    if k in result
                } or result
                out["readiness_after_text_reports"] = self.pipe.refresh_readiness(d, c)
            out["actions"].append(action_rec)

        if plan.settle:
            action_rec = {"action": "settle"}
            if dry_run:
                action_rec["ok"] = True
                action_rec["dry_run"] = True
            else:
                # 若本輪先 sync，以最新 RESULTS 為準；仍無名次則跳過 settle
                ready = self.pipe.refresh_readiness(d, c)
                results_st = str((ready.get("RESULTS") or {}).get("status") or "")
                if results_st != STATUS_OK:
                    action_rec["ok"] = False
                    action_rec["skipped"] = True
                    action_rec["reason"] = "RESULTS still not ok after sync"
                    self.record_tick_attempt(
                        d,
                        c,
                        "SETTLED",
                        ok=True,
                        status=STATUS_WAITING,
                        detail=action_rec["reason"],
                    )
                else:
                    result = self.pipe.run_action(d, c, "settle")
                    settled_batches = list(result.get("settled_batches") or [])
                    err = result.get("error")
                    ok = err is None and result.get("ok", True) is not False
                    detail = str(err or "")
                    if ok and not settled_batches and not result.get("updated_rows"):
                        status = STATUS_WAITING
                        detail = detail or "settle ran but no batch fully settled yet"
                        count_as_success = True
                    elif ok:
                        status = STATUS_OK
                        count_as_success = True
                    else:
                        status = STATUS_FAILED
                        count_as_success = False
                    self.record_tick_attempt(
                        d,
                        c,
                        "SETTLED",
                        ok=count_as_success,
                        status=status,
                        detail=detail
                        or json.dumps(
                            {"settled_batches": settled_batches}, ensure_ascii=False
                        )[:500],
                    )
                    action_rec["ok"] = ok
                    action_rec["result"] = {
                        k: result.get(k)
                        for k in (
                            "ok",
                            "error",
                            "settled_batches",
                            "updated_rows",
                            "waiting_results",
                            "message",
                            "msg",
                        )
                        if k in result
                    } or result
                    out["readiness_after_settle"] = self.pipe.refresh_readiness(d, c)
            out["actions"].append(action_rec)

        # 附屬：本 meeting 已 SETTLED（或本輪 settle 成功）→ promo／文案
        # 注意：run_post_race 會把 settle 延後；此處只處理 plan.settle=False 且已 settled 的補跑
        if (plan.promo_hits or plan.post_race_copy) and not plan.settle:
            ready = (
                out.get("readiness_after_settle")
                or out.get("readiness_after_sync")
                or self.pipe.refresh_readiness(d, c)
            )
            settled_ok = (
                str((ready.get("SETTLED") or {}).get("status") or "") == STATUS_OK
            )
            if settled_ok or dry_run:
                ad_rec = self._run_post_race_ad_actions(
                    d, c, plan, dry_run=dry_run
                )
                out["actions"].extend(ad_rec)

        if (
            not plan.sync_results
            and not plan.sync_text_reports
            and not plan.settle
            and not plan.promo_hits
            and not plan.post_race_copy
        ):
            out["noop"] = True
        return out

    def _run_post_race_ad_actions(
        self,
        d: str,
        c: str,
        plan: MeetingActionPlan,
        *,
        dry_run: bool = False,
        settled_batch_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """執行 promo_hits／post_race_copy 並寫 tick_state。"""
        actions: List[Dict[str, Any]] = []
        if not (plan.promo_hits or plan.post_race_copy):
            return actions
        if dry_run:
            if plan.promo_hits:
                actions.append(
                    {"action": "promo_hits", "ok": True, "dry_run": True}
                )
            if plan.post_race_copy:
                actions.append(
                    {"action": "post_race_copy", "ok": True, "dry_run": True}
                )
            return actions
        try:
            from ad_copy_jobs import run_post_race_ad_cascade

            cascade = run_post_race_ad_cascade(
                racing_date=d,
                course=c,
                batch_ids=list(settled_batch_ids or []) or None,
                force=self.guards.force,
                dry_run=False,
                auto_promo=bool(plan.promo_hits),
                auto_copy=bool(plan.post_race_copy),
            )
            for step in cascade.get("actions") or []:
                name = str(step.get("action") or "")
                stage = (
                    "PROMO_HITS"
                    if name == "promo_hits"
                    else "POST_RACE_COPY"
                    if name == "post_race_copy"
                    else name.upper()
                )
                rec = {
                    "action": name,
                    "ok": bool(step.get("ok")),
                    "result": {
                        k: step.get(k)
                        for k in (
                            "ok",
                            "skipped",
                            "waiting",
                            "error",
                            "reason",
                            "batch_id",
                            "n_promo_races",
                            "n_featured",
                            "source",
                            "archive",
                            "promo_hits",
                            "post_race_copy",
                        )
                        if k in step
                    }
                    or step,
                }
                actions.append(rec)
                # skipped＋ok 算成功；waiting 不累加 fail
                self._record_pull_attempt(
                    d,
                    c,
                    stage,
                    step,
                    waiting_hints=("尚無", "尚未", "waiting"),
                )
        except Exception as e:
            actions.append(
                {
                    "action": "post_race_ad_cascade",
                    "ok": False,
                    "result": {"ok": False, "error": str(e)},
                }
            )
            if plan.promo_hits:
                self.record_tick_attempt(
                    d, c, "PROMO_HITS", ok=False, status=STATUS_FAILED, detail=str(e)
                )
            if plan.post_race_copy:
                self.record_tick_attempt(
                    d,
                    c,
                    "POST_RACE_COPY",
                    ok=False,
                    status=STATUS_FAILED,
                    detail=str(e),
                )
        return actions

    def run_post_race(
        self,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        racing_date: Optional[str] = None,
        course: Optional[str] = None,
        dry_run: bool = False,
        as_of: Optional[date] = None,
    ) -> Dict[str, Any]:
        today = as_of or date.today()
        if racing_date:
            meetings = [(racing_date[:10], (course or "ST").upper())]
            if course is None:
                # 若只給日期，展開該日所有已知 meeting
                start = date.fromisoformat(racing_date[:10])
                meetings = [
                    m
                    for m in self.list_meetings_in_range(start, start)
                ] or meetings
        else:
            start = today - timedelta(days=max(0, int(lookback_days)))
            meetings = self.list_meetings_in_range(start, today)

        report: Dict[str, Any] = {
            "mode": POST_RACE_MODE,
            "dry_run": dry_run,
            "as_of": today.isoformat(),
            "lookback_days": lookback_days,
            "guards": {
                "cooldown_waiting_sec": self.guards.cooldown_waiting_sec,
                "cooldown_failed_sec": self.guards.cooldown_failed_sec,
                "max_fails": self.guards.max_fails,
                "force": self.guards.force,
            },
            "meetings": [],
            "n_meetings": 0,
            "n_actions": 0,
        }

        # settle 全域一次即可；先收集需要 settle 的 meeting，最後跑一次
        settle_requested = False
        deferred_settle_meetings: List[MeetingActionPlan] = []
        deferred_ad_meetings: List[MeetingActionPlan] = []

        for d, c in meetings:
            plan = self.plan_post_race_meeting(d, c)
            # 拆開：先執行 sync；settle 延後合併；附屬廣告亦跟 settle 後跑
            local = MeetingActionPlan(
                racing_date=plan.racing_date,
                course=plan.course,
                sync_results=plan.sync_results,
                sync_text_reports=plan.sync_text_reports,
                settle=False,
                # 僅當本輪不需 settle（已結算）才即時跑廣告附屬
                promo_hits=bool(plan.promo_hits and not plan.settle),
                post_race_copy=bool(plan.post_race_copy and not plan.settle),
                skip_reasons=list(plan.skip_reasons),
                readiness=plan.readiness,
            )
            meeting_out = self.execute_post_race_meeting(local, dry_run=dry_run)
            if plan.settle:
                settle_requested = True
                deferred_settle_meetings.append(plan)
                meeting_out["plan"]["settle_deferred"] = True
                if plan.promo_hits or plan.post_race_copy:
                    deferred_ad_meetings.append(plan)
                    meeting_out["plan"]["ad_deferred"] = True
            report["meetings"].append(meeting_out)
            report["n_actions"] += len(meeting_out.get("actions") or [])

        if settle_requested:
            settle_rec: Dict[str, Any] = {
                "action": "settle_pending",
                "meetings": [f"{p.racing_date}:{p.course}" for p in deferred_settle_meetings],
            }
            if dry_run:
                settle_rec["ok"] = True
                settle_rec["dry_run"] = True
            else:
                # 任一 meeting RESULTS 已 ok 才值得 settle
                any_results_ok = False
                for p in deferred_settle_meetings:
                    ready = self.pipe.refresh_readiness(p.racing_date, p.course)
                    if str((ready.get("RESULTS") or {}).get("status")) == STATUS_OK:
                        any_results_ok = True
                        break
                if not any_results_ok:
                    settle_rec["ok"] = False
                    settle_rec["skipped"] = True
                    settle_rec["reason"] = "no meeting with RESULTS=ok"
                    for p in deferred_settle_meetings:
                        self.record_tick_attempt(
                            p.racing_date,
                            p.course,
                            "SETTLED",
                            ok=True,
                            status=STATUS_WAITING,
                            detail=settle_rec["reason"],
                        )
                else:
                    result = self.pipe.run_action(
                        deferred_settle_meetings[0].racing_date,
                        deferred_settle_meetings[0].course,
                        "settle",
                    )
                    settled_batches = list(result.get("settled_batches") or [])
                    err = result.get("error")
                    ok = err is None and result.get("ok", True) is not False
                    settle_rec["ok"] = ok
                    settle_rec["result"] = {
                        k: result.get(k)
                        for k in (
                            "ok",
                            "error",
                            "settled_batches",
                            "updated_rows",
                            "waiting_results",
                            "message",
                        )
                        if k in result
                    } or result
                    for p in deferred_settle_meetings:
                        ready = self.pipe.refresh_readiness(p.racing_date, p.course)
                        settled_ok = (
                            str((ready.get("SETTLED") or {}).get("status")) == STATUS_OK
                        )
                        self.record_tick_attempt(
                            p.racing_date,
                            p.course,
                            "SETTLED",
                            ok=settled_ok,
                            status=STATUS_OK if settled_ok else STATUS_WAITING,
                            detail=(
                                f"settled_batches={settled_batches}"
                                if settled_ok
                                else "settle ran; meeting not fully settled yet"
                            ),
                        )
            report["settle"] = settle_rec
            report["n_actions"] += 1

            # settle 後：對已 SETTLED 的 deferred ad meetings 跑宣傳／文案
            ad_report: List[Dict[str, Any]] = []
            for p in deferred_ad_meetings:
                if dry_run:
                    ad_actions = self._run_post_race_ad_actions(
                        p.racing_date, p.course, p, dry_run=True
                    )
                else:
                    ready = self.pipe.refresh_readiness(p.racing_date, p.course)
                    if str((ready.get("SETTLED") or {}).get("status")) != STATUS_OK:
                        ad_report.append(
                            {
                                "racing_date": p.racing_date,
                                "course": p.course,
                                "skipped": True,
                                "reason": "SETTLED not ok after settle",
                            }
                        )
                        continue
                    settled_batches = list(
                        ((report.get("settle") or {}).get("result") or {}).get(
                            "settled_batches"
                        )
                        or []
                    )
                    ad_actions = self._run_post_race_ad_actions(
                        p.racing_date,
                        p.course,
                        p,
                        dry_run=False,
                        settled_batch_ids=settled_batches or None,
                    )
                ad_report.append(
                    {
                        "racing_date": p.racing_date,
                        "course": p.course,
                        "actions": ad_actions,
                    }
                )
                report["n_actions"] += len(ad_actions)
            if ad_report:
                report["post_race_ads"] = ad_report

        # 數據遺留：保留窗掃評述缺口（可超出 lookback）
        if AUTO_BACKLOG:
            report["backlog"] = self.run_backlog_pass(
                as_of=today,
                dry_run=dry_run,
            )
            report["n_actions"] += int(
                (report.get("backlog") or {}).get("n_processed") or 0
            )

        # needs_human／failed → 營運介入報告（notify_admins 入口；預設可 stub）
        if not dry_run:
            report["incidents"] = self.scan_ops_incidents(report)
            report["n_actions"] += int(
                (report.get("incidents") or {}).get("n_created") or 0
            )

        report["n_meetings"] = len(report["meetings"])
        return report

    def scan_ops_incidents(self, tick_report: Dict[str, Any]) -> Dict[str, Any]:
        """依本輪 meeting readiness／tick fail_count／backlog 寫介入報告。"""
        try:
            from ops_incidents import OpsIncidentService

            svc = OpsIncidentService(engine=self.pipe.engine)
            created: List[Dict[str, Any]] = []
            n_created = 0
            meetings = tick_report.get("meetings") or []
            pairs: List[Tuple[str, str]] = []
            for m in meetings:
                d = str(m.get("racing_date") or "")[:10]
                c = str(m.get("course") or "").upper()
                if d and c:
                    pairs.append((d, c))
            # 去重
            seen = set()
            uniq: List[Tuple[str, str]] = []
            for p in pairs:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)

            backlog = tick_report.get("backlog") or {}
            backlog_expiring = False
            try:
                from data_backlog import STATUS_EXPIRED, STATUS_OPEN

                # 粗判：本輪有 expired 計數或 open 且接近保留窗
                counts = backlog.get("counts") or {}
                if int(counts.get(STATUS_EXPIRED) or 0) > 0:
                    backlog_expiring = True
                # 亦對個別 open 項標將過期（由 evaluate 統一建）
                if int(counts.get(STATUS_OPEN) or 0) > 0 and int(
                    counts.get(STATUS_EXPIRED) or 0
                ) == 0:
                    # 不強制；僅當 process 回傳 expiring 標記
                    backlog_expiring = bool(backlog.get("expiring"))
            except Exception:
                pass

            for d, c in uniq:
                ready = self.pipe.refresh_readiness(d, c)
                # 取各 stage 最大 fail_count
                max_fc = 0
                try:
                    for stage, _label in (
                        ("RACECARD", ""),
                        ("SPEEDGUIDE", ""),
                        ("FORMGUIDE", ""),
                        ("FORM_AI", ""),
                        ("SNAPSHOT", ""),
                        ("RESULTS", ""),
                        ("SETTLED", ""),
                    ):
                        st_row = self.get_tick_state(d, c, stage)
                        max_fc = max(max_fc, int(st_row.get("fail_count") or 0))
                except Exception:
                    max_fc = 0
                outs = svc.evaluate_meeting_needs_human(
                    d,
                    c,
                    ready,
                    tick_fail_count=max_fc if max_fc else None,
                    max_fails=int(self.guards.max_fails),
                    backlog_expiring=backlog_expiring,
                    notify=True,
                )
                for o in outs:
                    created.append(o)
                    if o.get("created"):
                        n_created += 1

            return {
                "ok": True,
                "n_meetings": len(uniq),
                "n_actions": len(created),
                "n_created": n_created,
                "reports": created,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "n_created": 0}

    def run_backlog_pass(
        self,
        *,
        as_of: Optional[date] = None,
        dry_run: bool = False,
        retention_days: int = DEFAULT_BACKLOG_RETENTION_DAYS,
        limit: int = DEFAULT_BACKLOG_LIMIT,
    ) -> Dict[str, Any]:
        """延遲資料遺留清單：入列＋到期重試（沿途／事故評述）。"""
        try:
            from data_backlog import DataBacklogService

            svc = DataBacklogService(engine=self.pipe.engine)
            return svc.run_tick_pass(
                as_of=as_of or date.today(),
                retention_days=retention_days,
                limit=limit,
                dry_run=dry_run,
                force=bool(self.guards.force),
            )
        except Exception as e:
            return {"ok": False, "error": str(e)}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Meeting pipeline auto tick (pre_race / post_race / all)"
    )
    p.add_argument(
        "--mode",
        default=DEFAULT_TICK_MODE if DEFAULT_TICK_MODE in (
            PRE_RACE_MODE,
            POST_RACE_MODE,
            ALL_MODE,
        )
        else ALL_MODE,
        choices=[PRE_RACE_MODE, POST_RACE_MODE, ALL_MODE],
        help="pre_race｜post_race｜all（預設 env MEETING_TICK_MODE 或 all）",
    )
    p.add_argument("--dry-run", action="store_true", help="只規劃／列印，不呼叫 sync／settle")
    p.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    p.add_argument("--lookahead-days", type=int, default=DEFAULT_LOOKAHEAD_DAYS)
    p.add_argument("--date", dest="racing_date", help="YYYY-MM-DD（可選，限定單日）")
    p.add_argument("--course", help="ST / HV（配合 --date）")
    p.add_argument("--force", action="store_true", help="忽略 cooldown 與 max fails")
    p.add_argument(
        "--cooldown-waiting-sec",
        type=int,
        default=DEFAULT_COOLDOWN_WAITING_SEC,
    )
    p.add_argument(
        "--cooldown-failed-sec",
        type=int,
        default=DEFAULT_COOLDOWN_FAILED_SEC,
    )
    p.add_argument("--max-fails", type=int, default=DEFAULT_MAX_FAILS)
    p.add_argument("--json", action="store_true", help="stdout 只輸出 JSON report")
    return p


def _report_has_hard_error(report: Dict[str, Any]) -> bool:
    """waiting／noop／skipped 不當 cron 失敗；明確 failed 才非零。"""
    if report.get("mode") == ALL_MODE:
        return _report_has_hard_error(report.get("pre_race") or {}) or _report_has_hard_error(
            report.get("post_race") or {}
        )
    hard = False
    for m in report.get("meetings") or []:
        for a in m.get("actions") or []:
            if a.get("ok") is False and not a.get("skipped") and not a.get("dry_run"):
                res = a.get("result") or {}
                err = str(res.get("error") or a.get("reason") or "")
                if any(
                    x in err
                    for x in ("無賽果", "尚未", "waiting", "無排位", "empty", "進行中", "404", "No route")
                ):
                    continue
                if res.get("waiting"):
                    continue
                hard = True
    settle = report.get("settle") or {}
    if settle.get("ok") is False and not settle.get("skipped") and not settle.get("dry_run"):
        hard = True
    return hard


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    guards = TickGuards(
        cooldown_waiting_sec=args.cooldown_waiting_sec,
        cooldown_failed_sec=args.cooldown_failed_sec,
        max_fails=args.max_fails,
        force=bool(args.force),
    )
    runner = MeetingTickRunner(guards=guards)
    if args.mode == PRE_RACE_MODE:
        report = runner.run_pre_race(
            lookahead_days=args.lookahead_days,
            racing_date=args.racing_date,
            course=args.course,
            dry_run=bool(args.dry_run),
        )
    elif args.mode == POST_RACE_MODE:
        report = runner.run_post_race(
            lookback_days=args.lookback_days,
            racing_date=args.racing_date,
            course=args.course,
            dry_run=bool(args.dry_run),
        )
    elif args.mode == ALL_MODE:
        report = runner.run_all(
            lookahead_days=args.lookahead_days,
            lookback_days=args.lookback_days,
            racing_date=args.racing_date,
            course=args.course,
            dry_run=bool(args.dry_run),
        )
    else:
        print(f"unsupported mode: {args.mode}", file=sys.stderr)
        return 2

    text_out = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.json:
        print(text_out)
    else:
        print(
            f"[meeting_tick] mode={report.get('mode')} dry_run={report.get('dry_run')} "
            f"meetings={report.get('n_meetings')} actions={report.get('n_actions')}"
        )
        print(text_out)
    return 1 if _report_has_hard_error(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
