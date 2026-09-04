import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
from bucket_utils import GLOBAL_BUCKET
import ui_utils

st.set_page_config(page_title="人馬合作因子 (Horse-Jockey)", layout="wide")
st.title("🏇🤝 人馬合作因子 (Horse-Jockey Synergy)")
st.caption(
    f"白皮書：不分賽道距離，使用全域分桶 `{GLOBAL_BUCKET}`。"
    " 鍵為「馬名 & 騎師」。"
)

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.sidebar.expander("⚙️ 參數調節", expanded=False):
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.HORSE_JOCKEY_SMOOTH_C = st.number_input(
        "HORSE_JOCKEY_SMOOTH_C", min_value=1, value=ModelConfig.HORSE_JOCKEY_SMOOTH_C
    )
    decay_str = st.text_input(
        "HORSE_JOCKEY_DECAY",
        value=",".join(map(str, ModelConfig.HORSE_JOCKEY_DECAY)),
    )
    ModelConfig.HORSE_JOCKEY_DECAY = [float(x.strip()) for x in decay_str.split(",")]

can_compute = 'raw_df' in st.session_state and not st.session_state['raw_df'].empty
if st.button("🚀 計算人馬合作因子", type="primary", disabled=not can_compute):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        hj_df = calc.calculate_horse_jockey_factor(df)
        st.session_state['hj_df_indep'] = hj_df
        st.success(f"完成：{len(hj_df)} 筆（bucket={GLOBAL_BUCKET}）")
if not can_compute:
    st.caption("調參重算需先回主頁載入歷史")

hj_df = ui_utils.load_factor_from_db_or_session('hj_df_indep', 'HORSE_JOCKEY')
if not hj_df.empty:
    st.session_state['hj_df_indep'] = hj_df
    ui_utils.render_upcoming_match_panel(
        hj_df,
        match_mode='horse_jockey',
        entity_label='人馬組合',
        key_prefix='hj',
        use_global_bucket=True,
    )
else:
    st.info("尚未有人馬合作因子，請按上方按鈕計算，或回主頁寫入 factor_scores。")
