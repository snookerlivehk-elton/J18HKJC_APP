"""
賽日作戰室：單日深挖＋人工介入。

定位（全自動為主）：
  - tick 是主管道；本頁＝查看進度＋需要時一鍵介入
  - 同屏：整備度、一鍵完成階段、遺留鏈（評述→NLP→因子）、爬取資料 drill-down
  - 每次人工放行／略過／一鍵動作 → OpsIncidentService 落報告
"""
from __future__ import annotations

import streamlit as st

from meeting_pipeline import (
    STAGE_HELP,
    STAGE_PRIMARY_ACTION,
    STAGES,
    STATUS_OK,
    STATUS_SKIPPED,
    MeetingPipeline,
)
from ops_incidents import OpsIncidentService
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header(
    "賽日作戰室",
    "單日深挖 · 一鍵完成階段／遺留鏈 · 爬取資料 drill-down（主管道仍是 tick）",
)

pipe = MeetingPipeline()
incidents = OpsIncidentService(engine=pipe.engine)


def _record(
    action: str,
    stage: str,
    detail: str = "",
    *,
    racing_date: str = "",
    course: str = "",
    notify: bool = False,
):
    try:
        incidents.record_manual_action(
            racing_date=racing_date or "",
            course=course or "",
            stage=stage,
            action=action,
            detail=detail,
            notify=notify,
        )
    except Exception:
        pass


# —— 賽期表 ——
st.subheader("① 賽期表 fixtures")
c_fx1, c_fx2 = st.columns([1, 3])
with c_fx1:
    if st.button(
        "抓取本季賽期表",
        type="primary",
        use_container_width=True,
        help=STAGE_HELP.get("FIXTURE", ""),
    ):
        with st.spinner("解析 HKJC Fixture.aspx …"):
            out = pipe.run_action("", "", "crawl_fixtures")
        _record(
            "crawl_fixtures",
            "FIXTURE",
            str(out.get("saved") or out.get("error") or ""),
        )
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

def _rec(action: str, stage: str, detail: str = "", *, notify: bool = False):
    _record(
        action,
        stage,
        detail,
        racing_date=racing_date,
        course=course,
        notify=notify,
    )

st.divider()
st.subheader(f"② 整備度 — {racing_date} {course}")
st.caption(
    "主管道是 `meeting_tick` Cron。此處只在 needs_human／失敗時介入："
    "「一鍵完成」跑該階段主路徑；「人工放行／略過」會寫入營運報告。"
)

b1, b2, b3 = st.columns(3)
with b1:
    do_refresh = st.button("重新檢查 readiness", use_container_width=True)
with b2:
    if st.button(
        "一鍵遺留鏈（評述→NLP→因子）",
        use_container_width=True,
        type="primary",
        help="同步 jjjc text-reports → NLP 解析 → 重算因子（含干擾）。評述遲到補齊用。",
    ):
        with st.spinner("遺留鏈執行中…"):
            chain = pipe.run_backlog_chain(racing_date, course)
        _rec(
            "run_backlog_chain",
            "NLP",
            detail=str(chain.get("error") or chain.get("sync") or "")[:500],
            notify=not bool(chain.get("ok")),
        )
        st.session_state.pop("ops_ready", None)
        if chain.get("ok"):
            st.success("遺留鏈完成")
            st.json(
                {
                    k: chain.get(k)
                    for k in ("sync", "nlp", "factors", "enroll", "nlp_note")
                    if chain.get(k) is not None
                }
            )
        else:
            st.error(chain.get("error") or chain)
        st.rerun()
