import streamlit as st
import pandas as pd
from config import ModelConfig
from inference_engine import InferenceEngine
import ui_utils

st.set_page_config(page_title="HKJC Speed Guide", layout="wide")
st.title("⚡ HKJC Speed Guide（官方速勢能量）")
st.caption("顯示 upcoming_speedguide；若爬蟲尚未解析入庫，此頁會是空的。權重寫入 ModelConfig 供推論使用。")

engine = InferenceEngine()
races = engine.get_upcoming_races()

with st.sidebar.expander("⚙️ 推論權重（寫入 ModelConfig）", expanded=True):
    ModelConfig.WEIGHT_SG_FORM = st.slider(
        "WEIGHT_SG_FORM", 0.0, 2.0, float(ModelConfig.WEIGHT_SG_FORM), 0.1
    )
    ModelConfig.WEIGHT_SG_ENERGY = st.slider(
        "WEIGHT_SG_ENERGY", 0.0, 2.0, float(ModelConfig.WEIGHT_SG_ENERGY), 0.1
    )
    ModelConfig.WEIGHT_SG_DELTA = st.slider(
        "WEIGHT_SG_DELTA", -1.0, 2.0, float(ModelConfig.WEIGHT_SG_DELTA), 0.1
    )

if races.empty:
    st.warning("尚無排位賽事。請先到資料控制中心抓排位表。")
    st.stop()

options = ui_utils.get_upcoming_races_list()
# 去掉純歷史選項
race_opts = [o for o in options if o[0] != "None"]
selected = st.selectbox(
    "選擇賽事：",
    options=[o[0] for o in race_opts],
    format_func=lambda x: next(o[1] for o in race_opts if o[0] == x),
)

runners = ui_utils.get_runners_for_race(selected)
if runners.empty:
    st.warning("此場無馬匹。")
    st.stop()

# runners 已 LEFT JOIN speedguide
show_cols = [
    c for c in [
        'horse_no', 'horse_name', 'draw', 'jockey_name', 'trainer_name',
        'form_rating', 'speed_energy', 'speed_energy_delta',
    ] if c in runners.columns
]
out = runners[show_cols].copy()
has_sg = out['form_rating'].notna().any() if 'form_rating' in out.columns else False
if not has_sg:
    st.warning(
        "此場尚未有 Speed Guide 資料（爬蟲解析仍可能是 TODO）。"
        "排位列仍會顯示，官方評級欄為空。"
    )

out = out.rename(columns={
    'horse_no': '馬號',
    'horse_name': '馬名',
    'draw': '檔位',
    'jockey_name': '騎師',
    'trainer_name': '練馬師',
    'form_rating': '狀態評級',
    'speed_energy': '速勢能量',
    'speed_energy_delta': '能量差值',
})
st.dataframe(out, hide_index=True, use_container_width=True, height=480)
