import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="騎師因子 (Jockey)", layout="wide")
st.title("🏇 騎師因子 (Jockey Factor)")

if 'raw_df' not in st.session_state:
    st.warning("請先至主頁面載入基礎歷史數據！")
    st.stop()

with st.sidebar.expander("⚙️ 參數調節 (AI 最佳化入口)", expanded=True):
    st.markdown("針對騎師因子獨立調整超參數")
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT (勝出權重)", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT (位置權重)", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.JOCKEY_SMOOTH_C = st.number_input("JOCKEY_SMOOTH_C (虛擬出賽限制)", min_value=1, value=ModelConfig.JOCKEY_SMOOTH_C)
    
    decay_str = st.text_input("JOCKEY_DECAY (時間衰減)", value=",".join(map(str, ModelConfig.JOCKEY_DECAY)))
    ModelConfig.JOCKEY_DECAY = [float(x.strip()) for x in decay_str.split(",")]

if st.button("🚀 獨立計算騎師因子", type="primary"):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        j_df = calc.calculate_entity_factor(df, 'jockey_name', ModelConfig.JOCKEY_DECAY, ModelConfig.JOCKEY_SMOOTH_C)
        j_df['factor_type'] = 'JOCKEY'
        j_df = j_df.rename(columns={'jockey_name': 'entity_name'})
        st.session_state['j_df_indep'] = j_df
        st.success("騎師因子計算完成！")

if 'j_df_indep' in st.session_state:
    st.divider()
    selected_bucket = st.selectbox("📍 選擇分桶 (Bucket)", st.session_state['buckets'])
    ui_utils.display_factor_details(st.session_state['j_df_indep'], selected_bucket, "騎師姓名")
