import streamlit as st
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

parse_mode = st.radio(
    "解析模式",
    options=["racecard", "queue"],
    format_func=lambda x: {
        "racecard": "⭐ 整個賽日解析（推薦｜自動略過無特別報告）",
        "queue": "全庫佇列（慢｜可選略過無內容）",
    }[x],
    horizontal=True,
    key="nlp_parse_mode",
)

ready = NLPProcessor().is_ready()
lookback_days = st.number_input(
    "歷史回看天數",
    min_value=90,
    max_value=730,
    value=360,
    help="對齊近績衰減：約一年內報告通常已足夠。",
)

if parse_mode == "racecard":
    meeting_options = ui_utils.get_upcoming_meeting_days_list()
    if not meeting_options:
        st.warning("沒有即將舉行的賽事。請先到資料控制中心抓排位表。")
    else:
        selected_key = st.selectbox(
            "選擇要整個賽日解析的賽日",
            options=[opt[0] for opt in meeting_options],
            format_func=lambda x: next(opt[1] for opt in meeting_options if opt[0] == x),
            key="nlp_meeting_select",
        )
        selected = next(opt for opt in meeting_options if opt[0] == selected_key)
        meeting_key, meeting_label, race_ids = selected
        date_part, course_part = meeting_key.split("|", 1)

        related = calc.load_reports_for_upcoming_race(
            race_ids,
            lookback_days=int(lookback_days),
            only_unprocessed=True,
        )
        n_total = len(related)
        n_trivial = int(related["is_trivial"].sum()) if n_total else 0
        n_llm = int(related["needs_llm"].sum()) if n_total else 0
        n_races = len(race_ids)
        n_horses = related.attrs.get("upcoming_horse_count") if hasattr(related, "attrs") else None

        st.caption(f"已選：{meeting_label}｜race_id × {n_races}" + (f"｜排位馬約 {n_horses} 匹" if n_horses else ""))
        m1, m2, m3 = st.columns(3)
        m1.metric("賽日相關待處理", n_total)
        m2.metric("將略過（無內容）", n_trivial)
        m3.metric("將呼叫 LLM", n_llm)

        if n_total:
            preview = related.copy()
            preview["處理"] = preview["is_trivial"].map({True: "略過", False: "LLM"})
            preview["report_text"] = preview["report_text"].astype(str).str.slice(0, 60)
            st.dataframe(
                preview[["id", "entity_id", "report_type", "處理", "report_text"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("此賽日排位馬匹在回看期內沒有未解析報告（可能已解析完，或歷史尚無文字）。")

        if st.button(
            "🚀 整個賽日解析",
            type="primary",
            disabled=(n_llm == 0 and n_trivial == 0) or (n_llm > 0 and not ready),
            key="nlp_parse_meeting",
        ):
            skipped = 0
            if n_trivial:
                trivial_ids = related.loc[related["is_trivial"], "id"].tolist()
                skipped = calc.mark_trivial_reports_skipped(report_ids=trivial_ids)

            results = []
            to_llm = related.loc[related["needs_llm"]].copy() if n_total else pd.DataFrame()
            if not to_llm.empty:
                if not ready:
                    st.error("需要 OPENAI_API_KEY 才能解析非空白報告。")
                else:
                    processor = NLPProcessor()
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    for i, (_, row) in enumerate(to_llm.iterrows()):
                        status_text.text(f"LLM {i + 1}/{len(to_llm)} (ID: {row['id']})...")
                        try:
                            res_json = processor.analyze_report_sync(
                                row["report_text"], system_prompt
                            )
                            calc.save_nlp_result(int(row["id"]), res_json)
                            results.append({"id": int(row["id"]), "nlp_result": res_json})
                        except Exception as e:
                            st.error(f"ID {row['id']} 失敗: {e}")
                        progress_bar.progress((i + 1) / len(to_llm))
                    status_text.text("✅ LLM 完成")

            st.success(
                f"賽日 {date_part} {course_part}：略過 {skipped} 筆無內容；LLM 成功 {len(results)} 筆。"
                "結果已寫入 nlp_result，之後可重用。"
            )
            if results:
                st.json(results[:5])
            st.info("請再按上方「計算並寫入馬匹近績因子」或主頁重算，補償才會進入 Z-Score。")
            st.rerun()

else:
    batch_size = st.number_input("每批筆數", min_value=1, max_value=100, value=20, key="nlp_batch_size")
    batches = st.number_input(
        "連續批次數",
        min_value=1,
        max_value=20,
        value=1,
        help="每批跑完再取下一批。",
        key="nlp_batches",
    )
    auto_skip = st.checkbox("自動略過空白／無特別報告", value=True, key="nlp_queue_skip")
    unprocessed_df = calc.load_unprocessed_reports(
        limit=int(batch_size), skip_trivial=bool(auto_skip)
    )
    st.write(
        f"本批預覽：{len(unprocessed_df)} 筆（連續 {batches} 批最多約 {int(batch_size) * int(batches)} 筆）"
    )
    if not unprocessed_df.empty:
        st.dataframe(
            unprocessed_df[["id", "entity_id", "report_type", "report_text"]].assign(
                report_text=lambda d: d["report_text"].astype(str).str.slice(0, 80)
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.caption("大量回補可用本機：`python nlp_batch_job.py --limit 200`（讀環境變數，不經 UI）。")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🧹 先略過一批無內容報告", key="nlp_mark_trivial"):
            n = calc.mark_trivial_reports_skipped(limit=int(batch_size) * 10)
            st.success(f"已略過並標記 {n} 筆。")
            st.rerun()
    with col_b:
        if st.button(
            "🚀 LLM 解析本批（全庫佇列）",
            type="primary",
            disabled=unprocessed_df.empty or not ready,
            key="nlp_parse_queue",
        ):
            processor = NLPProcessor()
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []
            total_target = int(batch_size) * int(batches)
            done_n = 0
            for b in range(int(batches)):
                chunk = calc.load_unprocessed_reports(
                    limit=int(batch_size), skip_trivial=bool(auto_skip)
                )
                if chunk.empty:
                    break
                for i, (_, row) in enumerate(chunk.iterrows()):
                    done_n += 1
                    status_text.text(f"分析 {done_n}/{total_target} (ID: {row['id']})...")
                    try:
                        res_json = processor.analyze_report_sync(
                            row["report_text"], system_prompt
                        )
                        calc.save_nlp_result(int(row["id"]), res_json)
                        results.append({"id": int(row["id"]), "nlp_result": res_json})
                    except Exception as e:
                        st.error(f"ID {row['id']} 失敗: {e}")
                    progress_bar.progress(min(1.0, done_n / max(1, total_target)))
            status_text.text("✅ 本輪完成")
            if results:
                st.json(results[:5])
                st.info("解析完成後請再按「計算並寫入馬匹近績因子」或主頁重算。")
            st.rerun()

st.markdown(
    """
**流程說明**
1. **整個賽日模式**：一次涵蓋該日該場地所有排位馬匹、回看期內尚未有 `nlp_result` 的報告；空白／「無特別報告」直接標記略過（不花 API）。
2. 結果寫入 `text_reports.nlp_result` 後**永久重用**，不會每次重跑。
3. 計算近績時讀取已解析結果做受阻補償；推論以 `WEIGHT_RECENT_FORM` 計入。
"""
)
