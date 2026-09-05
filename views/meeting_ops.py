"""
賽日作戰室：fixtures → readiness 各節點 → 手動覆寫／重跑。
"""
from __future__ import annotations

import streamlit as st

from meeting_pipeline import MeetingPipeline, STAGES, STATUS_OK, STATUS_SKIPPED
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header("賽日作戰室", "賽期表 → 整備度 → 手動重跑／放行")

pipe = MeetingPipeline()

# —— 賽期表 ——
st.subheader("① 賽期表 fixtures")
c_fx1, c_fx2 = st.columns([1, 3])
with c_fx1:
    if st.button("抓取本季賽期表", type="primary", use_container_width=True):
        with st.spinner("解析 HKJC Fixture.aspx …"):
            out = pipe.run_action("", "", "crawl_fixtures")
        if out.get("ok"):
            st.success(f"寫入／更新 {out.get('saved')} 筆（解析 {out.get('parsed')}）")
        else:
            st.error(out.get("error") or out)
with c_fx2:
    show_all = st.checkbox("顯示整季（含已過賽日）", value=False)

fx = pipe.list_fixtures(upcoming_only=not show_all)
if fx.empty:
    st.warning("尚無 fixtures。請先抓取賽期表。")
    st.stop()

fx = fx.copy()
dow = fx["day_of_week"].astype(str) if "day_of_week" in fx.columns else ""
sess = fx["session"].astype(str) if "session" in fx.columns else ""
fx["_label"] = (
    fx["racing_date"].astype(str).str[:10]
    + " "
    + fx["course"].astype(str)
    + "（"
    + dow
    + " "
    + sess
    + "）"
)
labels = fx["_label"].tolist()
pick = st.selectbox("選擇賽日", labels, index=0)
row = fx[fx["_label"] == pick].iloc[0]
racing_date = str(row["racing_date"])[:10]
course = str(row["course"])

st.divider()
st.subheader(f"② 整備度 — {racing_date} {course}")

b1, b2, b3 = st.columns(3)
with b1:
    do_refresh = st.button("重新檢查 readiness", use_container_width=True)
with b2:
    st.write("")
with b3:
    st.write("")

if do_refresh or "ops_ready" not in st.session_state:
    with st.spinner("檢查各階段…"):
        st.session_state["ops_ready"] = pipe.refresh_readiness(racing_date, course)
        st.session_state["ops_key"] = f"{racing_date}_{course}"

if st.session_state.get("ops_key") != f"{racing_date}_{course}":
    with st.spinner("檢查各階段…"):
        st.session_state["ops_ready"] = pipe.refresh_readiness(racing_date, course)
        st.session_state["ops_key"] = f"{racing_date}_{course}"

ready = st.session_state["ops_ready"]
status_icon = {
    "ok": "✅",
    "pending": "⏳",
    "waiting": "🕐",
    "failed": "❌",
    "skipped_manual": "⏭",
}

for stage, label in STAGES:
    info = ready.get(stage) or {"status": "pending", "detail": ""}
    st_status = info.get("status", "pending")
    detail = info.get("detail", "")
    icon = status_icon.get(st_status, "•")
    with st.expander(f"{icon} **{label}** (`{stage}`) — {st_status}", expanded=(st_status in ("failed", "pending", "waiting"))):
        st.write(detail)
        a1, a2, a3, a4 = st.columns(4)

        # 節點動作
        if stage == "RACECARD":
            if a1.button("重抓排位", key=f"act_rc_{stage}"):
                with st.spinner("racecard…"):
                    r = pipe.run_action(racing_date, course, "crawl_racecard")
                st.session_state.pop("ops_ready", None)
                st.json({k: r.get(k) for k in ("ok", "error", "stdout", "stderr") if k in r or r.get(k)})
                st.rerun()
        elif stage == "SPEEDGUIDE":
            if a1.button("重抓 SG", key=f"act_sg_{stage}"):
                with st.spinner("speedguide…"):
                    r = pipe.run_action(racing_date, course, "crawl_speedguide")
                st.session_state.pop("ops_ready", None)
                st.json({k: r.get(k) for k in ("ok", "error", "stdout", "stderr") if r.get(k) is not None})
                st.rerun()
        elif stage == "FORMGUIDE":
            if a1.button("重抓 Form Guide", key=f"act_fg_{stage}"):
                with st.spinner("formguide…"):
                    r = pipe.run_action(racing_date, course, "crawl_formguide")
                st.session_state.pop("ops_ready", None)
                st.json({k: r.get(k) for k in ("ok", "error", "stdout", "stderr") if r.get(k) is not None})
                st.rerun()
        elif stage == "FACTORS":
            if a1.button("重算因子", key=f"act_fac_{stage}"):
                with st.spinner("factor_scores…（較久）"):
                    r = pipe.run_action(racing_date, course, "run_factors")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(r.get("msg"))
                else:
                    st.error(r.get("error"))
                st.rerun()
        elif stage == "FORM_AI":
            if a1.button("跑 Form AI", key=f"act_ai_{stage}"):
                with st.spinner("OpenAI Form AI…"):
                    r = pipe.run_action(racing_date, course, "run_form_ai")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(f"完成 {r.get('done')} 匹")
                else:
                    st.error(r.get("error"))
                st.rerun()
        elif stage == "SNAPSHOT":
            if a1.button("建立快照", key=f"act_snap_{stage}"):
                with st.spinner("snapshot…"):
                    r = pipe.run_action(racing_date, course, "snapshot")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(r.get("batch_id", r))
                else:
                    st.error(r.get("error"))
                st.rerun()
        elif stage == "SETTLED":
            if a1.button("結算快照", key=f"act_set_{stage}"):
                with st.spinner("settle…"):
                    r = pipe.run_action(racing_date, course, "settle")
                st.session_state.pop("ops_ready", None)
                st.info(r)
                st.rerun()

        if a2.button("人工放行 OK", key=f"ok_{stage}"):
            pipe.set_stage(racing_date, course, stage, STATUS_OK, "人工放行", manual=True)
            st.session_state.pop("ops_ready", None)
            st.rerun()
        if a3.button("標記略過", key=f"skip_{stage}"):
            pipe.set_stage(racing_date, course, stage, STATUS_SKIPPED, "人工略過", manual=True)
            st.session_state.pop("ops_ready", None)
            st.rerun()
        if a4.button("清除覆寫", key=f"clr_{stage}"):
            pipe.set_stage(racing_date, course, stage, "pending", "", manual=False)
            st.session_state.pop("ops_ready", None)
            st.rerun()

st.divider()
st.caption("NLP／賽果節點多為可選或賽後；官方 SG 未上架時狀態為 waiting，不必強行失敗。")