with b3:
    if st.button("掃描／建立介入報告", use_container_width=True):
        ready_now = pipe.refresh_readiness(racing_date, course)
        created = incidents.evaluate_meeting_needs_human(
            racing_date, course, ready_now, notify=True
        )
        st.session_state["ops_ready"] = ready_now
        n_new = sum(1 for x in created if x.get("created"))
        st.info(f"報告動作 {len(created)}（新建 {n_new}）")

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
    help_txt = STAGE_HELP.get(stage, "")
    primary = STAGE_PRIMARY_ACTION.get(stage)
    with st.expander(
        f"{icon} **{label}** (`{stage}`) — {st_status}",
        expanded=(st_status in ("failed", "pending", "waiting")),
    ):
        if help_txt:
            st.caption(help_txt)
        st.write(detail)
        a1, a2, a3, a4, a5 = st.columns(5)

        if primary and stage != "FIXTURE":
            if a1.button(
                "一鍵完成此階段",
                key=f"oneclick_{stage}",
                type="primary",
                help=f"主路徑：`{primary}`。{help_txt}",
            ):
                with st.spinner(f"{label}…"):
                    r = pipe.complete_stage(racing_date, course, stage)
                _rec(
                    f"complete_stage:{primary}",
                    stage,
                    detail=str(r.get("error") or r.get("msg") or r.get("message") or "")[:500],
                    notify=not bool(r.get("ok")),
                )
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(r.get("msg") or r.get("message") or "完成")
                else:
                    st.error(r.get("error") or r)
                st.rerun()

        # 節點細部動作（保留備援）
        if stage == "RACECARD":
            if a2.button(
                "同步 jjjc 排位",
                key=f"act_rc_sync_{stage}",
                help="GET jjjc /api/export/racecard → upcoming_*",
            ):
                with st.spinner("jjjc racecard export → upcoming_*…"):
                    r = pipe.run_action(racing_date, course, "sync_jjjc_racecard")
                _rec("sync_jjjc_racecard", stage, str(r.get("error") or ""))
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(
                        f"寫入 {r.get('runner_upserted')} 匹／{r.get('race_count')} 場"
                    )
                else:
                    st.error(r.get("error") or r)
                st.rerun()
            if st.button(
                "備援：重抓 HKJC HTML 排位",
                key=f"act_rc_html_{stage}",
                help="僅在 jjjc 錯位／不可用時使用",
            ):
                with st.spinner("racecard HTML…"):
                    r = pipe.run_action(racing_date, course, "crawl_racecard")
                _rec("crawl_racecard", stage, str(r.get("error") or ""))
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
            if a2.button(
                "重抓 SG",
                key=f"act_sg_{stage}",
                help="JJJC 主路徑；空殼／waiting 會打 CMS 備援",
            ):
                with st.spinner("speedguide（JJJC→CMS）…"):
                    r = pipe.run_action(
                        racing_date,
                        course,
                        "crawl_speedguide",
                        force_fallback=True,
                    )
                _rec("crawl_speedguide", stage, str(r.get("error") or ""))
                st.session_state.pop("ops_ready", None)
                st.json(
                    {
                        k: r.get(k)
                        for k in ("ok", "error", "stdout", "stderr", "source", "jjjc")
                        if r.get(k) is not None
                    }
                )
                st.rerun()
        elif stage == "FORMGUIDE":
            if a2.button("重抓 Form Guide", key=f"act_fg_{stage}", help=help_txt):
                with st.spinner("formguide…"):
                    r = pipe.run_action(racing_date, course, "crawl_formguide")
                _rec("crawl_formguide", stage, str(r.get("error") or ""))
                st.session_state.pop("ops_ready", None)
                st.json(
                    {
                        k: r.get(k)
                        for k in ("ok", "error", "stdout", "stderr", "source")
                        if r.get(k) is not None
                    }
                )
                st.rerun()
        elif stage == "FACTORS":
            if a2.button(
                "重算因子",
                key=f"act_fac_{stage}",
                help="基礎因子；不含 NLP 干擾通道",
            ):
                with st.spinner("factor_scores…（較久）"):
                    r = pipe.run_action(racing_date, course, "run_factors")
                _rec("run_factors", stage, str(r.get("error") or r.get("msg") or ""))
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(r.get("msg"))
                else:
                    st.error(r.get("error"))
                st.rerun()
            if a3.button(
                "重算（含 NLP／干擾）",
                key=f"act_fac_nlp_{stage}",
                help="有評述解析後才有意義",
            ):
                with st.spinner("factor_scores + interference…"):
                    r = pipe.run_action(racing_date, course, "run_factors_with_nlp")
                _rec(
                    "run_factors_with_nlp",
                    stage,
                    str(r.get("error") or r.get("msg") or ""),
                )
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(r.get("msg"))
                else:
                    st.error(r.get("error"))
                st.rerun()
        elif stage == "NLP":
            st.caption("NLP 為可選；一鍵遺留鏈見上方按鈕，或本階段「一鍵完成」。")
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
            if a2.button(
                "後台啟動 Form AI",
                key=f"act_ai_bg_{stage}",
                help="subprocess 背景跑；進度寫 background_jobs",
            ):
                r = pipe.run_action(
                    racing_date,
                    course,
                    "start_form_ai_background",
                    only_missing=only_miss,
                )
                _rec("start_form_ai_background", stage, str(r.get("job_id") or r.get("error") or ""))
                st.session_state["ops_form_ai_job"] = r.get("job_id")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(r.get("message") or f"job `{r.get('job_id')}`")
                else:
                    st.error(r.get("error") or r)
                    if r.get("job_id"):
                        st.session_state["ops_form_ai_job"] = r.get("job_id")
                st.rerun()
            if a3.button("重新整理進度", key=f"act_ai_stat_{stage}"):
                st.session_state.pop("ops_ready", None)
                st.rerun()
            if a4.button(
                "前台跑（需開頁）",
                key=f"act_ai_fg_{stage}",
                help="必須留在本頁；手機斷線會中斷",
            ):
                prog = st.progress(0.0, text="準備中…")
                line = st.empty()
                detail_box = st.empty()
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
                        score_s = (
                            f"{score:+.2f}" if isinstance(score, (int, float)) else "—"
                        )
                        detail_box.write(f"#{hno}　AI {score_s}　{summary}")

                r = pipe.run_action(
                    racing_date,
                    course,
                    "run_form_ai",
                    only_missing=only_miss,
                    progress_cb=on_prog,
                )
                _rec("run_form_ai", stage, str(r.get("error") or r.get("done") or ""))
                prog.progress(1.0, text="完成")
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(f"完成寫入 {r.get('done')} 匹（共 {r.get('n_races')} 場）")
                else:
                    st.error(r.get("error"))
                st.rerun()

            st_job = pipe.get_form_ai_job(
                racing_date,
                course,
                job_id=st.session_state.get("ops_form_ai_job"),
            )
            job = (st_job or {}).get("job")
            if job:
                js = str(job.get("status") or "")
                prog = job.get("progress_json") or {}
                if isinstance(prog, str):
                    try:
                        import json as _json

                        prog = _json.loads(prog)
                    except Exception:
                        prog = {}
                st.write(
                    f"**後台任務** `{job.get('job_id')}` — **{js}**  \n"
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
                if js in ("ok", "ok_with_errors"):
                    st.success("Form AI 後台已完成；可重新檢查 readiness 後繼續快照。")
                elif js == "failed":
                    st.error("後台失敗，請看 detail／Railway log。")
                elif js == "running":
                    st.info("進行中——可關閉本頁，稍後回來按「重新整理進度」。")
        elif stage == "SNAPSHOT":
            if a2.button("建立快照", key=f"act_snap_{stage}", help=help_txt):
                with st.spinner("snapshot…"):
                    r = pipe.run_action(racing_date, course, "snapshot")
                _rec("snapshot", stage, str(r.get("batch_id") or r.get("error") or ""))
                st.session_state.pop("ops_ready", None)
                st.session_state["ops_snapshot_result"] = r
                st.rerun()
            if a3.button(
                "修訂快照 revision",
                key=f"act_rev_{stage}",
                help="資料到位後追加 revision，不覆寫已結算",
            ):
                with st.spinner("revise snapshot…"):
                    r = pipe.run_action(racing_date, course, "revise_snapshot")
                _rec(
                    "revise_snapshot",
                    stage,
                    str(r.get("batch_id") or r.get("error") or ""),
                )
                st.session_state.pop("ops_ready", None)
                st.session_state["ops_snapshot_result"] = r
                st.rerun()
            last_snap = st.session_state.get("ops_snapshot_result")
            if last_snap:
                if last_snap.get("ok"):
                    msg = last_snap.get("batch_id", last_snap)
                    if last_snap.get("provisional"):
                        st.warning(
                            f"provisional 快照 `{msg}`（{', '.join(last_snap.get('provisional_reasons') or [])}）"
                        )
                    elif last_snap.get("revision_of"):
                        st.success(
                            f"revision `{msg}` ← `{last_snap.get('revision_of')}`"
                        )
                    else:
                        st.success(f"快照 `{msg}`")
                    ad = last_snap.get("ad_output") or {}
                    if ad.get("ok") or ad.get("races_written"):
                        st.info(
                            f"廣告輸出：全賽日 {ad.get('races_written', ad.get('n_races', 0))} 場 → "
                            f"2 張海報 · 模型 {int(ad.get('model_bytes') or 0) // 1024}KB / "
                            f"AI {int(ad.get('ai_bytes') or 0) // 1024}KB · "
                            f"`{ad.get('output_dir', '')}`（營運 → 廣告輸出）"
                        )
                    elif ad.get("error"):
                        st.caption(f"廣告輸出略過／失敗：{ad.get('error')}")
                else:
                    st.error(last_snap.get("error"))
        elif stage == "RESULTS":
            if a2.button(
                "同步 jjjc 賽果",
                key=f"act_res_{stage}",
                help="名次／派彩入庫；結算依賴此步",
            ):
                with st.spinner("jjjc results export → runners…"):
                    r = pipe.run_action(racing_date, course, "sync_jjjc_results")
                _rec("sync_jjjc_results", stage, str(r.get("error") or ""))
                st.session_state.pop("ops_ready", None)
                if r.get("ok"):
                    st.success(
                        f"寫入 {r.get('runner_upserted')} 匹／{r.get('race_count')} 場"
                    )
                else:
                    st.error(r.get("error") or r)
                st.rerun()
        elif stage == "SETTLED":
            if a2.button("結算快照", key=f"act_set_{stage}", help=help_txt):
                with st.spinner("settle…"):
                    r = pipe.run_action(racing_date, course, "settle")
                _rec("settle", stage, str(r.get("message") or r.get("error") or ""))
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

        if a5.button(
            "人工放行 OK",
            key=f"ok_{stage}",
            help="標記本階段已人工確認；tick 不會覆蓋 manual_override",
        ):
            pipe.set_stage(
                racing_date, course, stage, STATUS_OK, "人工放行", manual=True
            )
            _rec("manual_ok", stage, "人工放行")
            st.session_state.pop("ops_ready", None)
            st.rerun()
        if st.button(
            "標記略過",
            key=f"skip_{stage}",
            help="略過本階段；寫入營運報告",
        ):
            pipe.set_stage(
                racing_date, course, stage, STATUS_SKIPPED, "人工略過", manual=True
            )
            _rec("manual_skip", stage, "人工略過", notify=True)
            st.session_state.pop("ops_ready", None)
            st.rerun()
        if st.button(
            "清除覆寫",
            key=f"clr_{stage}",
            help="清除人工放行／略過，恢復自動判定",
        ):
            pipe.set_stage(racing_date, course, stage, "pending", "", manual=False)
            _rec("clear_override", stage, "清除覆寫")
            st.session_state.pop("ops_ready", None)
            st.rerun()

st.divider()
st.subheader(f"③ 爬取資料 drill-down — {racing_date} {course}")
st.caption("選場次 → 看馬匹列（檔位／騎練／SG）。用來核對錯位或覆蓋缺口。")
races = pipe.list_meeting_races(racing_date, course)
if races is None or races.empty:
    st.info("尚無排位場次。請先完成 RACECARD 同步。")
else:
    race_labels = [
        f"R{int(r.race_num):02d} · {r.race_id}（{int(r.runner_n or 0)} 匹）"
        for r in races.itertuples()
    ]
    race_pick = st.selectbox("選擇場次", race_labels, key="ops_race_pick")
    race_row = races.iloc[race_labels.index(race_pick)]
    runners = pipe.list_race_runners(str(race_row["race_id"]))
    if runners is None or runners.empty:
        st.warning("此場無馬匹列。")
    else:
        show_cols = [
            c
            for c in (
                "horse_no",
                "horse_name",
                "draw",
                "jockey_name",
                "trainer_name",
                "handicap_weight",
                "rating",
                "speed_energy",
                "speed_energy_delta",
                "form_rating",
            )
            if c in runners.columns
        ]
        st.dataframe(
            runners[show_cols],
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.subheader(f"④ 數據遺留 — {racing_date} {course}")
st.caption(
    "沿途走勢（corunning／running_comment）或競賽報告（racereport／incident_report）"
    "未齊時入遺留清單。多日總覽見「數據營運中心」。"
)
try:
    from data_backlog import (
        KIND_INCIDENT,
        KIND_RUNNING,
        DataBacklogService,
    )

    bl = DataBacklogService(engine=pipe.engine)
    bl_rows = bl.list_items(racing_date=racing_date, course=course, limit=20)
    cov_rc = bl.measure_comment_coverage(racing_date, course, KIND_RUNNING)
    cov_inc = bl.measure_comment_coverage(racing_date, course, KIND_INCIDENT)
    bc1, bc2, bc3 = st.columns(3)
    bc1.metric(
        "沿途評述覆蓋（corunning）",
        f"{cov_rc.get('covered_n', 0)}/{cov_rc.get('expected_n', 0)}",
        f"{int(cov_rc.get('race_n') or 0)}場 · {float(cov_rc.get('coverage') or 0):.0%}",
    )
    bc2.metric(
        "競賽報告覆蓋（racereport）",
        f"{cov_inc.get('covered_n', 0)}/{cov_inc.get('expected_n', 0)}",
        f"{int(cov_inc.get('race_n') or 0)}場 · {float(cov_inc.get('coverage') or 0):.0%}",
    )
    with bc3:
        if st.button(
            "入列／刷新本賽日遺留",
            use_container_width=True,
            help="依覆蓋門檻把缺口寫入 data_backlog",
        ):
            out = bl.enroll_meeting(racing_date, course)
            _rec("enroll_backlog", "NLP", str(out)[:500])
            st.success(out)
            st.rerun()
    if bl_rows is not None and not bl_rows.empty:
        st.dataframe(
            bl_rows[
                [
                    c
                    for c in (
                        "data_kind",
                        "status",
                        "covered_n",
                        "expected_n",
                        "coverage",
                        "attempt_count",
                        "next_attempt_at",
                        "detail",
                    )
                    if c in bl_rows.columns
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("本賽日暫無遺留列（無名次母體或已達標／未入列）。")
except Exception as e:
    st.warning(f"遺留清單暫不可用：{e}")

st.divider()
st.caption(
    "RACECARD／RESULTS 優先同步 jjjc（需設 JJJC_API_BASE）；HTML 重抓僅備援。"
    "【重要】NLP／沿路走勢＝可選強化，**不必人工放行**，也不阻擋「建立快照」或「結算快照」。"
    "無評述時干擾通道自動降覆蓋；有評述後再解析→重算干擾→修訂快照即可。"
    "結算只依賴：賽前快照 × 賽果名次（finish_order），與當日走勢評述無關。"
    "多日總覽／開放介入報告 →「數據營運中心」。"
)
