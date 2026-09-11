"""
營運介入報告＋管理員通知入口。

設計（全自動為主）：
  - tick／readiness 發現 needs_human／嚴重問題 → create_incident → notify_admins
  - 作戰室每次人工放行／略過／一鍵重跑 → 也寫報告
  - 真正發信（Resend）後期再優化；本模組必須保留唯一入口 notify_admins()
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from etl_pipeline import USE_SQLITE, resolve_database_url

logger = logging.getLogger(__name__)

STATUS_OPEN = "open"
STATUS_ACKED = "acked"
STATUS_RESOLVED = "resolved"

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_CRIT = "crit"

# 通知開關（發信實作可後期接 Resend）
NOTIFY_ENABLED = (os.getenv("NOTIFY_ENABLED", "false") or "false").lower() in (
    "1",
    "true",
    "yes",
)
RESEND_API_KEY = (os.getenv("RESEND_API_KEY") or "").strip()
NOTIFY_FROM = (os.getenv("NOTIFY_FROM") or "alerts@j18ai.local").strip()
NOTIFY_ADMIN_EMAILS = [
    x.strip()
    for x in (os.getenv("NOTIFY_ADMIN_EMAILS") or "").split(",")
    if x.strip()
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    d = dt or _utcnow()
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat()


def resolve_engine(engine: Optional[Engine] = None) -> Engine:
    if engine is not None:
        return engine
    if USE_SQLITE:
        from etl_pipeline import SQLITE_DB_PATH

        return create_engine(f"sqlite:///{SQLITE_DB_PATH}")
    url = resolve_database_url()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url)


class OpsIncidentService:
    """介入報告 CRUD＋needs_human 掃描＋通知入口。"""

    def __init__(self, engine: Optional[Engine] = None):
        self.engine = resolve_engine(engine)
        self.ensure_tables()

    def ensure_tables(self) -> None:
        if USE_SQLITE:
            ddl = """
            CREATE TABLE IF NOT EXISTS ops_incident_reports (
                report_id TEXT PRIMARY KEY,
                racing_date TEXT,
                course TEXT,
                stage TEXT,
                data_kind TEXT,
                reason_code TEXT NOT NULL,
                severity TEXT DEFAULT 'warn',
                detail TEXT,
                status TEXT DEFAULT 'open',
                triggered_by TEXT DEFAULT 'system',
                action_taken TEXT,
                notify_status TEXT DEFAULT 'pending',
                notify_detail TEXT,
                dedupe_key TEXT,
                created_at TEXT,
                resolved_at TEXT,
                meta_json TEXT
            )
            """
            idx = (
                "CREATE INDEX IF NOT EXISTS idx_ops_incidents_open "
                "ON ops_incident_reports (status, created_at)"
            )
            idx2 = (
                "CREATE INDEX IF NOT EXISTS idx_ops_incidents_dedupe "
                "ON ops_incident_reports (dedupe_key, status)"
            )
        else:
            ddl = """
            CREATE TABLE IF NOT EXISTS ops_incident_reports (
                report_id TEXT PRIMARY KEY,
                racing_date TEXT,
                course TEXT,
                stage TEXT,
                data_kind TEXT,
                reason_code TEXT NOT NULL,
                severity TEXT DEFAULT 'warn',
                detail TEXT,
                status TEXT DEFAULT 'open',
                triggered_by TEXT DEFAULT 'system',
                action_taken TEXT,
                notify_status TEXT DEFAULT 'pending',
                notify_detail TEXT,
                dedupe_key TEXT,
                created_at TIMESTAMPTZ,
                resolved_at TIMESTAMPTZ,
                meta_json TEXT
            )
            """
            idx = (
                "CREATE INDEX IF NOT EXISTS idx_ops_incidents_open "
                "ON ops_incident_reports (status, created_at DESC)"
            )
            idx2 = (
                "CREATE INDEX IF NOT EXISTS idx_ops_incidents_dedupe "
                "ON ops_incident_reports (dedupe_key, status)"
            )
        with self.engine.begin() as conn:
            conn.execute(text(ddl))
            try:
                conn.execute(text(idx))
                conn.execute(text(idx2))
            except Exception:
                pass

    def _find_open_dedupe(self, dedupe_key: str) -> Optional[str]:
        if not dedupe_key:
            return None
        q = text(
            """
            SELECT report_id FROM ops_incident_reports
            WHERE dedupe_key = :k AND status IN ('open', 'acked')
            ORDER BY created_at DESC LIMIT 1
            """
        )
        df = pd.read_sql(q, self.engine, params={"k": dedupe_key})
        if df.empty:
            return None
        return str(df.iloc[0]["report_id"])

    def create_incident(
        self,
        *,
        reason_code: str,
        detail: str = "",
        racing_date: Optional[str] = None,
        course: Optional[str] = None,
        stage: Optional[str] = None,
        data_kind: Optional[str] = None,
        severity: str = SEVERITY_WARN,
        triggered_by: str = "system",
        action_taken: str = "",
        meta: Optional[Dict[str, Any]] = None,
        notify: bool = True,
        dedupe: bool = True,
    ) -> Dict[str, Any]:
        """建立報告；同 dedupe_key 未解決則不重複建／不狂寄。"""
        d = (racing_date or "")[:10]
        c = (course or "").upper()
        st = stage or ""
        dedupe_key = f"{d}|{c}|{st}|{reason_code}|{data_kind or ''}"
        if dedupe:
            existing = self._find_open_dedupe(dedupe_key)
            if existing:
                return {
                    "ok": True,
                    "created": False,
                    "report_id": existing,
                    "deduped": True,
                    "notify": None,
                }

        report_id = f"inc_{uuid.uuid4().hex[:16]}"
        now = _iso()
        payload = {
            "report_id": report_id,
            "racing_date": d or None,
            "course": c or None,
            "stage": st or None,
            "data_kind": data_kind,
            "reason_code": reason_code,
            "severity": severity,
            "detail": (detail or "")[:4000],
            "status": STATUS_OPEN,
            "triggered_by": triggered_by,
            "action_taken": (action_taken or "")[:2000],
            "notify_status": "pending",
            "notify_detail": None,
            "dedupe_key": dedupe_key,
            "created_at": now,
            "resolved_at": None,
            "meta_json": json.dumps(meta or {}, ensure_ascii=False),
        }
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ops_incident_reports (
                        report_id, racing_date, course, stage, data_kind,
                        reason_code, severity, detail, status, triggered_by,
                        action_taken, notify_status, notify_detail, dedupe_key,
                        created_at, resolved_at, meta_json
                    ) VALUES (
                        :report_id, :racing_date, :course, :stage, :data_kind,
                        :reason_code, :severity, :detail, :status, :triggered_by,
                        :action_taken, :notify_status, :notify_detail, :dedupe_key,
                        :created_at, :resolved_at, :meta_json
                    )
                    """
                ),
                payload,
            )

        notify_out = None
        if notify:
            notify_out = notify_admins(self.get_report(report_id) or payload)
            self._update_notify(report_id, notify_out)
        return {
            "ok": True,
            "created": True,
            "report_id": report_id,
            "deduped": False,
            "notify": notify_out,
        }

    def _update_notify(self, report_id: str, notify_out: Dict[str, Any]) -> None:
        status = "sent" if notify_out.get("ok") and notify_out.get("sent") else (
            "skipped" if notify_out.get("skipped") else "failed"
        )
        if notify_out.get("stub"):
            status = "stub"
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE ops_incident_reports
                    SET notify_status = :ns, notify_detail = :nd
                    WHERE report_id = :id
                    """
                ),
                {
                    "ns": status,
                    "nd": json.dumps(notify_out, ensure_ascii=False)[:2000],
                    "id": report_id,
                },
            )

    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        df = pd.read_sql(
            text("SELECT * FROM ops_incident_reports WHERE report_id = :id"),
            self.engine,
            params={"id": report_id},
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def list_reports(
        self,
        *,
        statuses: Optional[Sequence[str]] = None,
        racing_date: Optional[str] = None,
        course: Optional[str] = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        statuses = list(statuses) if statuses else [STATUS_OPEN, STATUS_ACKED]
        clauses = ["status IN :statuses"]
        # SQLAlchemy expanding + pandas：改用字面 IN
        status_list = ",".join(f"'{s}'" for s in statuses)
        where = [f"status IN ({status_list})"]
        params: Dict[str, Any] = {"lim": int(limit)}
        if racing_date:
            where.append("racing_date = :d")
            params["d"] = racing_date[:10]
        if course:
            where.append("course = :c")
            params["c"] = course.upper()
        q = f"""
            SELECT * FROM ops_incident_reports
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT :lim
        """
        return pd.read_sql(text(q), self.engine, params=params)

    def summary_counts(self) -> Dict[str, int]:
        df = pd.read_sql(
            text(
                "SELECT status, COUNT(*) AS n FROM ops_incident_reports GROUP BY status"
            ),
            self.engine,
        )
        out = {STATUS_OPEN: 0, STATUS_ACKED: 0, STATUS_RESOLVED: 0}
        for _, r in df.iterrows():
            out[str(r["status"])] = int(r["n"] or 0)
        return out

    def resolve(
        self,
        report_id: str,
        *,
        action_taken: str = "",
        triggered_by: str = "admin",
    ) -> Dict[str, Any]:
        now = _iso()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE ops_incident_reports
                    SET status = :st,
                        action_taken = CASE
                          WHEN :act = '' THEN action_taken
                          ELSE :act
                        END,
                        triggered_by = CASE
                          WHEN triggered_by = 'system' THEN :by
                          ELSE triggered_by
                        END,
                        resolved_at = :now
                    WHERE report_id = :id
                    """
                ),
                {
                    "st": STATUS_RESOLVED,
                    "act": (action_taken or "")[:2000],
                    "by": triggered_by,
                    "now": now,
                    "id": report_id,
                },
            )
        return {"ok": True, "report_id": report_id, "status": STATUS_RESOLVED}

    def record_manual_action(
        self,
        *,
        racing_date: str,
        course: str,
        stage: str,
        action: str,
        detail: str = "",
        reason_code: Optional[str] = None,
        notify: bool = False,
    ) -> Dict[str, Any]:
        """作戰室人工動作：一律落報告（預設不發信，避免操作噪音）。"""
        code = reason_code or f"manual_{action}"
        return self.create_incident(
            reason_code=code,
            detail=detail or f"人工動作：{action}",
            racing_date=racing_date,
            course=course,
            stage=stage,
            severity=SEVERITY_INFO,
            triggered_by="admin",
            action_taken=action,
            notify=notify,
            dedupe=False,
            meta={"manual_action": action},
        )

    def evaluate_meeting_needs_human(
        self,
        racing_date: str,
        course: str,
        ready: Dict[str, Any],
        *,
        tick_fail_count: Optional[int] = None,
        max_fails: int = 5,
        backlog_expiring: bool = False,
        notify: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        依 readiness／tick 規則產生 needs_human 報告。
        waiting 且未過預期窗 → 不告警；failed／錯位／連敗／遺留將過期 → 告警。
        """
        created: List[Dict[str, Any]] = []
        d, c = racing_date[:10], course.upper()

        for stage, info in (ready or {}).items():
            st = str((info or {}).get("status") or "")
            detail = str((info or {}).get("detail") or "")
            if st == "failed":
                reason = "stage_failed"
                sev = SEVERITY_CRIT
                if "錯位" in detail or "corrupt" in detail.lower():
                    reason = "racecard_corrupt"
                out = self.create_incident(
                    reason_code=reason,
                    detail=detail,
                    racing_date=d,
                    course=c,
                    stage=stage,
                    severity=sev,
                    triggered_by="system",
                    notify=notify,
                    dedupe=True,
                )
                created.append(out)
            elif st == "pending" and stage == "FORM_AI":
                # 距開賽緊迫時由呼叫端標；此處僅記 info 級待補（不強制 notify）
                pass

        if tick_fail_count is not None and tick_fail_count >= max_fails:
            out = self.create_incident(
                reason_code="tick_max_fails",
                detail=f"fail_count={tick_fail_count}>={max_fails}",
                racing_date=d,
                course=c,
                stage=None,
                severity=SEVERITY_CRIT,
                triggered_by="system",
                notify=notify,
                dedupe=True,
            )
            created.append(out)

        if backlog_expiring:
            out = self.create_incident(
                reason_code="backlog_expiring",
                detail="遺留評述接近保留窗到期，需人工決定略過或強制補撈",
                racing_date=d,
                course=c,
                stage="NLP",
                data_kind="running_comment",
                severity=SEVERITY_WARN,
                triggered_by="system",
                notify=notify,
                dedupe=True,
            )
            created.append(out)

        return created

    def scan_from_pipeline(
        self,
        pipe,
        *,
        meetings: Optional[Sequence[tuple]] = None,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """對多個 meeting 跑 readiness 並寫 needs_human 報告。"""
        from meeting_pipeline import MeetingPipeline

        mp: MeetingPipeline = pipe
        fx = mp.list_fixtures(upcoming_only=True)
        pairs: List[tuple] = []
        if meetings:
            pairs = [(str(a)[:10], str(b).upper()) for a, b in meetings]
        elif fx is not None and not fx.empty:
            for _, r in fx.head(12).iterrows():
                pairs.append((str(r["racing_date"])[:10], str(r["course"]).upper()))

        reports: List[Dict[str, Any]] = []
        for d, c in pairs:
            ready = mp.refresh_readiness(d, c)
            reports.extend(
                self.evaluate_meeting_needs_human(
                    d, c, ready, notify=notify
                )
            )
        return {
            "ok": True,
            "n_meetings": len(pairs),
            "n_report_actions": len(reports),
            "reports": reports,
        }


def notify_admins(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    管理員通知唯一入口。

    現況：預設 stub（寫 log）；若 NOTIFY_ENABLED + RESEND_API_KEY + 收件人齊全，
    則嘗試 Resend HTTP API。文案／去重靜默窗後期再優化。
    """
    subject = _format_subject(report)
    body = _format_body(report)
    out: Dict[str, Any] = {
        "ok": True,
        "channel": "resend",
        "subject": subject,
        "to": list(NOTIFY_ADMIN_EMAILS),
        "stub": True,
        "sent": False,
        "skipped": False,
    }

    if not NOTIFY_ENABLED:
        out["skipped"] = True
        out["reason"] = "NOTIFY_ENABLED=false"
        logger.info("notify_admins skipped (disabled): %s", subject)
        return out

    if not NOTIFY_ADMIN_EMAILS:
        out["ok"] = False
        out["skipped"] = True
        out["reason"] = "NOTIFY_ADMIN_EMAILS empty"
        logger.warning("notify_admins: no admin emails configured")
        return out

    if not RESEND_API_KEY:
        # 入口已呼叫；未設 key 時保持 stub，方便後期接上
        out["stub"] = True
        out["reason"] = "RESEND_API_KEY missing — stub only"
        logger.info("notify_admins stub (no RESEND_API_KEY): %s\n%s", subject, body)
        return out

    try:
        import httpx

        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": NOTIFY_FROM,
                "to": NOTIFY_ADMIN_EMAILS,
                "subject": subject,
                "text": body,
            },
            timeout=20.0,
        )
        out["stub"] = False
        out["http_status"] = resp.status_code
        if resp.status_code >= 200 and resp.status_code < 300:
            out["sent"] = True
            try:
                out["provider"] = resp.json()
            except Exception:
                out["provider"] = {"raw": resp.text[:500]}
        else:
            out["ok"] = False
            out["error"] = resp.text[:800]
        return out
    except Exception as e:
        out["ok"] = False
        out["stub"] = False
        out["error"] = str(e)
        logger.exception("notify_admins Resend failed")
        return out


