import streamlit as st
import pandas as pd
from config import ModelConfig
from factor_calculator import FactorCalculator

st.set_page_config(page_title="J18 Quant Model", layout="wide")

st.title("🏇 J18 量化因子大腦 (Quant Factor Dashboard)")
st.markdown("""
歡迎來到 J18 量化預測系統後台。
本系統嚴格遵循 **特徵顆粒度原則 (Feature Granularity Principle)**，所有量化因子皆獨立計算與儲存。

👈 請從左側選單進入各因子專屬頁面，進行**獨立運算**與**細部參數調校 (AI 最佳化入口)**。
""")

st.divider()

st.subheader("📥 步驟 1: 載入基礎歷史數據 (Data Fetching)")
st.markdown("請先在此處從資料庫載入最新抓取的原始數據，載入後即可前往各獨立頁面進行計算。")

if st.button("🚀 載入歷史賽果數據", type="primary"):
    # 建立一個佔位符用來顯示進度
    progress_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    with st.spinner("系統運算中..."):
        try:
            calc = FactorCalculator()
            
            progress_placeholder.info("🔄 步驟 1/3: 正在從本地/雲端資料庫 (PostgreSQL/SQLite) 讀取數據... (不消耗 J18 API)")
            progress_bar.progress(33)
            
            df = calc.fetch_historical_data()
            
            if df.empty:
                progress_placeholder.error("找不到歷史數據！請先執行 `python batch_crawler.py` 抓取資料。")
                progress_bar.empty()
            else:
                progress_placeholder.info(f"🔄 步驟 2/3: 成功讀取 {len(df)} 筆資料，正在計算基礎分數 (Base Score)...")
                progress_bar.progress(66)
                
                # 預先算好 Base Score
                df = calc.calculate_base_score(df)
                
                progress_placeholder.info("🔄 步驟 3/3: 正在整理賽道分桶 (Bucketing) 與快取...")
                progress_bar.progress(90)
                
                st.session_state['raw_df'] = df
                st.session_state['buckets'] = sorted(df['bucket_id'].unique().tolist())
                
                progress_bar.progress(100)
                progress_placeholder.success(f"✅ 成功載入 {len(df)} 筆賽馬出賽紀錄！請從左側選單進入各因子獨立頁面。")
                
        except Exception as e:
            progress_placeholder.error(f"發生錯誤: {e}")
            progress_bar.empty()
