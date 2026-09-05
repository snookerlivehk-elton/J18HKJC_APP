import streamlit as st
import pandas as pd
import subprocess
import os
from config import ModelConfig
from inference_engine import InferenceEngine
import ui_utils
import ui_param_help as ph

st.title("⚡ 官方速勢能量（Speed Guide）")
st.caption(
    "資料來自 HKJC CMS JSON（`sg_index` / `sg_race_N`），寫入 `upcoming_speedguide` 後直接進推論。"
    "官方通常於賽日前一日中午左右上架；缺值時推論給 0，不假裝官方分。"
)

engine = InferenceEngine()
races = engine.get_upcoming_races()

with st.expander("⚙️ 推論權重（寫入 ModelConfig）", expanded=True):
    st.caption("游標停在標籤旁 ⓘ 可看功能與調節後變化；調完表格「SG貢獻／評分排名」會即時重算。")
    ModelConfig.WEIGHT_SG_FORM = st.slider(
        "SG·狀態／Fitness",
        0.0, 2.0, float(ModelConfig.WEIGHT_SG_FORM), 0.1,
        help=ph.WEIGHT_SG_FORM,
    )
    ModelConfig.WEIGHT_SG_ENERGY = st.slider(
        "SG·能量同場 Z",
        0.0, 2.0, float(ModelConfig.WEIGHT_SG_ENERGY), 0.1,
        help=ph.WEIGHT_SG_ENERGY,
    )
    ModelConfig.WEIGHT_SG_DELTA = st.slider(
        "SG·能量差值",
        -1.0, 2.0, float(ModelConfig.WEIGHT_SG_DELTA), 0.1,
        help=ph.WEIGHT_SG_DELTA,
    )

