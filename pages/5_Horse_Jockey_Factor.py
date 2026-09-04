import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="人馬合作因子 (Horse-Jockey Synergy)", layout="wide")
st.title("🏇🤝 人馬合作因子 (Horse-Jockey Synergy)")
st.markdown("""
這個因子專門衡量**特定馬匹與特定騎師**的歷史合作表現。
在量化模型中，如果「現任騎師的 Z-Score」高於「前任騎師的 Z-Score」，這將觸發 **換人效應 (Switch Delta)** 的加分，這是幕後搏殺的重要信號！
""")

if 'raw_df' not in st.session_state:
    st.warning("請先至主頁面載入基礎歷史數據！")
    st.stop()

with st.sidebar.expander("⚙️ 參數調節 (AI 最佳化入口)", expanded=True):
    st.markdown("針對人馬合作獨立調整超參數")
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT (勝出權重)", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT (位置權重)", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.HORSE_JOCKEY_SMOOTH_C = st.number_input("HORSE_JOCKEY_SMOOTH_C (虛擬出賽限制)", min_value=1, value=ModelConfig.HORSE_JOCKEY_SMOOTH_C)
    
    decay_str = st.text_input("HORSE_JOCKEY_DECAY (時間衰減)", value=",".join(map(str, ModelConfig.HORSE_JOCKEY_DECAY)))
    ModelConfig.HORSE_JOCKEY_DECAY = [float(x.strip()) for x in decay_str.split(",")]

if st.button("🚀 獨立計算人馬合作因子", type="primary"):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        # 組合人馬名稱
        df['horse_jockey_name'] = df['horse_name'].fillna('未知').astype(str) + " & " + df['jockey_name'].fillna('未知').astype(str)
        hj_df = calc.calculate_entity_factor(df, 'horse_jockey_name', ModelConfig.HORSE_JOCKEY_DECAY, ModelConfig.HORSE_JOCKEY_SMOOTH_C)
        hj_df['factor_type'] = 'HORSE_JOCKEY'
        hj_df = hj_df.rename(columns={'horse_jockey_name': 'entity_name'})
        st.session_state['hj_df_indep'] = hj_df
        st.success("人馬合作因子計算完成！")

if 'hj_df_indep' in st.session_state:
    st.divider()
    
    upcoming_options = ui_utils.get_upcoming_races_list()
    if upcoming_options:
        st.subheader("🔮 結合明日排位表 (對應預測)")
        selected_race_id = st.selectbox(
            "選擇明日賽事 (自動帶入參賽人馬組合)：",
            options=[opt[0] for opt in upcoming_options],
            format_func=lambda x: next(opt[1] for opt in upcoming_options if opt[0] == x)
        )
        
        if selected_race_id != "None":
            runners_df = ui_utils.get_runners_for_race(selected_race_id)
            if not runners_df.empty:
                st.info("人馬合作因子不區分賽道與距離，直接比對韁繩相性。")
                runners_df['horse_jockey_name'] = runners_df['horse_name'].fillna('未知').astype(str) + " & " + runners_df['jockey_name'].fillna('未知').astype(str)
                hj_in_race = runners_df['horse_jockey_name'].unique().tolist()
                # 這裡強制指定 bucket 為 Global
                ui_utils.display_factor_details(st.session_state['hj_df_indep'], 'Global', "人馬組合", filter_entities=hj_in_race)
            else:
                st.warning("無法取得該場賽事資訊。")
        else:
            ui_utils.display_factor_details(st.session_state['hj_df_indep'], 'Global', "人馬組合")
    else:
        ui_utils.display_factor_details(st.session_state['hj_df_indep'], 'Global', "人馬組合")
