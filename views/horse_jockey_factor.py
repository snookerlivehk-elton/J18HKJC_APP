import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
from bucket_utils import GLOBAL_BUCKET
import ui_utils

st.title("🏇🤝 人馬合作因子")
st.caption(
    f"白皮書：不分賽道距離，使用全域分桶 `{GLOBAL_BUCKET}`。"
    " 鍵為「馬名 & 騎師」。"
)

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.expander("⚙️ 參數調節", expanded=False):
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

if st.button("🚀 計算人馬合作因子（並寫入資料庫）", type="primary"):
    with st.spinner("從資料庫讀取歷史並計算人馬合作..."):
        try:
            df, src = ui_utils.get_history_df_for_compute()
            if df.empty:
                st.error("資料庫沒有可用歷史賽果，無法計算。")
            else:
                calc = FactorCalculator()
                # get_history_df_for_compute 已含 base score；避免重複也無妨
                if 'raw_score' not in df.columns:
                    df = calc.calculate_base_score(df)
                hj_df = calc.calculate_horse_jockey_factor(df)
                n = calc.save_factor_scores(hj_df)
                st.session_state['hj_df_indep'] = hj_df
                st.success(
                    f"完成：{len(hj_df)} 筆（bucket={GLOBAL_BUCKET}），"
                    f"已寫入 factor_scores {n} 列。資料來源：{src}"
                )
        except Exception as e:
            st.error(f"計算失敗：{e}")

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
    st.info("尚未有人馬合作因子。按上方按鈕即可從雲端歷史直接計算並寫入，不必先回主頁。")
