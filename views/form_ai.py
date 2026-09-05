"""
賽績指引爬取 + 賽前 AI 評價／獨立評分。
"""
from __future__ import annotations

import os
import subprocess

import streamlit as st
import pandas as pd

from inference_engine import InferenceEngine
from form_ai_analyst import FormAIAnalyst
import ui_utils
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header("賽績指引 + AI 評價", "獨立馬評軌道（不混入模型總分）")
st.caption(
    "CMS Form Guide 近績文字 + 系統量化統計 → 文字評價與 AI 獨立分（−2～+2）。"
    "可重用、進賽日速覽並排推介。長任務請留在本頁。"
)

engine = InferenceEngine()
analyst = FormAIAnalyst()

st.subheader("① 抓取官方賽績指引（CMS）")
c1, c2, c3 = st.columns(3)
with c1:
    fg_date = st.text_input("核對日期 YYYY/MM/DD", value="2026/09/06")
with c2:
    fg_course = st.selectbox("核對場地", ["ST", "HV"])
with c3:
    st.write("")
    st.write("")
    if st.button("抓取 Form Guide", type="primary"):
        with st.spinner("抓取中…"):
            env = os.environ.copy()
            try:
                r = subprocess.run(
                    ["python", "formguide_crawler.py", "--date", fg_date, "--course", fg_course],
                    capture_output=True, text=True, check=True, env=env,
                )
                st.success("完成")
                with st.expander("日誌"):
                    st.text(r.stdout or "")
            except subprocess.CalledProcessError as e:
                st.error(e.stderr or e.stdout)

races = engine.get_upcoming_races()
if races.empty:
    st.warning("無排位賽事")
    st.stop()

opts = ui_utils.get_upcoming_races_list()
race_opts = [o for o in opts if o[0] != "None"]
selected = st.selectbox(
    "② 選擇場次做 AI 評價",
    options=[o[0] for o in race_opts],
    format_func=lambda x: next(o[1] for o in race_opts if o[0] == x),
)

forms = analyst.load_formguide(selected)
st.caption(f"本場 Form Guide 已入庫：{len(forms)} 匹" if not forms.empty else "本場尚無 Form Guide，請先抓取。")

st.subheader("③ 執行 AI 分析")
if not analyst.is_ready():
    st.error("未設定 OPENAI_API_KEY（環境變數）。")
else:
    only_missing = st.checkbox("只處理尚未有 AI 結果的馬（取消＝本場全部重跑）", value=True)
    if st.button("分析本場全部馬匹", type="primary"):
        st.info("請留在本頁至進度完成；換頁會中斷分析。")
        prog = st.progress(0.0, text="準備中…")
        status = st.empty()
        detail = st.empty()

        def cb(done, total, hno, res):
            tot = max(int(total or 0), 1)
            cur = int(done or 0)
            frac = 0.0 if tot == 0 else min(1.0, cur / tot)
            prog.progress(frac, text=f"進度 {cur}/{total or 0}")
            if hno is None:
                status.write("無需處理（已全部存在或無馬匹）")
                return
            summary = ""
            score_s = "—"
            if isinstance(res, dict):
                summary = (res.get("summary") or "")[:56]
                sc = res.get("ai_score")
                if isinstance(sc, (int, float)):
                    score_s = f"{sc:+.2f}"
            status.write(f"正在／剛完成 **#{hno}**　AI {score_s}")
            if summary:
                detail.caption(summary)

        out = analyst.analyze_race(selected, only_missing=only_missing, progress_cb=cb)
        prog.progress(1.0, text="完成")
        if out.get("ok"):
            msg = f"新寫入 {out['done']} 匹"
            if out.get("skipped"):
                msg += f"（略過已有 {out['skipped']}）"
            st.success(msg)
            if out.get("errors"):
                st.warning(str(out["errors"][:5]))
        else:
            st.error(out.get("error"))

ai_df = analyst.load_ai_for_race(selected)
if ai_df.empty:
    st.info("尚無 AI 結果。")
else:
    show = ai_df[["horse_no", "ai_score", "confidence", "summary"]].rename(
        columns={
            "horse_no": "馬號",
            "ai_score": "AI分",
            "confidence": "信心",
            "summary": "評價",
        }
    )
    st.dataframe(show, use_container_width=True, hide_index=True, height=480)
