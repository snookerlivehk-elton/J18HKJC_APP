import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="騎師因子 (Jockey)", layout="wide")
st.title("🏇 騎師因子 (Jockey Factor)")
st.caption("依排位騎師 + 距離帶粗桶（如 ST_SPRINT），匹配歷史 JOCKEY Z-Score。")

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.sidebar.expander("⚙️ 參數調節", expanded=False):
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.JOCKEY_SMOOTH_C = st.number_input("JOCKEY_SMOOTH_C", min_value=1, value=ModelConfig.JOCKEY_SMOOTH_C)
    decay_str = st.text_input("JOCKEY_DECAY", value=",".join(map(str, ModelConfig.JOCKEY_DECAY)))
    ModelConfig.JOCKEY_DECAY = [float(x.strip()) for x in decay_str.split(",")]

col_a, col_b = st.columns([1, 3])
with col_a:
    can_compute = 'raw_df' in st.session_state and not st.session_state['raw_df'].empty
    if st.button("🚀 計算騎師因子", type="primary", use_container_width=True, disabled=not can_compute):
        with st.spinner("計算中..."):
            calc = FactorCalculator()
            df = calc.calculate_base_score(st.session_state['raw_df'].copy())
            j_df = calc.calculate_entity_factor(
                df, 'jockey_name', ModelConfig.JOCKEY_DECAY, ModelConfig.JOCKEY_SMOOTH_C,
                use_distance_band=True,
            )
            j_df['factor_type'] = 'JOCKEY'
            j_df = j_df.rename(columns={'jockey_name': 'entity_name'})
            st.session_state['j_df_indep'] = j_df
            st.success(f"完成：{len(j_df)} 筆")
    if not can_compute:
        st.caption("調參重算需先回主頁載入歷史")

j_df = ui_utils.load_factor_from_db_or_session('j_df_indep', 'JOCKEY')
if not j_df.empty:
    st.session_state['j_df_indep'] = j_df
    ui_utils.render_upcoming_match_panel(
        j_df, match_mode='jockey', entity_label='匹配騎師', key_prefix='jockey'
    )
else:
    st.info("尚未有騎師因子，請按上方按鈕計算，或回主頁寫入 factor_scores。")
