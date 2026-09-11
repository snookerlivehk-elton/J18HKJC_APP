"""
數據營運中心（Ops Center）

合併原「資料控制中心」整備監控 +「數據遺留清單」多日總覽，
並加上開放介入報告（needs_human）。

定位：多日總覽／告警；單日深挖仍在「賽日作戰室」。
主管道仍是 meeting_tick。
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from data_backlog import (
    DEFAULT_RETENTION_DAYS,
    KIND_INCIDENT,
    KIND_RUNNING,
    STATUS_EXPIRED,
    STATUS_OPEN,
    STATUS_RETRYING,
    STATUS_SKIPPED,
    DataBacklogService,
)
from meeting_pipeline import STAGES, MeetingPipeline
from ops_incidents import OpsIncidentService
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header(
    "數據營運中心",
    "多日整備總覽 · 遺留佇列 · 介入報告（tick 主管道；作戰室單日介入）",
)

pipe = MeetingPipeline()
bl = DataBacklogService(engine=pipe.engine)
inc = OpsIncidentService(engine=pipe.engine)

# —— A. 總覽條 ——
st.subheader("總覽")
look_ahead = st.slider("未來賽日窗口（日）", 1, 14, 7, key="ops_look_ahead")
look_back = st.slider("賽後回看（日）", 1, 14, 7, key="ops_look_back")

today = date.today()
fx_up = pipe.list_fixtures(upcoming_only=True)
fx_all = pipe.list_fixtures(upcoming_only=False)

meetings: list[tuple[str, str]] = []
if fx_all is not None and not fx_all.empty:
    for _, r in fx_all.iterrows():
        d = str(r["racing_date"])[:10]
        c = str(r["course"]).upper()
        try:
            dd = date.fromisoformat(d)
        except Exception:
            continue
        if today - timedelta(days=look_back) <= dd <= today + timedelta(days=look_ahead):
            meetings.append((d, c))

# 去重保序
seen = set()
meetings_u = []
for m in meetings:
    if m not in seen:
        seen.add(m)
        meetings_u.append(m)
meetings = meetings_u

bl_counts = bl.summary_counts()
inc_counts = inc.summary_counts()

n_failed = 0
n_waiting = 0
n_pending = 0
n_ok = 0
n_needs = 0
meeting_rows = []

if st.button("刷新多日 readiness", type="primary"):
    st.session_state.pop("ops_center_rows", None)

if "ops_center_rows" not in st.session_state or st.session_state.get(
    "ops_center_meetings"
) != meetings:
    rows_cache = []
    with st.spinner(f"檢查 {len(meetings)} 個 meeting…"):
        for d, c in meetings[:24]:
            try:
                ready = pipe.refresh_readiness(d, c)
            except Exception as e:
                ready = {}
                rows_cache.append(
                    {
                        "racing_date": d,
                        "course": c,
                        "blocker": f"error:{e}",
                        "chain": "—",
                        "needs_human": True,
                        "reason": str(e)[:80],
                    }
                )
                n_needs += 1
                continue
            statuses = {s: (ready.get(s) or {}).get("status") for s, _ in STAGES}
            failed_stages = [s for s, stv in statuses.items() if stv == "failed"]
            waiting_stages = [s for s, stv in statuses.items() if stv == "waiting"]
            pending_stages = [s for s, stv in statuses.items() if stv == "pending"]
            if failed_stages:
                n_failed += 1
            elif waiting_stages:
                n_waiting += 1
            elif pending_stages:
                n_pending += 1
            else:
                n_ok += 1

            # needs_human 簡判（與 OpsIncidentService 規則對齊）
            reasons = []
            if "RACECARD" in failed_stages:
                detail = (ready.get("RACECARD") or {}).get("detail") or ""
                if "錯位" in detail or "corrupt" in detail.lower():
                    reasons.append("排位錯位")
                else:
                    reasons.append("RACECARD failed")
            for s in failed_stages:
                if s != "RACECARD":
                    reasons.append(f"{s} failed")
            blocker = (
                failed_stages[0]
                if failed_stages
                else (
                    waiting_stages[0]
                    if waiting_stages
                    else (pending_stages[0] if pending_stages else "—")
                )
            )
            chain_bits = []
            for s in ("RACECARD", "SPEEDGUIDE", "FORMGUIDE", "FORM_AI", "SNAPSHOT", "RESULTS", "SETTLED"):
                stv = statuses.get(s) or "?"
                icon = {
                    "ok": "🟢",
                    "waiting": "🟡",
                    "pending": "⚪",
                    "failed": "🔴",
                    "skipped_manual": "⏭",
                }.get(stv, "·")
                chain_bits.append(icon)
            needs = bool(reasons)
            if needs:
                n_needs += 1
            rows_cache.append(
                {
                    "racing_date": d,
                    "course": c,
                    "blocker": blocker,
                    "chain": "".join(chain_bits),
                    "needs_human": needs,
                    "reason": "；".join(reasons) if reasons else "",
                    "snapshot": (ready.get("SNAPSHOT") or {}).get("status"),
                    "settled": (ready.get("SETTLED") or {}).get("status"),
                }
            )
    st.session_state["ops_center_rows"] = rows_cache
    st.session_state["ops_center_meetings"] = meetings
    st.session_state["ops_center_stats"] = {
        "ok": n_ok,
        "waiting": n_waiting,
        "pending": n_pending,
        "failed": n_failed,
        "needs": n_needs,
    }

meeting_rows = st.session_state.get("ops_center_rows") or []
stats = st.session_state.get("ops_center_stats") or {}

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("健康／齊備", int(stats.get("ok") or 0))
m2.metric("等待中", int(stats.get("waiting") or 0))
m3.metric("需人工", int(stats.get("needs") or 0))
m4.metric("遺留 open", int(bl_counts.get(STATUS_OPEN) or 0))
m5.metric("介入報告 open", int(inc_counts.get("open") or 0))
m6.metric("視窗 meeting", len(meetings))

st.caption(
    "鏈路圖示順序：排位→SG→FormGuide→FormAI→快照→賽果→結算 "
    "（🟢ok 🟡wait ⚪pending 🔴failed）。詳細介入請開「賽日作戰室」。"
)

# —— B. 賽日流水 ——
st.subheader("賽日流水")
if not meeting_rows:
    st.info("視窗內無 fixtures。請先到作戰室抓取賽期表。")
else:
    df_m = pd.DataFrame(meeting_rows)
    st.dataframe(
        df_m.rename(
            columns={
                "racing_date": "賽日",
                "course": "場地",
                "chain": "鏈路",
                "blocker": "卡點",
                "needs_human": "需人工",
                "reason": "原因",
                "snapshot": "快照",
                "settled": "結算",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

# —— C. 介入報告 ——
st.subheader("開放介入報告")
c_scan, c_ack = st.columns(2)
with c_scan:
    if st.button("掃描 needs_human 並建報告", use_container_width=True):
        with st.spinner("掃描…"):
            out = inc.scan_from_pipeline(
                pipe, meetings=meetings[:12] or None, notify=True
            )
        st.success(
            f"掃描 {out.get('n_meetings')} meeting；報告動作 {out.get('n_report_actions')}"
        )
        st.session_state.pop("ops_center_rows", None)

reports = inc.list_reports(statuses=["open", "acked"], limit=50)
if reports is None or reports.empty:
    st.caption("目前沒有開放介入報告。")
else:
    view = reports.copy()
    for col in (
        "report_id",
        "racing_date",
        "course",
        "stage",
        "reason_code",
        "severity",
        "status",
        "detail",
        "created_at",
        "notify_status",
    ):
        if col not in view.columns:
            view[col] = None
    st.dataframe(
        view[
            [
                "created_at",
                "racing_date",
                "course",
                "stage",
                "reason_code",
                "severity",
                "status",
                "detail",
                "notify_status",
                "report_id",
            ]
        ].rename(
            columns={
                "created_at": "時間",
                "racing_date": "賽日",
                "course": "場地",
                "stage": "階段",
                "reason_code": "原因碼",
                "severity": "嚴重度",
                "status": "狀態",
                "detail": "說明",
                "notify_status": "通知",
                "report_id": "ID",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    rid = st.text_input("解決報告 ID", value="")
    act = st.text_input("處理說明", value="")
    if st.button("標記已解決", disabled=not rid.strip()):
        out = inc.resolve(rid.strip(), action_taken=act, triggered_by="admin")
        st.success(out)
        st.rerun()

# —— D. 遺留佇列 ——
st.subheader("數據遺留佇列")
st.caption(
    f"保留窗預設 **{DEFAULT_RETENTION_DAYS} 日**。"
    "評述到齊後 tick／一鍵遺留鏈可觸發 NLP→因子"
    "（`MEETING_TICK_BACKLOG_AUTO_FACTORS` 預設 true）。"
)

bc1, bc2, bc3, bc4, bc5 = st.columns(5)
bc1.metric("open", int(bl_counts.get(STATUS_OPEN) or 0))
bc2.metric("retrying", int(bl_counts.get(STATUS_RETRYING) or 0))
bc3.metric("done", int(bl_counts.get("done") or 0))
bc4.metric("expired", int(bl_counts.get(STATUS_EXPIRED) or 0))
bc5.metric("skipped", int(bl_counts.get(STATUS_SKIPPED) or 0))

b1, b2, b3 = st.columns(3)
with b1:
    if st.button("重新整理覆蓋", use_container_width=True):
        with st.spinner("對齊覆蓋…"):
            refreshed = bl.refresh_open_coverage(reconcile=True)
        st.success(
            f"已重算 {refreshed.get('n_updated', 0)} 項"
            f"（{refreshed.get('meetings', 0)} meeting）"
        )
with b2:
    if st.button("掃描入列（保留窗）", use_container_width=True):
        with st.spinner("掃描…"):
            cand = bl.candidate_meetings()
            enroll_report = []
            for d, c in cand:
                enroll_report.extend(bl.enroll_meeting(d, c))
        st.success(f"掃描 {len(cand)}；入列動作 {len(enroll_report)}")
with b3:
    if st.button("立即處理到期項", type="primary", use_container_width=True):
        with st.spinner("處理遺留…"):
            report = bl.run_tick_pass(force=True)
        st.write(report.get("counts"))
        nlp = report.get("nlp_pipeline") or {}
        if nlp.get("nlp"):
            st.info(f"NLP：{nlp.get('nlp')}")
        st.success(
            f"處理 {report.get('n_processed')} 項；新寫入 {report.get('new_upserts')} 筆"
        )

show_done = st.checkbox("顯示已完成遺留", value=False)
statuses = [STATUS_OPEN, STATUS_RETRYING, STATUS_EXPIRED, STATUS_SKIPPED]
if show_done:
    statuses.append("done")
df = bl.list_items(statuses=statuses, limit=300)
if df.empty:
    st.caption("目前沒有遺留項目。")
else:
    view = df.copy()
    for col in (
        "racing_date",
        "course",
        "data_kind",
        "status",
        "covered_n",
        "expected_n",
        "coverage",
        "attempt_count",
        "next_attempt_at",
        "detail",
        "last_error",
    ):
        if col not in view.columns:
            view[col] = None
    view["覆蓋"] = view.apply(
        lambda r: f"{int(r['covered_n'] or 0)}/{int(r['expected_n'] or 0)} "
        f"({float(r['coverage'] or 0):.0%})",
        axis=1,
    )
    st.dataframe(
        view[
            [
                "racing_date",
                "course",
                "data_kind",
                "status",
                "覆蓋",
                "attempt_count",
                "next_attempt_at",
                "detail",
                "last_error",
            ]
        ].rename(
            columns={
                "racing_date": "賽日",
                "course": "場地",
                "data_kind": "資料種類",
                "status": "狀態",
                "attempt_count": "嘗試次數",
                "next_attempt_at": "下次重試",
                "detail": "說明",
                "last_error": "錯誤",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("單日遺留操作")
oc1, oc2, oc3 = st.columns(3)
with oc1:
    op_date = st.text_input("賽日 YYYY-MM-DD", value="")
with oc2:
    op_course = st.selectbox("場地", ["ST", "HV"])
with oc3:
    op_kind = st.selectbox("種類", [KIND_RUNNING, KIND_INCIDENT])

b_skip, b_reopen, b_cov, b_chain = st.columns(4)
with b_skip:
    if st.button("略過此項", disabled=not op_date):
        bl.mark_skipped(op_date, op_course, op_kind)
        inc.record_manual_action(
            racing_date=op_date,
            course=op_course,
            stage="NLP",
            action="backlog_skip",
            detail=op_kind,
            notify=False,
        )
        st.success("已標為 skipped_manual")
with b_reopen:
    if st.button("重開此項", disabled=not op_date):
        bl.reopen(op_date, op_course, op_kind)
        st.success("已重開為 open")
with b_cov:
    if st.button("檢查覆蓋", disabled=not op_date):
        st.json(bl.measure_comment_coverage(op_date, op_course, op_kind))
with b_chain:
    if st.button(
        "一鍵遺留鏈",
        disabled=not op_date,
        help="評述同步 → NLP → 因子",
        type="primary",
    ):
        with st.spinner("遺留鏈…"):
            chain = pipe.run_backlog_chain(op_date, op_course)
        inc.record_manual_action(
            racing_date=op_date,
            course=op_course,
            stage="NLP",
            action="run_backlog_chain",
            detail=str(chain.get("error") or "ok")[:500],
            notify=not bool(chain.get("ok")),
        )
        if chain.get("ok"):
            st.success("完成")
            st.json(
                {
                    k: chain.get(k)
                    for k in ("sync", "nlp", "factors")
                    if chain.get(k) is not None
                }
            )
        else:
            st.error(chain.get("error") or chain)

st.caption(
    "CLI：`python ops_incidents.py --scan` ／ `python data_backlog.py --process --json`。"
    "單日深挖 → 賽日作戰室。"
)
