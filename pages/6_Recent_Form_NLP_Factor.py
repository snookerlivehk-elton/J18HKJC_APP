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

st.set_page_config(page_title="近績與 NLP 因子 (Recent Form & NLP)", layout="wide")
st.title("📉🤖 近績與 NLP 因子 (Recent Form & NLP Factor)")

if 'raw_df' not in st.session_state:
    st.warning("請先至主頁面載入基礎歷史數據！")
    st.stop()

st.markdown("""
### Phase 4: 近績與 NLP 補償
這個模組旨在解決傳統量化模型的盲點：**「馬匹上一場跑得很差，是真的實力不行，還是因為塞車受阻？」**

這裡分為兩個部分：
1. **基礎近績 (Base Form)**：純粹根據馬匹過去的勝負名次計算出的 Z-Score。
2. **NLP 補償 (NLP Excuse)**：使用 LLM 閱讀賽後報告，並根據受阻階段 (Early/Middle/Late) 乘上補償係數，修正基礎分數。
""")

# ==========================================
# 1. 參數與模型設定區
# ==========================================
col1, col2 = st.columns([1, 2])

with col1:
    with st.expander("⚙️ 參數調節 (AI 最佳化入口)", expanded=True):
        st.markdown("針對近績與 NLP 獨立調整超參數")
        ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT (勝出權重)", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
        ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT (位置權重)", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
        
        ModelConfig.HORSE_SMOOTH_C = st.number_input("HORSE_SMOOTH_C (馬匹虛擬出賽數)", min_value=1, value=ModelConfig.HORSE_SMOOTH_C)
        decay_str = st.text_input("HORSE_DECAY (近績時間衰減)", value=",".join(map(str, ModelConfig.HORSE_DECAY)))
        ModelConfig.HORSE_DECAY = [float(x.strip()) for x in decay_str.split(",")]
        
        st.divider()
        ModelConfig.EXCUSE_MULTIPLIER_EARLY = st.slider("早段受阻補償 (Early)", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_EARLY, 0.1)
        ModelConfig.EXCUSE_MULTIPLIER_MIDDLE = st.slider("中段受阻補償 (Middle)", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_MIDDLE, 0.1)
        ModelConfig.EXCUSE_MULTIPLIER_LATE = st.slider("直路受阻補償 (Late)", 1.0, 3.0, ModelConfig.EXCUSE_MULTIPLIER_LATE, 0.1)

with col2:
    with st.expander("🧠 LLM 模型與 Prompt 管理", expanded=False):
        api_key = st.text_input("OpenAI API Key (僅本次 Session 有效，Railway 將讀取 ENV)", type="password", value=os.getenv("OPENAI_API_KEY", ""))
        model_name = st.selectbox("模型選擇", ["gpt-4o-mini", "gpt-3.5-turbo", "gpt-4o"], index=0)
        
        default_prompt = """你是一個專業的香港賽馬分析師。請閱讀以下賽馬報告（可能包含走位短評與賽後報告），判斷該馬匹在賽事中是否遭遇了影響名次的受阻或意外。
請嚴格輸出以下 JSON 格式：
{
  "has_excuse": true/false,
  "excuse_stage": "early" | "middle" | "late" | "none",
  "severity": 0.0 到 1.0 之間的數字 (1.0代表極嚴重如勒避/墮馬，0.3代表輕微受擠逼),
  "reason": "簡短的受阻原因總結(繁體中文)"
}
注意：
- early: 起步、早段
- middle: 中段、轉彎前
- late: 轉彎入直路、直路衝刺階段
- 如果沒有任何意外或只是自然力弱，has_excuse 必須為 false。"""
        system_prompt = st.text_area("System Prompt (系統提示詞)", value=default_prompt, height=200)

        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["OPENAI_MODEL"] = model_name

# ==========================================
# 2. 計算基礎近績 (Base Form)
# ==========================================
st.divider()
st.subheader("📊 馬匹基礎近績 (Base Form)")

if st.button("🚀 獨立計算馬匹近績因子", type="primary"):
    with st.spinner("計算馬匹基礎近績中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        
        # 由於原始數據可能包含未知的 horse_name，我們確保名稱乾淨
        df['horse_name_clean'] = df['horse_name'].fillna('未知馬匹').astype(str)
        
        # 使用與騎師相同的方法計算實體分數，但傳入馬匹專屬的超參數
        h_df = calc.calculate_entity_factor(df, 'horse_name_clean', ModelConfig.HORSE_DECAY, ModelConfig.HORSE_SMOOTH_C)
        h_df['factor_type'] = 'HORSE'
        h_df = h_df.rename(columns={'horse_name_clean': 'entity_name'})
        
        st.session_state['h_df_indep'] = h_df
        st.success("馬匹近績因子計算完成！")

if 'h_df_indep' in st.session_state:
    selected_bucket = st.selectbox("📍 選擇分桶 (Bucket)", st.session_state['buckets'], key="horse_bucket")
    ui_utils.display_factor_details(st.session_state['h_df_indep'], selected_bucket, "馬匹名稱")


# ==========================================
# 3. 執行 NLP 解析 (批次處理)
# ==========================================
st.divider()
st.subheader("📝 執行 NLP 解析 (針對尚未解析的歷史報告)")

def get_unprocessed_reports():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    # 找出還沒有 nlp_result 的文字報告
    df = pd.read_sql("SELECT id, entity_id, report_type, report_text FROM text_reports WHERE nlp_result IS NULL LIMIT 10", conn)
    conn.close()
    return df

unprocessed_df = get_unprocessed_reports()
st.write(f"目前資料庫中有 {len(unprocessed_df)} 筆 (此處僅預覽前 10 筆) 尚未被 LLM 解析的報告。")
st.dataframe(unprocessed_df, use_container_width=True)

if st.button("🚀 開始呼叫 LLM 進行解析 (每次 10 筆)", type="primary", disabled=unprocessed_df.empty or not api_key):
    async def process_batch():
        processor = NLPProcessor()
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        for idx, row in unprocessed_df.iterrows():
            status_text.text(f"正在分析第 {idx+1}/{len(unprocessed_df)} 筆 (ID: {row['id']})...")
            try:
                res_json = await processor.analyze_report(row['report_text'], system_prompt)
                
                # 寫回資料庫
                import json
                c.execute("UPDATE text_reports SET nlp_result = ? WHERE id = ?", (json.dumps(res_json, ensure_ascii=False), row['id']))
                conn.commit()
                
                results.append({"id": row['id'], "nlp_result": res_json})
            except Exception as e:
                st.error(f"ID {row['id']} 解析失敗: {e}")
            
            progress_bar.progress((idx + 1) / len(unprocessed_df))
            
        conn.close()
        status_text.text("✅ 解析完成！")
        return results

    # 執行非同步處理
    results = asyncio.run(process_batch())
    st.write("解析結果預覽：")
    st.json(results)
    st.rerun()
