import streamlit as st
import os
import asyncio
import pandas as pd
from config import ModelConfig
from nlp_processor import NLPProcessor
from factor_calculator import FactorCalculator
import ui_utils
import sqlite3
from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH

st.set_page_config(page_title="近績與 NLP 因子", layout="wide")
st.title("📉🤖 近績與 NLP 因子 (Recent Form & NLP)")
st.caption("基礎近績 = 馬匹在特定 Bucket 的歷史表現；NLP 補償為後續加權（需 text_reports）。")

if not ui_utils.ensure_history_loaded():
    st.stop()

col1, col2 = st.columns([1, 2])
with col1:
    with st.expander("⚙️ 參數調節", expanded=False):
        ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
        ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
        ModelConfig.HORSE_SMOOTH_C = st.number_input("HORSE_SMOOTH_C", min_value=1, value=ModelConfig.HORSE_SMOOTH_C)
        decay_str = st.text_input("HORSE_DECAY", value=",".join(map(str, ModelConfig.HORSE_DECAY)))
        ModelConfig.HORSE_DECAY = [float(x.strip()) for x in decay_str.split(",")]
        ModelConfig.EXCUSE_MULTIPLIER_EARLY = st.slider("早段受阻補償", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_EARLY, 0.1)
        ModelConfig.EXCUSE_MULTIPLIER_MIDDLE = st.slider("中段受阻補償", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_MIDDLE, 0.1)
        ModelConfig.EXCUSE_MULTIPLIER_LATE = st.slider("直路受阻補償", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_LATE, 0.1)

with col2:
    with st.expander("🧠 LLM Prompt", expanded=False):
        api_key = st.text_input(
            "OpenAI API Key",
            type="password",
            value=os.getenv("OPENAI_API_KEY", ""),
        )
        model_name = st.selectbox("模型", ["gpt-4o-mini", "gpt-3.5-turbo", "gpt-4o"], index=0)
        default_prompt = """你是一個專業的香港賽馬分析師。請閱讀以下賽馬報告，判斷是否遭遇影響名次的受阻。
嚴格輸出 JSON：
{"has_excuse": true/false, "excuse_stage": "early"|"middle"|"late"|"none", "severity": 0.0-1.0, "reason": "繁中簡述"}"""
        system_prompt = st.text_area("System Prompt", value=default_prompt, height=160)
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["OPENAI_MODEL"] = model_name

st.divider()
st.subheader("📊 馬匹基礎近績")

can_compute = 'raw_df' in st.session_state and not st.session_state['raw_df'].empty
if st.button("🚀 計算馬匹近績因子", type="primary", disabled=not can_compute):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        df['horse_name_clean'] = df['horse_name'].fillna('未知馬匹').astype(str)
        h_df = calc.calculate_entity_factor(
            df, 'horse_name_clean', ModelConfig.HORSE_DECAY, ModelConfig.HORSE_SMOOTH_C
        )
        h_df['factor_type'] = 'HORSE'
        h_df = h_df.rename(columns={'horse_name_clean': 'entity_name'})
        st.session_state['h_df_indep'] = h_df
        st.success(f"完成：{len(h_df)} 筆")

h_df = ui_utils.load_factor_from_db_or_session('h_df_indep', 'HORSE')
if not h_df.empty:
    st.session_state['h_df_indep'] = h_df
    ui_utils.render_upcoming_match_panel(
        h_df, match_mode='horse', entity_label='匹配馬名', key_prefix='horse_form'
    )
else:
    st.info("尚未有近績因子。請先載入歷史後計算。")

st.divider()
st.subheader("📝 NLP 解析（歷史報告）")

def get_unprocessed_reports():
    if USE_SQLITE:
        if not os.path.exists(SQLITE_DB_PATH):
            return pd.DataFrame()
        conn = sqlite3.connect(SQLITE_DB_PATH)
    else:
        st.caption("雲端 Postgres NLP 批次請改用專用 job；此處僅 SQLite 預覽。")
        return pd.DataFrame()
    try:
        # nlp_result 欄位可能尚未 migration；容錯
        cols = pd.read_sql("PRAGMA table_info(text_reports)", conn)
        col_names = cols['name'].tolist() if not cols.empty else []
        if 'nlp_result' not in col_names:
            conn.execute("ALTER TABLE text_reports ADD COLUMN nlp_result TEXT")
            conn.commit()
        df = pd.read_sql(
            "SELECT id, entity_id, report_type, report_text FROM text_reports "
            "WHERE nlp_result IS NULL LIMIT 10",
            conn,
        )
    except Exception as e:
        st.warning(f"讀取 text_reports 失敗: {e}")
        df = pd.DataFrame()
    finally:
        conn.close()
    return df

unprocessed_df = get_unprocessed_reports()
st.write(f"待解析預覽：{len(unprocessed_df)} 筆")
if not unprocessed_df.empty:
    st.dataframe(unprocessed_df, use_container_width=True)

if st.button(
    "🚀 LLM 解析（每次最多 10 筆）",
    type="primary",
    disabled=unprocessed_df.empty or not api_key,
):
    async def process_batch():
        processor = NLPProcessor()
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        progress_bar = st.progress(0)
        status_text = st.empty()
        results = []
        for i, (_, row) in enumerate(unprocessed_df.iterrows()):
            status_text.text(f"分析 {i+1}/{len(unprocessed_df)} (ID: {row['id']})...")
            try:
                import json
                res_json = await processor.analyze_report(row['report_text'], system_prompt)
                c.execute(
                    "UPDATE text_reports SET nlp_result = ? WHERE id = ?",
                    (json.dumps(res_json, ensure_ascii=False), row['id']),
                )
                conn.commit()
                results.append({"id": row['id'], "nlp_result": res_json})
            except Exception as e:
                st.error(f"ID {row['id']} 失敗: {e}")
            progress_bar.progress((i + 1) / len(unprocessed_df))
        conn.close()
        status_text.text("✅ 完成")
        return results

    results = asyncio.run(process_batch())
    st.json(results)
    st.rerun()
