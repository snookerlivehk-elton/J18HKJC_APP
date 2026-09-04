import streamlit as st
import pandas as pd
import numpy as np
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="步速與分段形勢", layout="wide")
st.title("⏱️ 步速與分段形勢因子 (Pace & Sectional)")
st.caption("由歷史分段走位推跑法；選排位場次後過濾顯示本場馬匹。")

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.sidebar.expander("⚙️ 參數調節", expanded=False):
    ModelConfig.PACE_SMOOTH_C = st.number_input("PACE_SMOOTH_C", min_value=1, value=ModelConfig.PACE_SMOOTH_C)
    ModelConfig.CLOSER_BONUS_WEIGHT = st.slider("後追馬加分", 1.0, 3.0, ModelConfig.CLOSER_BONUS_WEIGHT, 0.1)
    ModelConfig.FRONT_RUNNER_BONUS_WEIGHT = st.slider(
        "前領馬加分", 1.0, 3.0, ModelConfig.FRONT_RUNNER_BONUS_WEIGHT, 0.1
    )

can_compute = 'raw_df' in st.session_state and not st.session_state['raw_df'].empty
if st.button("🚀 解析歷史分段走位", type="primary", disabled=not can_compute):
    with st.spinner("提取分段位置..."):
        calc = FactorCalculator()
        df = calc.extract_sectional_positions(st.session_state['raw_df'].copy())
        df = df.dropna(subset=['early_position', 'positions_gained'])

        pace_df = df.groupby('horse_name').agg({
            'early_position': ['mean', 'count'],
            'positions_gained': 'mean',
            'finish_order_num': 'mean',
        }).reset_index()
        pace_df.columns = [
            'horse_name', 'avg_early_pos', 'runs_with_sections',
            'avg_positions_gained', 'avg_finish',
        ]

        conditions = [
            (pace_df['avg_early_pos'] <= 4.5),
            (pace_df['avg_early_pos'] <= 8.5),
            (pace_df['avg_early_pos'] > 8.5),
        ]
        pace_df['running_style'] = np.select(
            conditions,
            ['前領 (Front-Runner)', '居中 (Mid-Pack)', '後追 (Closer)'],
            default='未知',
        )

        global_avg = pace_df['avg_positions_gained'].mean()
        c = ModelConfig.PACE_SMOOTH_C
        pace_df['smoothed_positions_gained'] = (
            (pace_df['avg_positions_gained'] * pace_df['runs_with_sections'] + c * global_avg)
            / (pace_df['runs_with_sections'] + c)
        )
        pace_df = pace_df.sort_values('smoothed_positions_gained', ascending=False)
        st.session_state['pace_df'] = pace_df
        st.success(f"完成：{len(pace_df)} 匹馬")

if 'pace_df' not in st.session_state or st.session_state['pace_df'].empty:
    st.info("請先計算分段走位。")
    st.stop()

pace_df = st.session_state['pace_df']
upcoming_options = ui_utils.get_upcoming_races_list()
st.subheader("🔮 排位場次過濾")

selected_race_id = "None"
if upcoming_options:
    selected_race_id = st.selectbox(
        "選擇賽事：",
        options=[opt[0] for opt in upcoming_options],
        format_func=lambda x: next(opt[1] for opt in upcoming_options if opt[0] == x),
        key="pace_race",
    )

display_df = pace_df.copy()
if selected_race_id != "None":
    runners = ui_utils.get_runners_for_race(selected_race_id)
    if runners.empty:
        st.warning("此場無排位馬匹")
    else:
        names = set(runners['horse_name'].tolist())
        # 合併排位列 + 跑法
        merged = runners[['horse_no', 'horse_name', 'draw', 'jockey_name', 'trainer_name']].copy()
        merged = merged.merge(pace_df, on='horse_name', how='left')
        hits = merged['running_style'].notna().sum()
        st.caption(f"本場有跑法資料：{hits}/{len(merged)}")
        display_df = merged.sort_values('smoothed_positions_gained', ascending=False, na_position='last')

for col in ('avg_early_pos', 'avg_positions_gained', 'avg_finish', 'smoothed_positions_gained'):
    if col in display_df.columns:
        display_df[col] = display_df[col].map(lambda x: '' if pd.isna(x) else f'{x:.2f}')

rename = {
    'horse_no': '馬號',
    'horse_name': '馬名',
    'draw': '檔位',
    'jockey_name': '騎師',
    'trainer_name': '練馬師',
    'runs_with_sections': '有效出賽',
    'running_style': '跑法',
    'avg_early_pos': '平均早段',
    'avg_finish': '平均名次',
    'avg_positions_gained': '平均追回',
    'smoothed_positions_gained': '平滑後追指數',
}
display_df = display_df.rename(columns={k: v for k, v in rename.items() if k in display_df.columns})
st.dataframe(display_df, hide_index=True, use_container_width=True, height=480)
