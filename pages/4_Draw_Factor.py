import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="檔位與場地因子 (Draw)", layout="wide")
st.title("🚪 檔位與場地偏差因子 (Draw Factor)")
st.caption("依排位檔位群組（Inner / Mid-Inner / Mid-Outer / Outer）+ 本場 Bucket 匹配。")

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.sidebar.expander("⚙️ 參數調節", expanded=False):
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.DRAW_SMOOTH_C = st.number_input("DRAW_SMOOTH_C", min_value=1, value=ModelConfig.DRAW_SMOOTH_C)
    bounds_str = st.text_input(
        "DRAW_GROUP_BOUNDARIES",
        value=",".join(map(str, ModelConfig.DRAW_GROUP_BOUNDARIES)),
    )
    ModelConfig.DRAW_GROUP_BOUNDARIES = [int(x.strip()) for x in bounds_str.split(",")]

can_compute = 'raw_df' in st.session_state and not st.session_state['raw_df'].empty
if st.button("🚀 計算檔位因子", type="primary", disabled=not can_compute):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        d_df = calc.calculate_draw_factor(df)
        d_df['factor_type'] = 'DRAW'
        d_df = d_df.rename(columns={'draw_group': 'entity_name'})
        st.session_state['d_df_indep'] = d_df
        st.success(f"完成：{len(d_df)} 筆")
if not can_compute:
    st.caption("調參重算需先回主頁載入歷史")

d_df = ui_utils.load_factor_from_db_or_session('d_df_indep', 'DRAW')
if not d_df.empty:
    st.session_state['d_df_indep'] = d_df
    ui_utils.render_upcoming_match_panel(
        d_df, match_mode='draw', entity_label='檔位群組', key_prefix='draw'
    )
else:
    st.info("尚未有檔位因子，請按上方按鈕計算，或回主頁寫入 factor_scores。")
