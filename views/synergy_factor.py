import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
from bucket_utils import synergy_name
import ui_utils

st.title("🤝 騎練合作因子")
st.caption("依排位「騎師 & 練馬師」+ 距離帶粗桶匹配。名稱格式與推論引擎相同。")

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.expander("⚙️ 參數調節", expanded=False):
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.SYNERGY_SMOOTH_C = st.number_input("SYNERGY_SMOOTH_C", min_value=1, value=ModelConfig.SYNERGY_SMOOTH_C)
    decay_str = st.text_input("SYNERGY_DECAY", value=",".join(map(str, ModelConfig.SYNERGY_DECAY)))
    ModelConfig.SYNERGY_DECAY = [float(x.strip()) for x in decay_str.split(",")]

can_compute = 'raw_df' in st.session_state and not st.session_state['raw_df'].empty
if st.button("🚀 計算騎練合作因子", type="primary", disabled=not can_compute):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        df['synergy_name'] = df.apply(
            lambda r: synergy_name(r['jockey_name'], r['trainer_name']), axis=1
        )
        s_df = calc.calculate_entity_factor(
            df, 'synergy_name', ModelConfig.SYNERGY_DECAY, ModelConfig.SYNERGY_SMOOTH_C,
            use_distance_band=True,
        )
        s_df['factor_type'] = 'SYNERGY'
        s_df = s_df.rename(columns={'synergy_name': 'entity_name'})
        st.session_state['s_df_indep'] = s_df
        st.success(f"完成：{len(s_df)} 筆")
if not can_compute:
    st.caption("調參重算需先回主頁載入歷史")

s_df = ui_utils.load_factor_from_db_or_session('s_df_indep', 'SYNERGY')
if not s_df.empty:
    st.session_state['s_df_indep'] = s_df
    ui_utils.render_upcoming_match_panel(
        s_df, match_mode='synergy', entity_label='騎練組合', key_prefix='synergy'
    )
else:
    st.info("尚未有騎練合作因子，請按上方按鈕計算，或回主頁寫入 factor_scores。")