def _format_subject(report: Dict[str, Any]) -> str:
    d = report.get("racing_date") or "?"
    c = report.get("course") or "?"
    code = report.get("reason_code") or "incident"
    return f"[J18 營運] {d} {c} · {code}"


def _format_body(report: Dict[str, Any]) -> str:
    lines = [
        "J18HKJC 營運介入報告",
        "",
        f"report_id: {report.get('report_id')}",
        f"賽日: {report.get('racing_date')} {report.get('course')}",
        f"階段: {report.get('stage') or '—'}",
        f"原因: {report.get('reason_code')}",
        f"嚴重度: {report.get('severity')}",
        f"狀態: {report.get('status')}",
        f"觸發: {report.get('triggered_by')}",
        "",
        "說明:",
        str(report.get("detail") or ""),
        "",
        "請到管理 UI「數據營運中心／賽日作戰室」同一版面處理。",
        "（此信由 notify_admins 入口送出；Resend 文案後期可再優化。）",
    ]
    return "\n".join(lines)


def build_arg_parser():
    import argparse

    p = argparse.ArgumentParser(description="Ops incident reports / notify stub")
    p.add_argument("--list", action="store_true")
    p.add_argument("--scan", action="store_true", help="掃描 upcoming fixtures readiness")
    p.add_argument("--notify-test", action="store_true", help="送一則測試報告（走 notify 入口）")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys

    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    svc = OpsIncidentService()
    if args.notify_test:
        out = svc.create_incident(
            reason_code="notify_test",
            detail="手動測試 notify_admins / Resend 入口",
            severity=SEVERITY_INFO,
            triggered_by="cli",
            notify=True,
            dedupe=False,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.scan:
        from meeting_pipeline import MeetingPipeline

        out = svc.scan_from_pipeline(MeetingPipeline(), notify=True)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.list:
        df = svc.list_reports(limit=50)
        if args.json:
            print(df.to_json(orient="records", force_ascii=False))
        else:
            print(df.to_string(index=False) if not df.empty else "(empty)")
        return 0
    build_arg_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
