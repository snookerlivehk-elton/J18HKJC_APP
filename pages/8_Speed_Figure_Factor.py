import streamlit as st
import pandas as pd
from config import ModelConfig
from factor_calculator import FactorCalculator
import ui_utils

st.set_page_config(page_title="速度指數 (Speed Figure)", layout="wide")
st.title("⏱️ 速度指數與絕對時間 (Speed Figure & FSR)")
st.caption("選排位場次後，顯示本場各馬歷史 Peak / EMA / FSR。")

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.sidebar.expander("⚙️ 參數調節", expanded=False):
    ModelConfig.FSR_PENALTY_THRESHOLD = st.number_input(
        "FSR 慢步速懲罰閥值", min_value=100.0, value=ModelConfig.FSR_PENALTY_THRESHOLD
    )
    ModelConfig.FSR_BONUS_THRESHOLD = st.number_input(
        "FSR 快步速獎勵閥值", max_value=100.0, value=ModelConfig.FSR_BONUS_THRESHOLD
    )
    ModelConfig.TIME_EMA_ALPHA = st.slider(
        "EMA Alpha", 0.1, 1.0, ModelConfig.TIME_EMA_ALPHA, 0.1
    )

can_compute = 'raw_df' in st.session_state and not st.session_state['raw_df'].empty
if st.button("🚀 計算速度指數", type="primary", disabled=not can_compute):
    with st.spinner("計算 Speed Figure / FSR..."):
        calc = FactorCalculator()
        df = calc.extract_time_and_fsr(st.session_state['raw_df'].copy())
        df = df.dropna(subset=['speed_figure', 'fsr'])
        df = df.sort_values(['horse_name', 'racing_date'], ascending=[True, False])

        horse_stats = []
        for horse, group in df.groupby('horse_name'):
            recent_3 = group.head(3)['speed_figure'].values
            ema = (
                pd.Series(recent_3[::-1]).ewm(alpha=ModelConfig.TIME_EMA_ALPHA, adjust=False).mean().iloc[-1]
                if len(recent_3) else group['speed_figure'].max()
            )
            horse_stats.append({
                'horse_name': horse,
                'runs': len(group),
                'peak_speed': group['speed_figure'].max(),
                'current_ema': ema,
                'avg_fsr': group['fsr'].mean(),
            })
        speed_df = pd.DataFrame(horse_stats).sort_values('current_ema', ascending=False)
        st.session_state['speed_df'] = speed_df
        st.success(f"完成：{len(speed_df)} 匹馬")

if 'speed_df' not in st.session_state or st.session_state['speed_df'].empty:
    st.info("請先計算速度指數。")
    st.stop()

speed_df = st.session_state['speed_df']
upcoming_options = ui_utils.get_upcoming_races_list()
st.subheader("🔮 排位場次過濾")

selected_race_id = "None"
if upcoming_options:
    selected_race_id = st.selectbox(
        "選擇賽事：",
        options=[opt[0] for opt in upcoming_options],
        format_func=lambda x: next(opt[1] for opt in upcoming_options if opt[0] == x),
        key="speed_race",
    )

if selected_race_id != "None":
    runners = ui_utils.get_runners_for_race(selected_race_id)
    if runners.empty:
        st.warning("此場無排位馬匹")
        display_df = pd.DataFrame()
    else:
        merged = runners[['horse_no', 'horse_name', 'draw', 'jockey_name', 'trainer_name']].copy()
        merged = merged.merge(speed_df, on='horse_name', how='left')
        hits = merged['current_ema'].notna().sum()
        st.caption(f"本場有速度指數：{hits}/{len(merged)}")
        display_df = merged.sort_values('current_ema', ascending=False, na_position='last')
else:
    q = st.text_input("搜尋馬名", "")
    display_df = speed_df.copy()
    if q:
        display_df = display_df[display_df['horse_name'].str.contains(q, na=False)]

if not display_df.empty:
    out = display_df.copy()
    for col, fmt in (('peak_speed', '{:+.2f}s'), ('current_ema', '{:+.2f}s'), ('avg_fsr', '{:.1f}%')):
        if col in out.columns:
            out[col] = out[col].map(lambda x: '' if pd.isna(x) else fmt.format(x))
    out = out.rename(columns={
        'horse_no': '馬號',
        'horse_name': '馬名',
        'draw': '檔位',
        'jockey_name': '騎師',
        'trainer_name': '練馬師',
        'runs': '有效紀錄',
        'peak_speed': '歷史峰值',
        'current_ema': '近況 EMA',
        'avg_fsr': '平均 FSR',
    })
    st.dataframe(out, hide_index=True, use_container_width=True, height=480)