with st.expander("抓取 / 更新 Speed Guide", expanded=False):
    st.markdown(
        "爬蟲讀取 [官方速勢走位圖](https://racing.hkjc.com/zh-hk/local/info/speedpro/speedguide?raceno=1) "
        "背後的 CMS JSON；日期與場地以 CMS 為準（下方僅核對）。"
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        sg_date = st.text_input("核對日期 YYYY/MM/DD", value="2026/09/06", key="sg_page_date")
    with c2:
        sg_course = st.selectbox("核對場地", ["ST", "HV"], key="sg_page_course")
    with c3:
        st.write("")
        st.write("")
        run_btn = st.button("立即抓取並寫入 DB", type="primary", use_container_width=True)
    if run_btn:
        with st.spinner("正在抓取 Speed Guide…"):
            try:
                env = os.environ.copy()
                result = subprocess.run(
                    ["python", "speedguide_crawler.py", "--date", sg_date, "--course", sg_course],
                    capture_output=True, text=True, check=True, env=env,
                )
                st.success("抓取完成。請重新選擇賽事或重新整理。")
                with st.expander("執行日誌"):
                    st.text(result.stdout or "(no stdout)")
                    if result.stderr:
                        st.text(result.stderr)
            except subprocess.CalledProcessError as e:
                st.error(f"失敗：\n{e.stderr or e.stdout}")

if races.empty:
    st.warning("尚無排位賽事。請先到資料控制中心抓排位表。")
    st.stop()

options = ui_utils.get_upcoming_races_list()
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

base_cols = [
    c for c in [
        'horse_no', 'horse_name', 'draw', 'jockey_name', 'trainer_name',
        'form_rating', 'speed_energy', 'speed_energy_delta',
    ] if c in runners.columns
]
out = runners[base_cols].copy()

has_form = 'form_rating' in out.columns and out['form_rating'].notna().any()
has_energy = 'speed_energy' in out.columns and out['speed_energy'].notna().any()
has_delta = 'speed_energy_delta' in out.columns and out['speed_energy_delta'].notna().any()
has_sg = has_form or has_energy or has_delta

if not has_sg:
    st.warning(
        "此場尚未有 Speed Guide 資料。"
        "請用上方「立即抓取」，或到資料控制中心執行速勢能量爬蟲。"
    )
    display = out.rename(columns={
        'horse_no': '馬號',
        'horse_name': '馬名',
        'draw': '檔位',
        'jockey_name': '騎師',
        'trainer_name': '練馬師',
        'form_rating': 'Fitness碼',
        'speed_energy': '速勢能量',
        'speed_energy_delta': '能量差值',
    })
    st.dataframe(display, hide_index=True, use_container_width=True, height=480)
    st.stop()

# —— 評分（與 inference_engine 公式一致）——
form_s = (
    out['form_rating'].map(engine._map_form_rating)
    if 'form_rating' in out.columns else pd.Series(0.0, index=out.index)
)
energy_z = engine._within_field_z(
    out['speed_energy'] if 'speed_energy' in out.columns else pd.Series(dtype=float)
)
delta = pd.to_numeric(
    out['speed_energy_delta'] if 'speed_energy_delta' in out.columns else 0.0,
    errors='coerce',
).fillna(0.0)

sg_form_w = form_s * ModelConfig.WEIGHT_SG_FORM
sg_energy_w = energy_z.fillna(0.0) * ModelConfig.WEIGHT_SG_ENERGY
sg_delta_w = delta * ModelConfig.WEIGHT_SG_DELTA
sg_total = (sg_form_w + sg_energy_w + sg_delta_w).round(2)

scored = pd.DataFrame({
    '評分排名': 0,  # fill after sort
    '馬號': out['horse_no'],
    '馬名': out['horse_name'],
    'Fitness': out['form_rating'].map(engine.fitness_label) if 'form_rating' in out.columns else '',
    'Fitness分': form_s.round(2),
    '速勢能量': pd.to_numeric(out.get('speed_energy'), errors='coerce'),
    '能量Z': energy_z.round(2),
    '能量差值': delta,
    'SG貢獻': sg_total,
    '其中_FORM': sg_form_w.round(2),
    '其中_ENERGY': sg_energy_w.round(2),
    '其中_DELTA': sg_delta_w.round(2),
    '檔位': out['draw'] if 'draw' in out.columns else None,
    '騎師': out['jockey_name'] if 'jockey_name' in out.columns else None,
    '練馬師': out['trainer_name'] if 'trainer_name' in out.columns else None,
})
scored = scored.sort_values('SG貢獻', ascending=False).reset_index(drop=True)
scored['評分排名'] = scored.index + 1

top = scored.iloc[0]
m1, m2, m3 = st.columns(3)
m1.metric("本場最高 SG貢獻", f"{top['SG貢獻']:.2f}", help="側欄權重加權後的 Speed Guide 總分")
m2.metric("領先馬", f"{int(top['馬號'])} {top['馬名']}")
m3.metric(
    "權重 FORM/ENERGY/DELTA",
    f"{ModelConfig.WEIGHT_SG_FORM:.1f} / {ModelConfig.WEIGHT_SG_ENERGY:.1f} / {ModelConfig.WEIGHT_SG_DELTA:.1f}",
)

st.subheader("Speed Guide 評分（依 SG貢獻排序）")
st.dataframe(scored, hide_index=True, use_container_width=True, height=520)

st.markdown(
    f"""
**評分公式**

`SG貢獻 = Fitness分×{ModelConfig.WEIGHT_SG_FORM} + 能量同場Z×{ModelConfig.WEIGHT_SG_ENERGY} + 能量差值×{ModelConfig.WEIGHT_SG_DELTA}`

- **Fitness**：`0` = 倒轉拇指（**-1.5**）；`1/2/3` = 👍×1/×2/×3（**0 / 1 / 2**）
- **能量Z**：同場 `speed_energy` 的 Z-Score
- **能量差值**：官方主排序（SpeedPRO Energy − Energy Required），正值較看好
"""
)
