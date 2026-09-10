"""
賽日自動 tick（階段 1：賽後 RESULTS → SETTLED）。

依 fixtures／未結算快照選賽日，refresh readiness 後只跑該做的動作：
  1) sync_jjjc_results（官方未上架 → waiting，冷卻後再試）
  2) sync_jjjc_text_reports（沿途／事故；空＝waiting；JJJC 主路徑）
  3) settle_pending（有快照且尚未結算）

原則（對齊 DEVELOPMENT_REPORT §5.3）：
  - 短週期 Cron 呼叫本 CLI；勿塞進 Streamlit request
  - 依 readiness 重試；禁止無限狂爬（cooldown + max fails）
  - 人工略過／放行（manual_override）不覆蓋、不強跑

用法：
  python meeting_tick.py --dry-run
  python meeting_tick.py --mode post_race --lookback-days 3
  python meeting_tick.py --date 2026-09-09 --course HV
  python meeting_tick.py --force   # 忽略 cooldown／失敗上限（仍尊重 manual skip）
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
DEFAULT_COOLDOWN_WAITING_SEC = int(
    os.getenv("MEETING_TICK_COOLDOWN_WAITING_SEC", str(30 * 60)) or 30 * 60
)
DEFAULT_COOLDOWN_FAILED_SEC = int(
    os.getenv("MEETING_TICK_COOLDOWN_FAILED_SEC", str(60 * 60)) or 60 * 60
)
DEFAULT_MAX_FAILS = int(os.getenv("MEETING_TICK_MAX_FAILS", "5") or 5)

POST_RACE_MODE = "post_race"


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

        if not plan.sync_results and not plan.sync_text_reports and not plan.settle:
            out["noop"] = True
        return out

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

        for d, c in meetings:
            plan = self.plan_post_race_meeting(d, c)
            # 拆開：先執行 sync；settle 延後合併
            local = MeetingActionPlan(
                racing_date=plan.racing_date,
                course=plan.course,
                sync_results=plan.sync_results,
                sync_text_reports=plan.sync_text_reports,
                settle=False,
                skip_reasons=list(plan.skip_reasons),
                readiness=plan.readiness,
            )
            meeting_out = self.execute_post_race_meeting(local, dry_run=dry_run)
            if plan.settle:
                settle_requested = True
                deferred_settle_meetings.append(plan)
                meeting_out["plan"]["settle_deferred"] = True
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

        report["n_meetings"] = len(report["meetings"])
        return report


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Meeting pipeline auto tick (post-race phase 1)")
    p.add_argument(
        "--mode",
        default=POST_RACE_MODE,
        choices=[POST_RACE_MODE],
        help="目前只支援 post_race（賽前 tick 較後階段）",
    )
    p.add_argument("--dry-run", action="store_true", help="只規劃／列印，不呼叫 sync／settle")
    p.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    guards = TickGuards(
        cooldown_waiting_sec=args.cooldown_waiting_sec,
        cooldown_failed_sec=args.cooldown_failed_sec,
        max_fails=args.max_fails,
        force=bool(args.force),
    )
    runner = MeetingTickRunner(guards=guards)
    if args.mode == POST_RACE_MODE:
        report = runner.run_post_race(
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
    # 有硬錯誤才非零；waiting／noop 仍 0 方便 Cron
    hard = False
    for m in report.get("meetings") or []:
        for a in m.get("actions") or []:
            if a.get("ok") is False and not a.get("skipped") and not a.get("dry_run"):
                # RESULTS empty export → waiting，唔當 cron 失敗
                res = a.get("result") or {}
                err = str(res.get("error") or "")
                if "無賽果" in err or "尚未" in err:
                    continue
                hard = True
    settle = report.get("settle") or {}
    if settle.get("ok") is False and not settle.get("skipped") and not settle.get("dry_run"):
        hard = True
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
