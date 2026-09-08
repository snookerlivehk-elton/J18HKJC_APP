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
            if a1.button("同步 jjjc 排位", key=f"act_rc_sync_{stage}"):
                with st.spinner("jjjc racecard export → upcoming_*…"):
                    r = pipe.run_action(racing_date, course, "sync_jjjc_racecard")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(
                        f"寫入 {r.get('runner_upserted')} 匹／{r.get('race_count')} 場"
                    )
                    st.json(
                        {
                            k: r.get(k)
                            for k in (
                                "ok",
                                "race_ids",
                                "runner_upserted",
                                "source",
                                "detail",
                                "error",
                            )
                            if r.get(k) is not None
                        }
                    )
                else:
                    st.error(r.get("error") or r)
                st.rerun()
            if st.button("備援：重抓 HKJC HTML 排位", key=f"act_rc_html_{stage}"):
                with st.spinner("racecard HTML…"):
                    r = pipe.run_action(racing_date, course, "crawl_racecard")
                st.session_state.pop("ops_ready", None)
                st.json(
                    {
                        k: r.get(k)
                        for k in ("ok", "error", "stdout", "stderr")
                        if k in r or r.get(k)
                    }
                )
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
            if a2.button("重算（含 NLP／干擾）", key=f"act_fac_nlp_{stage}"):
                with st.spinner("factor_scores + interference…"):
                    r = pipe.run_action(racing_date, course, "run_factors_with_nlp")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(r.get("msg"))
                else:
                    st.error(r.get("error"))
                st.rerun()
        elif stage == "FORM_AI":
            only_miss = st.checkbox(
                "只補尚未有結果的馬（取消＝整日重跑）",
                value=True,
                key=f"ai_only_miss_{stage}",
            )
            st.caption(
                "建議用「後台啟動」：關掉手機／換頁也不中斷。"
                "前台「跑 Form AI」仍可用，但必須保持本頁開啟。"
            )
            if a1.button("後台啟動 Form AI", key=f"act_ai_bg_{stage}", type="primary"):
                r = pipe.run_action(
                    racing_date,
                    course,
                    "start_form_ai_background",
                    only_missing=only_miss,
                )
                st.session_state["ops_form_ai_job"] = r.get("job_id")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(r.get("message") or f"job `{r.get('job_id')}`")
                else:
                    st.error(r.get("error") or r)
                    if r.get("job_id"):
                        st.session_state["ops_form_ai_job"] = r.get("job_id")
                st.rerun()
            if a2.button("重新整理進度", key=f"act_ai_stat_{stage}"):
                st.session_state.pop("ops_ready", None)
                st.rerun()
            if a3.button("前台跑（需開頁）", key=f"act_ai_fg_{stage}"):
                prog = st.progress(0.0, text="準備中…")
                line = st.empty()
                detail = st.empty()
                st.warning("請留在本頁至完成；換頁／手機斷線會中斷。建議改用後台啟動。")

                def on_prog(info: dict):
                    ri = int(info.get("race_index") or 1)
                    rn = max(int(info.get("race_count") or 1), 1)
                    hd = int(info.get("horse_done") or 0)
                    ht = max(int(info.get("horse_total") or 0), 1)
                    overall = ((ri - 1) + (hd / ht)) / rn
                    rid = info.get("race_id") or ""
                    hno = info.get("horse_no")
                    res = info.get("result") or {}
                    prog.progress(
                        min(1.0, overall),
                        text=f"場次 {ri}/{rn} · 本場馬 {hd}/{ht}",
                    )
                    line.write(f"**{rid}**")
                    if hno is not None:
                        summary = (res.get("summary") or "")[:48]
                        score = res.get("ai_score")
                        score_s = f"{score:+.2f}" if isinstance(score, (int, float)) else "—"
                        detail.write(f"#{hno}　AI {score_s}　{summary}")

                r = pipe.run_action(
                    racing_date,
                    course,
                    "run_form_ai",
                    only_missing=only_miss,
                    progress_cb=on_prog,
                )
                prog.progress(1.0, text="完成")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(f"完成寫入 {r.get('done')} 匹（共 {r.get('n_races')} 場）")
                else:
                    st.error(r.get("error"))
                st.rerun()

            # 顯示最新後台任務狀態
            st_job = pipe.get_form_ai_job(
                racing_date,
                course,
                job_id=st.session_state.get("ops_form_ai_job"),
            )
            job = (st_job or {}).get("job")
            if job:
                st_status = str(job.get("status") or "")
                prog = job.get("progress_json") or {}
                if isinstance(prog, str):
                    try:
                        import json as _json
                        prog = _json.loads(prog)
                    except Exception:
                        prog = {}
                st.write(
                    f"**後台任務** `{job.get('job_id')}` — **{st_status}**  \n"
                    f"{job.get('detail') or ''}"
                )
                if isinstance(prog, dict) and prog:
                    ri = prog.get("race_index")
                    rn = prog.get("race_count")
                    if ri and rn:
                        st.progress(
                            min(1.0, float(ri) / float(rn)),
                            text=f"場次 {ri}/{rn} · {prog.get('race_id') or ''}",
                        )
                    st.caption(str(prog))
                if st_status in ("ok", "ok_with_errors"):
                    st.success("Form AI 後台已完成；可重新檢查 readiness 後繼續快照。")
                elif st_status == "failed":
                    st.error("後台失敗，請看 detail／Railway log。")
                elif st_status == "running":
                    st.info("進行中——可關閉本頁，稍後回來按「重新整理進度」。")
        elif stage == "SNAPSHOT":
            if a1.button("建立快照", key=f"act_snap_{stage}"):
                with st.spinner("snapshot…"):
                    r = pipe.run_action(racing_date, course, "snapshot")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    msg = r.get("batch_id", r)
                    if r.get("provisional"):
                        st.warning(f"provisional 快照 `{msg}`（{', '.join(r.get('provisional_reasons') or [])}）")
                    else:
                        st.success(msg)
                else:
                    st.error(r.get("error"))
                st.rerun()
            if a2.button("修訂快照 revision", key=f"act_rev_{stage}"):
                with st.spinner("revise snapshot…"):
                    r = pipe.run_action(racing_date, course, "revise_snapshot")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(
                        f"revision `{r.get('batch_id')}` ← `{r.get('revision_of')}`"
                    )
                else:
                    st.error(r.get("error"))
                st.rerun()
        elif stage == "RESULTS":
            if a1.button("同步 jjjc 賽果", key=f"act_res_{stage}"):
                with st.spinner("jjjc results export → runners…"):
                    r = pipe.run_action(racing_date, course, "sync_jjjc_results")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(
                        f"寫入 {r.get('runner_upserted')} 匹／{r.get('race_count')} 場"
                    )
                    st.json(
                        {
                            k: r.get(k)
                            for k in (
                                "ok",
                                "race_ids",
                                "runner_upserted",
                                "payout_upserted",
                                "detail",
                                "error",
                            )
                            if r.get(k) is not None
                        }
                    )
                else:
                    st.error(r.get("error") or r)
                st.rerun()
        elif stage == "SETTLED":
            if a1.button("結算快照", key=f"act_set_{stage}"):
                with st.spinner("settle…"):
                    r = pipe.run_action(racing_date, course, "settle")
                st.session_state["ops_settle_result"] = r
                st.session_state.pop("ops_ready", None)
                st.rerun()
            last = st.session_state.get("ops_settle_result")
            if last:
                msg = last.get("message") or last
                if last.get("settled_batches"):
                    st.success(msg)
                elif last.get("updated_rows"):
                    st.warning(msg)
                else:
                    st.info(msg)
                if last.get("match_stats"):
                    st.caption(f"配對細節：{last.get('match_stats')}")

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
st.caption(
    "RACECARD／RESULTS 優先同步 jjjc（需設 JJJC_API_BASE）；HTML 重抓僅備援。"
    "【重要】NLP／沿路走勢＝可選強化，**不必人工放行**，也不阻擋「建立快照」或「結算快照」。"
    "無評述時干擾通道自動降覆蓋；有評述後再解析→重算干擾→修訂快照即可。"
    "結算只依賴：賽前快照 × 賽果名次（finish_order），與當日走勢評述無關。"
)
