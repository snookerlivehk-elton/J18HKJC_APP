"""系統主頁：載入歷史、重算 factor_scores。"""
from __future__ import annotations

import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header("系統主頁", "載入歷史賽果並重算因子分數（寫入 factor_scores）")

st.markdown(
    """
**建議操作順序**
1. 資料控制中心：抓取排位表  
2. 本頁：載入歷史 → **重算並寫入因子分數**  
3. 賽日速覽／融合預測：查看結果  
"""
)

st.subheader("步驟 1：載入歷史賽果")
st.caption("從資料庫讀取已抓取的歷史出賽紀錄（不打 J18 API）。")

if st.button("載入歷史賽果數據", type="primary"):
    progress_placeholder = st.empty()
    progress_bar = st.progress(0)
    with st.spinner("系統運算中..."):
        try:
            calc = FactorCalculator()
            progress_placeholder.info("步驟 1/3: 讀取資料庫...")
            progress_bar.progress(33)
            df = calc.fetch_historical_data()
            if df.empty:
                progress_placeholder.error("找不到歷史數據！請先執行 batch_crawler。")
                progress_bar.empty()
            else:
                progress_placeholder.info(f"步驟 2/3: 已讀 {len(df)} 筆，計算 Base Score...")
                progress_bar.progress(66)
                df = calc.calculate_base_score(df)
                progress_placeholder.info("步驟 3/3: 整理 Bucket 快取...")
                progress_bar.progress(90)
                st.session_state["raw_df"] = df
                st.session_state["buckets"] = sorted(df["bucket_id"].unique().tolist())
                st.session_state["band_buckets"] = sorted(df["band_bucket_id"].unique().tolist())
                progress_bar.progress(100)
                progress_placeholder.success(
                    f"載入 {len(df)} 筆；細桶 {len(st.session_state['buckets'])}、"
                    f"粗桶 {len(st.session_state['band_buckets'])}。"
                )
        except Exception as e:
            progress_placeholder.error(f"發生錯誤: {e}")
            progress_bar.empty()

st.divider()
st.subheader("步驟 2：重算並寫入因子分數")
st.caption("騎練／近績＝距離帶粗桶；檔位＝細桶。推論只讀 factor_scores。")

if st.button("重算並寫入 factor_scores", type="primary"):
    with st.spinner("計算因子並寫入資料庫..."):
        try:
            calc = FactorCalculator()
            j, t, s, d, hj, h, p, sp = calc.run_all_factors(persist=True)
            if j is None:
                st.error("沒有歷史資料可計算。請先跑批次爬蟲。")
            else:
                n = (
                    len(j) + len(t) + len(s) + len(d)
                    + (0 if hj is None else len(hj))
                    + (0 if h is None else len(h))
                    + (0 if p is None else len(p))
                    + (0 if sp is None else len(sp))
                )
                st.session_state["j_df_indep"] = j
                st.session_state["t_df_indep"] = t
                st.session_state["s_df_indep"] = s
                st.session_state["d_df_indep"] = d
                if hj is not None:
                    st.session_state["hj_df_indep"] = hj
                if h is not None:
                    st.session_state["h_df_indep"] = h
                if p is not None:
                    st.session_state["pace_df"] = p
                if sp is not None:
                    st.session_state["speed_df"] = sp
                if "raw_df" not in st.session_state:
                    df = calc.fetch_historical_data()
                    if not df.empty:
                        st.session_state["raw_df"] = calc.calculate_base_score(df)
                        st.session_state["buckets"] = sorted(df["bucket_id"].unique().tolist())
                        st.session_state["band_buckets"] = sorted(
                            df["band_bucket_id"].unique().tolist()
                        )
                st.success(f"已寫入約 {n} 筆。可前往融合預測或賽日速覽。")
                st.dataframe(
                    j.sort_values("z_score", ascending=False).head(8)[
                        ["bucket_id", "entity_name", "actual_runs", "z_score"]
                    ],
                    use_container_width=True,
                )
        except Exception as e:
            st.error(f"寫入失敗: {e}")

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

with st.expander("目前 ModelConfig 權重"):
    st.json(
        {
            "WEIGHT_JOCKEY": ModelConfig.WEIGHT_JOCKEY,
            "WEIGHT_TRAINER": ModelConfig.WEIGHT_TRAINER,
            "WEIGHT_SYNERGY": ModelConfig.WEIGHT_SYNERGY,
            "WEIGHT_DRAW": ModelConfig.WEIGHT_DRAW,
            "WEIGHT_RECENT_FORM": ModelConfig.WEIGHT_RECENT_FORM,
            "WEIGHT_PACE": ModelConfig.WEIGHT_PACE,
            "WEIGHT_SPEED_FIGURE": ModelConfig.WEIGHT_SPEED_FIGURE,
            "WEIGHT_SG_FORM": ModelConfig.WEIGHT_SG_FORM,
            "WEIGHT_SG_ENERGY": ModelConfig.WEIGHT_SG_ENERGY,
            "WEIGHT_SG_DELTA": ModelConfig.WEIGHT_SG_DELTA,
        }
    )
