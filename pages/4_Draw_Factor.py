import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="檔位與場地因子 (Draw)", layout="wide")
st.title("🚪 檔位與場地偏差因子 (Draw Factor)")

if 'raw_df' not in st.session_state:
    st.warning("請先至主頁面載入基礎歷史數據！")
    st.stop()

with st.sidebar.expander("⚙️ 參數調節 (AI 最佳化入口)", expanded=True):
    st.markdown("針對檔位偏差獨立調整超參數")
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT (勝出權重)", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT (位置權重)", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.DRAW_SMOOTH_C = st.number_input("DRAW_SMOOTH_C (虛擬出賽限制)", min_value=1, value=ModelConfig.DRAW_SMOOTH_C)
    
    bounds_str = st.text_input("DRAW_GROUP_BOUNDARIES (分組切分點)", value=",".join(map(str, ModelConfig.DRAW_GROUP_BOUNDARIES)))
    ModelConfig.DRAW_GROUP_BOUNDARIES = [int(x.strip()) for x in bounds_str.split(",")]

if st.button("🚀 獨立計算檔位因子", type="primary"):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        d_df = calc.calculate_draw_factor(df)
        d_df['factor_type'] = 'DRAW'
        d_df = d_df.rename(columns={'draw_group': 'entity_name'})
        st.session_state['d_df_indep'] = d_df
        st.success("檔位因子計算完成！")

if 'd_df_indep' in st.session_state:
    st.divider()
    selected_bucket = st.selectbox("📍 選擇分桶 (Bucket)", st.session_state['buckets'])
    ui_utils.display_factor_details(st.session_state['d_df_indep'], selected_bucket, "檔位群組")
