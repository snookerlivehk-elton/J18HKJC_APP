import streamlit as st
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="騎練合作因子 (Synergy)", layout="wide")
st.title("🤝 騎練合作因子 (Synergy Factor)")

if 'raw_df' not in st.session_state:
    st.warning("請先至主頁面載入基礎歷史數據！")
    st.stop()

with st.sidebar.expander("⚙️ 參數調節 (AI 最佳化入口)", expanded=True):
    st.markdown("針對騎練合作獨立調整超參數")
    ModelConfig.WIN_WEIGHT = st.slider("WIN_WEIGHT (勝出權重)", 0.5, 2.0, ModelConfig.WIN_WEIGHT, 0.1)
    ModelConfig.PLACE_WEIGHT = st.slider("PLACE_WEIGHT (位置權重)", 0.0, 1.0, ModelConfig.PLACE_WEIGHT, 0.05)
    ModelConfig.SYNERGY_SMOOTH_C = st.number_input("SYNERGY_SMOOTH_C (虛擬出賽限制)", min_value=1, value=ModelConfig.SYNERGY_SMOOTH_C)
    
    decay_str = st.text_input("SYNERGY_DECAY (時間衰減)", value=",".join(map(str, ModelConfig.SYNERGY_DECAY)))
    ModelConfig.SYNERGY_DECAY = [float(x.strip()) for x in decay_str.split(",")]

if st.button("🚀 獨立計算合作因子", type="primary"):
    with st.spinner("計算中..."):
        calc = FactorCalculator()
        df = calc.calculate_base_score(st.session_state['raw_df'].copy())
        df['synergy_name'] = df['jockey_name'].fillna('未知').astype(str) + " & " + df['trainer_name'].fillna('未知').astype(str)
        s_df = calc.calculate_entity_factor(df, 'synergy_name', ModelConfig.SYNERGY_DECAY, ModelConfig.SYNERGY_SMOOTH_C)
        s_df['factor_type'] = 'SYNERGY'
        s_df = s_df.rename(columns={'synergy_name': 'entity_name'})
        st.session_state['s_df_indep'] = s_df
        st.success("合作因子計算完成！")

if 's_df_indep' in st.session_state:
    st.divider()
    
    upcoming_options = ui_utils.get_upcoming_races_list()
    if upcoming_options:
        st.subheader("🔮 結合明日排位表 (對應預測)")
        selected_race_id = st.selectbox(
            "選擇明日賽事 (自動帶入該場 Bucket 與參賽騎練組合)：",
            options=[opt[0] for opt in upcoming_options],
            format_func=lambda x: next(opt[1] for opt in upcoming_options if opt[0] == x)
        )
        
        if selected_race_id != "None":
            target_bucket = ui_utils.get_bucket_for_race(selected_race_id)
            runners_df = ui_utils.get_runners_for_race(selected_race_id)
            if not runners_df.empty and target_bucket:
                st.info(f"自動匹配分桶：`{target_bucket}`")
                # 組合騎師與練馬師名稱
                runners_df['synergy_name'] = runners_df['jockey_name'] + " & " + runners_df['trainer_name']
                synergy_in_race = runners_df['synergy_name'].unique().tolist()
                ui_utils.display_factor_details(st.session_state['s_df_indep'], target_bucket, "騎練組合", filter_entities=synergy_in_race)
            else:
                st.warning("無法取得該場賽事資訊。")
        else:
            selected_bucket = st.selectbox("📍 選擇歷史分桶 (Bucket)", st.session_state['buckets'])
            ui_utils.display_factor_details(st.session_state['s_df_indep'], selected_bucket, "騎練組合")
    else:
        selected_bucket = st.selectbox("📍 選擇歷史分桶 (Bucket)", st.session_state['buckets'])
        ui_utils.display_factor_details(st.session_state['s_df_indep'], selected_bucket, "騎練組合")
