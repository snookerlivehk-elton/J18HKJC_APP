import streamlit as st
import pandas as pd
from config import ModelConfig
from factor_calculator import FactorCalculator

st.set_page_config(page_title="J18 Quant Model", layout="wide")

st.title("🏇 J18 量化預測系統")
st.markdown("""
**建議操作順序**
1. 資料控制中心：抓取明日排位表  
2. 本頁：載入歷史 → **重算並寫入因子分數**  
3. 推論儀表板：選場次，用排位條件匹配 `factor_scores` 出預測  

各因子獨立頁僅供診斷「為什麼是這個分數」。
""")

st.divider()

st.subheader("📥 步驟 1: 載入歷史賽果")
st.markdown("從資料庫讀取已抓取的歷史出賽紀錄（不打 J18 API）。")

if st.button("🚀 載入歷史賽果數據", type="primary"):
    progress_placeholder = st.empty()
    progress_bar = st.progress(0)

    with st.spinner("系統運算中..."):
        try:
            calc = FactorCalculator()

            progress_placeholder.info("🔄 步驟 1/3: 讀取資料庫...")
            progress_bar.progress(33)

            df = calc.fetch_historical_data()

            if df.empty:
                progress_placeholder.error("找不到歷史數據！請先執行 `python batch_crawler.py`。")
                progress_bar.empty()
            else:
                progress_placeholder.info(f"🔄 步驟 2/3: 已讀 {len(df)} 筆，計算 Base Score...")
                progress_bar.progress(66)

                df = calc.calculate_base_score(df)

                progress_placeholder.info("🔄 步驟 3/3: 整理標準 Bucket 快取...")
                progress_bar.progress(90)

                st.session_state['raw_df'] = df
                st.session_state['buckets'] = sorted(df['bucket_id'].unique().tolist())

                progress_bar.progress(100)
                progress_placeholder.success(
                    f"✅ 載入 {len(df)} 筆紀錄，共 {len(st.session_state['buckets'])} 個 bucket。"
                    f" 範例：`{st.session_state['buckets'][:5]}`"
                )

        except Exception as e:
            progress_placeholder.error(f"發生錯誤: {e}")
            progress_bar.empty()

st.divider()

st.subheader("🧠 步驟 2: 重算並寫入因子分數（供預測查表）")
st.markdown(
    "計算騎師 / 練馬師 / 騎練 / 檔位 Z-Score，寫入 `factor_scores`。"
    "推論頁只讀這張表，不再每次現算。"
)

if st.button("💾 重算並寫入 factor_scores", type="primary"):
    with st.spinner("計算四大因子並寫入資料庫..."):
        try:
            calc = FactorCalculator()
            j, t, s, d = calc.run_all_factors(persist=True)
            if j is None:
                st.error("沒有歷史資料可計算。請先跑批次爬蟲。")
            else:
                n = len(j) + len(t) + len(s) + len(d)
                st.session_state['j_df_indep'] = j
                st.session_state['t_df_indep'] = t
                st.session_state['s_df_indep'] = s
                st.session_state['d_df_indep'] = d
                # 同步 raw_df 方便各診斷頁
                if 'raw_df' not in st.session_state:
                    df = calc.fetch_historical_data()
                    if not df.empty:
                        st.session_state['raw_df'] = calc.calculate_base_score(df)
                        st.session_state['buckets'] = sorted(df['bucket_id'].unique().tolist())
                st.success(f"✅ 已寫入約 {n} 筆因子分數。可前往「推論儀表板」做賽事預測。")
                st.dataframe(
                    j.sort_values('z_score', ascending=False).head(8)[
                        ['bucket_id', 'entity_name', 'actual_runs', 'z_score']
                    ],
                    use_container_width=True,
                )
        except Exception as e:
            st.error(f"寫入失敗: {e}")

# 顯示目前庫內狀態
try:
    calc = FactorCalculator()
    existing = calc.load_factor_scores()
    if not existing.empty:
        st.caption(
            f"資料庫現有 factor_scores：{len(existing)} 筆，"
            f"類型 {sorted(existing['factor_type'].unique().tolist())}，"
            f"bucket 數 {existing['bucket_id'].nunique()}"
        )
except Exception:
    pass

with st.expander("目前 ModelConfig 權重（推論用）"):
    st.json({
        "WEIGHT_JOCKEY": ModelConfig.WEIGHT_JOCKEY,
        "WEIGHT_TRAINER": ModelConfig.WEIGHT_TRAINER,
        "WEIGHT_SYNERGY": ModelConfig.WEIGHT_SYNERGY,
        "WEIGHT_DRAW": ModelConfig.WEIGHT_DRAW,
        "WEIGHT_SG_FORM": ModelConfig.WEIGHT_SG_FORM,
        "WEIGHT_SG_ENERGY": ModelConfig.WEIGHT_SG_ENERGY,
        "WEIGHT_SG_DELTA": ModelConfig.WEIGHT_SG_DELTA,
    })
