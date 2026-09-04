import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="練馬師因子 (Trainer)", layout="wide")
st.title("🎩 練馬師因子 (Trainer Factor)")

if 'raw_df' not in st.session_state:
    st.warning("請先至主頁面載入基礎歷史數據！")
    st.stop()

with st.sidebar.expander("⚙️ 參數調節 (AI 最佳化入口)", expanded=True):
    st.markdown("針對練馬師因子獨立調整超參數")
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT (勝出權重)", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT (位置權重)", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.TRAINER_SMOOTH_C = st.number_input("TRAINER_SMOOTH_C (虛擬出賽限制)", min_value=1, value=ModelConfig.TRAINER_SMOOTH_C)
    
    decay_str = st.text_input("TRAINER_DECAY (時間衰減)", value=",".join(map(str, ModelConfig.TRAINER_DECAY)))
    ModelConfig.TRAINER_DECAY = [float(x.strip()) for x in decay_str.split(",")]

if st.button("🚀 獨立計算練馬師因子", type="primary"):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        t_df = calc.calculate_entity_factor(df, 'trainer_name', ModelConfig.TRAINER_DECAY, ModelConfig.TRAINER_SMOOTH_C)
        t_df['factor_type'] = 'TRAINER'
        t_df = t_df.rename(columns={'trainer_name': 'entity_name'})
        st.session_state['t_df_indep'] = t_df
        st.success("練馬師因子計算完成！")

if 't_df_indep' in st.session_state:
    st.divider()
    selected_bucket = st.selectbox("📍 選擇分桶 (Bucket)", st.session_state['buckets'])
    ui_utils.display_factor_details(st.session_state['t_df_indep'], selected_bucket, "練馬師姓名")
