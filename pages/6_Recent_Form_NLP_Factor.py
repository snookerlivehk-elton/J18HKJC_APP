import streamlit as st
import os
import pandas as pd
from config import ModelConfig
from nlp_processor import NLPProcessor, DEFAULT_SYSTEM_PROMPT
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="近績與 NLP 因子", layout="wide")
st.title("📉🤖 近績與 NLP 因子 (Recent Form & NLP)")
st.caption(
    "基礎近績 = 馬匹在**距離帶粗桶**（如 ST_SPRINT）的歷史表現；"
    "NLP 受阻補償寫回 raw_score 後再算 Z（需先解析 text_reports）。"
)

if not ui_utils.ensure_history_loaded():
    st.stop()

col1, col2 = st.columns([1, 2])
with col1:
    with st.expander("⚙️ 參數調節", expanded=False):
        ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
        ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
        ModelConfig.HORSE_SMOOTH_C = st.number_input(
            "HORSE_SMOOTH_C", min_value=1, value=ModelConfig.HORSE_SMOOTH_C
        )
        decay_str = st.text_input(
            "HORSE_DECAY", value=",".join(map(str, ModelConfig.HORSE_DECAY))
        )
        ModelConfig.HORSE_DECAY = [float(x.strip()) for x in decay_str.split(",")]
        ModelConfig.EXCUSE_MULTIPLIER_EARLY = st.slider(
            "早段受阻補償", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_EARLY, 0.1
        )
        ModelConfig.EXCUSE_MULTIPLIER_MIDDLE = st.slider(
            "中段受阻補償", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_MIDDLE, 0.1
        )
        ModelConfig.EXCUSE_MULTIPLIER_LATE = st.slider(
            "直路受阻補償", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_LATE, 0.1
        )

with col2:
    with st.expander("🧠 LLM 設定（只用環境變數，不在畫面輸入 Key）", expanded=False):
        processor = NLPProcessor()
        if processor.is_ready():
            st.success("OPENAI_API_KEY：已從環境變數讀取（Railway Variables）")
        else:
            st.error("未偵測到 OPENAI_API_KEY。請在 Railway → Variables 設定後重新部署。")
        st.caption(f"目前模型：`{processor.model}`（可用 OPENAI_MODEL 覆寫）")
        st.caption(f"端點：`{processor.base_url}`（OpenRouter 請設 OPENAI_BASE_URL）")
        system_prompt = st.text_area("System Prompt", value=DEFAULT_SYSTEM_PROMPT, height=160)
        apply_nlp_on_compute = st.checkbox(
            "計算近績時套用已解析的 NLP 受阻補償",
            value=True,
            help="僅使用資料庫中已有 nlp_result 的報告；未解析的場次不補償。",
        )

st.divider()
st.subheader("📊 馬匹基礎近績（距離帶粗桶）")

can_compute = "raw_df" in st.session_state and not st.session_state["raw_df"].empty
if st.button("🚀 計算並寫入馬匹近績因子", type="primary", disabled=not can_compute):
    with st.spinner("計算中（距離帶 + 可選 NLP 補償）..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state["raw_df"].copy())
        h_df = calc.calculate_horse_factor(df, apply_nlp=apply_nlp_on_compute)
        if h_df.empty:
            st.error("無法計算近績（無有效歷史）。")
        else:
            n = calc.save_factor_scores(h_df)
            st.session_state["h_df_indep"] = h_df
            excused = 0
            if apply_nlp_on_compute:
                emap = calc.load_excuse_map()
                excused = len(emap)
            st.success(
                f"完成：{len(h_df)} 筆近績（已寫入 factor_scores {n} 列）；"
                f"可用 NLP 受阻 runner 數：{excused}"
            )

h_df = ui_utils.load_factor_from_db_or_session("h_df_indep", "HORSE")
if not h_df.empty:
    st.session_state["h_df_indep"] = h_df
    ui_utils.render_upcoming_match_panel(
        h_df, match_mode="horse", entity_label="匹配馬名", key_prefix="horse_form"
    )
else:
    st.info("尚未有近績因子。請先載入歷史後按上方計算。")

st.divider()
st.subheader("📝 NLP 解析（歷史報告 → 寫入 nlp_result）")

calc = FactorCalculator()
status = calc.nlp_status()
c1, c2, c3 = st.columns(3)
c1.metric("報告總數", status.get("total", 0))
c2.metric("已解析", status.get("done", 0))
c3.metric("待解析", status.get("pending", 0))
if status.get("error"):
    st.warning(status["error"])

batch_size = st.number_input("每批筆數", min_value=1, max_value=100, value=20)
batches = st.number_input("連續批次數", min_value=1, max_value=20, value=1, help="每批跑完再取下一批，避免一次塞爆請求。")
unprocessed_df = calc.load_unprocessed_reports(limit=int(batch_size))
st.write(f"本批預覽：{len(unprocessed_df)} 筆（連續 {batches} 批最多約 {int(batch_size) * int(batches)} 筆）")
if not unprocessed_df.empty:
    st.dataframe(
        unprocessed_df[["id", "entity_id", "report_type", "report_text"]].assign(
            report_text=lambda d: d["report_text"].astype(str).str.slice(0, 80)
        ),
        use_container_width=True,
        hide_index=True,
    )

ready = NLPProcessor().is_ready()
st.caption("大量回補可用本機：`python nlp_batch_job.py --limit 200`（讀環境變數，不經 UI）。")
if st.button(
    "🚀 LLM 解析本批",
    type="primary",
    disabled=unprocessed_df.empty or not ready,
):
    processor = NLPProcessor()
    progress_bar = st.progress(0)
    status_text = st.empty()
    results = []
    total_target = int(batch_size) * int(batches)
    done_n = 0
    for b in range(int(batches)):
        chunk = calc.load_unprocessed_reports(limit=int(batch_size))
        if chunk.empty:
            break
        for i, (_, row) in enumerate(chunk.iterrows()):
            done_n += 1
            status_text.text(f"分析 {done_n}/{total_target} (ID: {row['id']})...")
            try:
                res_json = processor.analyze_report_sync(row["report_text"], system_prompt)
                calc.save_nlp_result(int(row["id"]), res_json)
                results.append({"id": int(row["id"]), "nlp_result": res_json})
            except Exception as e:
                st.error(f"ID {row['id']} 失敗: {e}")
            progress_bar.progress(min(1.0, done_n / max(1, total_target)))
    status_text.text("✅ 本輪完成")
    if results:
        st.json(results[:5])
        st.info("解析完成後請再按「計算並寫入馬匹近績因子」或主頁重算，補償才會進入 Z-Score。")
    st.rerun()

st.markdown(
    """
**流程說明**
1. LLM 解析把受阻 JSON 寫進 `text_reports.nlp_result`。
2. 計算近績時：NLP 補償 + 降班三條件修正 → 距離帶粗桶 Z。
3. 推論儀表板以 `WEIGHT_RECENT_FORM` 計入近績分。
"""
)
