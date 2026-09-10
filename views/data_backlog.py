"""數據遺留清單 — 延遲入庫（沿途走勢／事故報告等）操作員視圖。"""
from __future__ import annotations

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
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header(
    "數據遺留清單",
    "沿途走勢／事故報告等可能賽後多日才上架；此頁列出尚未入庫項目，供操作員監看。",
)

svc = DataBacklogService()

counts = svc.summary_counts()
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("待補 open", int(counts.get(STATUS_OPEN) or 0))
m2.metric("重試中", int(counts.get(STATUS_RETRYING) or 0))
m3.metric("已完成", int(counts.get("done") or 0))
m4.metric("已過期", int(counts.get(STATUS_EXPIRED) or 0))
m5.metric("人工略過", int(counts.get(STATUS_SKIPPED) or 0))

st.caption(
    f"保留窗預設 **{DEFAULT_RETENTION_DAYS} 日**（`MEETING_TICK_BACKLOG_RETENTION_DAYS`）。"
    "覆蓋門檻預設 80%。名次鏈不受評述遲到影響；評述到齊後 tick 可觸發 NLP。"
)

c1, c2, c3 = st.columns(3)
with c1:
    do_refresh = st.button("重新整理", use_container_width=True)
with c2:
    do_enroll = st.button("掃描入列（保留窗）", use_container_width=True)
with c3:
    do_process = st.button("立即處理到期項", type="primary", use_container_width=True)

if do_enroll:
    with st.spinner("掃描保留窗內賽日…"):
        meetings = svc.candidate_meetings()
        enroll_report = []
        for d, c in meetings:
            enroll_report.extend(svc.enroll_meeting(d, c))
        counts2 = svc.summary_counts()
    st.success(
        f"掃描 {len(meetings)} 個 meeting；入列動作 {len(enroll_report)}；"
        f"目前 open={counts2.get('open', 0)}"
    )

if do_process:
    with st.spinner("同步 JJJC text-reports 並更新覆蓋…"):
        report = svc.run_tick_pass(force=True)
    st.write(report.get("counts"))
    nlp = report.get("nlp_pipeline") or {}
    if nlp.get("nlp"):
        st.info(f"NLP：{nlp.get('nlp')}")
    st.success(
        f"處理 {report.get('n_processed')} 項；新寫入評述 {report.get('new_upserts')} 筆"
    )
    st.session_state.pop("backlog_df", None)

show_done = st.checkbox("顯示已完成", value=False)
statuses = [STATUS_OPEN, STATUS_RETRYING, STATUS_EXPIRED, STATUS_SKIPPED]
if show_done:
    statuses.append("done")

df = svc.list_items(statuses=statuses, limit=300)
if df.empty:
    st.info("目前沒有遺留項目。有賽果後若評述未齊，系統會在 tick 自動入列。")
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
st.subheader("單日操作")
oc1, oc2, oc3, oc4 = st.columns(4)
with oc1:
    op_date = st.text_input("賽日 YYYY-MM-DD", value="")
with oc2:
    op_course = st.selectbox("場地", ["ST", "HV"])
with oc3:
    op_kind = st.selectbox("種類", [KIND_RUNNING, KIND_INCIDENT])
with oc4:
    st.write("")
    st.write("")

b_skip, b_reopen, b_cov = st.columns(3)
with b_skip:
    if st.button("略過此項", disabled=not op_date):
        svc.mark_skipped(op_date, op_course, op_kind)
        st.success("已標為 skipped_manual")
with b_reopen:
    if st.button("重開此項", disabled=not op_date):
        svc.reopen(op_date, op_course, op_kind)
        st.success("已重開為 open")
with b_cov:
    if st.button("檢查覆蓋", disabled=not op_date):
        cov = svc.measure_comment_coverage(op_date, op_course, op_kind)
        st.json(cov)

st.caption(
    "CLI：`python data_backlog.py --list` ／ `python data_backlog.py --process --json`"
)
