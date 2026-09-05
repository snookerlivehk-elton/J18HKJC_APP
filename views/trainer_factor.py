import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils
import ui_param_help as ph

st.title("🎩 練馬師因子")
st.caption("依排位練馬師 + 距離帶粗桶（如 ST_SPRINT），匹配歷史 TRAINER Z-Score。")

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.expander("⚙️ 參數調節", expanded=False):
    st.caption("游標停在標籤旁 ⓘ 可看功能與調節後變化。")
    ModelConfig.WIN_WEIGHT = st.slider(
        "冠軍權重", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1, help=ph.WIN_WEIGHT
    )
    ModelConfig.PLACE_WEIGHT = st.slider(
        "入位權重", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05, help=ph.PLACE_WEIGHT
    )
    ModelConfig.TRAINER_SMOOTH_C = st.number_input(
        "練馬師平滑常數", min_value=1, value=ModelConfig.TRAINER_SMOOTH_C, help=ph.smooth_c("練馬師")
    )
    decay_str = st.text_input(
        "練馬師時間衰減",
        value=",".join(map(str, ModelConfig.TRAINER_DECAY)),
        help=ph.decay("練馬師"),
    )
    ModelConfig.TRAINER_DECAY = [float(x.strip()) for x in decay_str.split(",")]

can_compute = 'raw_df' in st.session_state and not st.session_state['raw_df'].empty
if st.button("🚀 計算練馬師因子", type="primary", disabled=not can_compute):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        t_df = calc.calculate_entity_factor(
            df, 'trainer_name', ModelConfig.TRAINER_DECAY, ModelConfig.TRAINER_SMOOTH_C,
            use_distance_band=True,
        )
        t_df['factor_type'] = 'TRAINER'
        t_df = t_df.rename(columns={'trainer_name': 'entity_name'})
        st.session_state['t_df_indep'] = t_df
        st.success(f"完成：{len(t_df)} 筆")
if not can_compute:
    st.caption("調參重算需先回主頁載入歷史")

t_df = ui_utils.load_factor_from_db_or_session('t_df_indep', 'TRAINER')
if not t_df.empty:
    st.session_state['t_df_indep'] = t_df
    ui_utils.render_upcoming_match_panel(
        t_df, match_mode='trainer', entity_label='匹配練馬師', key_prefix='trainer'
    )
else:
    st.info("尚未有練馬師因子，請按上方按鈕計算，或回主頁寫入 factor_scores。")
