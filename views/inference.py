"""
推論儀表板：分場次融合總分 + 各因子雷達圖。
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from inference_engine import InferenceEngine
from config import ModelConfig
from bucket_utils import format_class_display
from ui_theme import inject_admin_css, page_header
from radar_charts import build_radar_figure, RADAR_AXES
import ui_param_help as ph

inject_admin_css()
page_header("融合預測", "總分排序 · 場內 z 勝率 · 雷達展示")
st.markdown(
    """
**三層勿混用**
1. **因子／總分**（歷史 Z + 加權，可正可負）— 排序  
2. **雷達**（同場每軸最低→中心、最高→外緣；原始負分完整參與）— 只顯示  
3. **模型勝率**（場內 z → softmax）— Kelly／外傳  
"""
)

SUMMARY_COLS = [
    "預測排名", "馬號", "馬名", "檔位", "騎師", "練馬師",
    "負磅", "體重", "評分", "評分升降", "配備",
    "命中", "SG貢獻", "總預測分", "模型勝率%",
]

FACTOR_COLS = [
    "預測排名", "馬號", "馬名",
    "騎師分", "練馬師分", "騎練分", "檔位分",
    "近績分", "步速分", "速度分", "SG貢獻", "總預測分", "模型勝率%",
]


def highlight_top3(s):
    if s["預測排名"] == 1:
        return ["background-color: #ffd700; color: black"] * len(s)
    if s["預測排名"] == 2:
        return ["background-color: #e3e4e5; color: black"] * len(s)
    if s["預測排名"] == 3:
        return ["background-color: #cd7f32; color: black"] * len(s)
    return [""] * len(s)


engine = InferenceEngine()
races_df = engine.get_upcoming_races()

if races_df.empty:
    st.warning("目前沒有即將舉行的賽事。請先到「資料控制中心」抓取排位表。")
    st.stop()

scores_preview = engine.calc.load_factor_scores(
    factor_types=["JOCKEY", "TRAINER", "SYNERGY", "DRAW", "HORSE", "PACE", "SPEED"]
)
if scores_preview.empty:
    st.error("`factor_scores` 是空的。請回主頁執行「重算並寫入因子分數」後再預測。")
    st.stop()

types = sorted(scores_preview["factor_type"].unique().tolist())
st.caption(f"資料庫已有 {len(scores_preview)} 筆因子分數（{types}）。")

with st.expander("融合權重（ModelConfig）", expanded=True):
    st.caption("游標停在標籤旁 ⓘ 可看功能與調節後變化。調權重會即時影響總分排序與模型勝率。")
    ModelConfig.WEIGHT_JOCKEY = st.slider(
        "騎師", 0.0, 3.0, float(ModelConfig.WEIGHT_JOCKEY), 0.1, help=ph.weight("騎師")
    )
    ModelConfig.WEIGHT_TRAINER = st.slider(
        "練馬師", 0.0, 3.0, float(ModelConfig.WEIGHT_TRAINER), 0.1, help=ph.weight("練馬師")
    )
    ModelConfig.WEIGHT_SYNERGY = st.slider(
        "騎練", 0.0, 3.0, float(ModelConfig.WEIGHT_SYNERGY), 0.1, help=ph.weight("騎練合作")
    )
    ModelConfig.WEIGHT_DRAW = st.slider(
        "檔位", 0.0, 3.0, float(ModelConfig.WEIGHT_DRAW), 0.1, help=ph.weight("檔位")
    )
    ModelConfig.WEIGHT_RECENT_FORM = st.slider(
        "近績", 0.0, 3.0, float(ModelConfig.WEIGHT_RECENT_FORM), 0.1, help=ph.weight("近績")
    )
    ModelConfig.WEIGHT_PACE = st.slider(
        "步速", 0.0, 3.0, float(ModelConfig.WEIGHT_PACE), 0.1, help=ph.weight("步速／跑法")
    )
    ModelConfig.WEIGHT_SPEED_FIGURE = st.slider(
        "速度", 0.0, 3.0, float(ModelConfig.WEIGHT_SPEED_FIGURE), 0.1, help=ph.weight("速度指數")
    )
    ModelConfig.WEIGHT_SG_FORM = st.slider(
        "SG·Fitness", 0.0, 3.0, float(ModelConfig.WEIGHT_SG_FORM), 0.1, help=ph.WEIGHT_SG_FORM
    )
    ModelConfig.WEIGHT_SG_ENERGY = st.slider(
        "SG·能量Z", 0.0, 3.0, float(ModelConfig.WEIGHT_SG_ENERGY), 0.1, help=ph.WEIGHT_SG_ENERGY
    )
    ModelConfig.WEIGHT_SG_DELTA = st.slider(
        "SG·差值", -1.0, 3.0, float(ModelConfig.WEIGHT_SG_DELTA), 0.1, help=ph.WEIGHT_SG_DELTA
    )
    st.divider()
    ModelConfig.SOFTMAX_WITHIN_RACE_Z = st.checkbox(
        "勝率前先做場內 z-score（建議開）",
        value=bool(ModelConfig.SOFTMAX_WITHIN_RACE_Z),
        help=ph.SOFTMAX_Z,
    )
    ModelConfig.SOFTMAX_TEMPERATURE = st.slider(
        "SOFTMAX 溫度（勝率尖銳度）",
        0.5, 8.0, float(ModelConfig.SOFTMAX_TEMPERATURE), 0.1,
        help=ph.SOFTMAX_T,
    )

race_options = []
for _, row in races_df.iterrows():
    label = (
        f"第 {row['race_num']} 場｜{row['racing_date']} {row['course']} "
        f"{row['track']} {row['distance_m']}米（{format_class_display(row['class'])}）"
    )
    race_options.append((row["race_id"], label, int(row["race_num"])))

view_mode = st.radio("檢視模式", ["單場深入", "整日總覽"], horizontal=True)

weight_key = (
    ModelConfig.WEIGHT_JOCKEY,
    ModelConfig.WEIGHT_TRAINER,
    ModelConfig.WEIGHT_SYNERGY,
    ModelConfig.WEIGHT_DRAW,
    ModelConfig.WEIGHT_RECENT_FORM,
    ModelConfig.WEIGHT_PACE,
    ModelConfig.WEIGHT_SPEED_FIGURE,
    ModelConfig.WEIGHT_SG_FORM,
    ModelConfig.WEIGHT_SG_ENERGY,
    ModelConfig.WEIGHT_SG_DELTA,
    ModelConfig.SOFTMAX_TEMPERATURE,
    ModelConfig.SOFTMAX_WITHIN_RACE_Z,
)


@st.cache_data(ttl=120, show_spinner="計算融合分數…")
def _cached_predict(race_id: str, _weights: tuple):
    eng = InferenceEngine()
    df, info, meta = eng.predict_race(race_id)
    info_dict = info.to_dict() if hasattr(info, "to_dict") else (dict(info) if info is not None else {})
    safe_info = {}
    for k, v in info_dict.items():
        if hasattr(v, "item"):
            try:
                safe_info[k] = v.item()
                continue
            except Exception:
                pass
        safe_info[k] = str(v) if hasattr(v, "isoformat") else v
    return {
        "df": df.to_dict(orient="list") if df is not None and not df.empty else {},
        "columns": list(df.columns) if df is not None and not df.empty else [],
        "info": safe_info,
        "meta": meta,
    }


def load_prediction(race_id: str):
    payload = _cached_predict(race_id, weight_key)
    if not payload["columns"]:
        return pd.DataFrame(), payload["info"], payload["meta"]
    return pd.DataFrame(payload["df"], columns=payload["columns"]), payload["info"], payload["meta"]


def render_race_block(race_id: str, race_label: str, *, compact: bool = False):
    predictions_df, _race_info, meta = load_prediction(race_id)

    st.markdown(f"### {race_label}")
    if not meta.get("bucket_valid") and not meta.get("band_bucket_valid"):
        st.error(
            f"Bucket 無效：細=`{meta.get('bucket_id')}`／粗=`{meta.get('band_bucket_id')}`。"
        )
        return

    hc = meta.get("hit_counts") or {}
    st.caption(
        f"細桶 `{meta.get('bucket_id')}`｜粗桶 `{meta.get('band_bucket_id')}`｜"
        f"匹配率 {meta.get('match_rate', 0):.0%}｜"
        f"J{hc.get('JOCKEY', 0)} T{hc.get('TRAINER', 0)} S{hc.get('SYNERGY', 0)} "
        f"D{hc.get('DRAW', 0)} H{hc.get('HORSE', 0)} P{hc.get('PACE', 0)} V{hc.get('SPEED', 0)}｜"
        f"softmax T={meta.get('softmax_temperature')}｜"
        f"場內z={meta.get('softmax_within_race_z')}｜"
        f"勝率加總={meta.get('win_prob_sum', 0):.4f}"
    )

    if predictions_df.empty:
        st.warning("此場無預測結果。")
        return

    if not compact and "模型勝率%" in predictions_df.columns:
        top = predictions_df.iloc[0]
        m1, m2, m3 = st.columns(3)
        m1.metric("首位總分", f"{top['總預測分']:.2f}")
        m2.metric("首位模型勝率", f"{top['模型勝率%']:.1f}%")
        m3.metric("場內馬數", f"{len(predictions_df)}")

    show = [c for c in SUMMARY_COLS if c in predictions_df.columns]
    st.dataframe(
        predictions_df[show].style.apply(highlight_top3, axis=1),
        use_container_width=True,
        height=320 if compact else 440,
        hide_index=True,
    )

    if compact:
        return

    with st.expander("各因子分數明細（可負；原始 Z）", expanded=False):
        fcols = [c for c in FACTOR_COLS if c in predictions_df.columns]
        st.dataframe(predictions_df[fcols], use_container_width=True, hide_index=True)

    with st.expander("外傳凱利／賠率系統 JSON", expanded=False):
        import json
        payload = engine.export_kelly_payload(race_id)
        st.code(json.dumps(payload, ensure_ascii=False, indent=2), language="json")
        st.download_button(
            "下載本場 JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2),
            file_name=f"kelly_payload_{race_id}.json",
            mime="application/json",
            key=f"dl_kelly_{race_id}",
        )
        st.caption(
            "Kelly：小數賠率 o、b=o−1、p=model_win_prob、q=1−p → f*=(b·p−q)/b。"
            "只傳勝率與總分；即時賠率由對方系統接入。"
        )

    st.subheader("因子雷達圖")
    default_top = [int(x) for x in predictions_df.head(3)["馬號"].tolist()]
    all_labels = {
        int(r["馬號"]): f"{int(r['馬號'])} {r['馬名']}（#{int(r['預測排名'])}｜總分 {r['總預測分']}）"
        for _, r in predictions_df.iterrows()
    }
    pick = st.multiselect(
        "疊加顯示的馬（建議 2–4 匹）",
        options=list(all_labels.keys()),
        default=default_top,
        format_func=lambda x: all_labels.get(x, str(x)),
        key=f"radar_pick_{race_id}",
    )
    if not pick:
        st.info("請至少選一匹馬。")
        return

    fig = build_radar_figure(predictions_df, pick, height=540, mobile=False)
    if fig is None:
        st.warning("未安裝 plotly，無法顯示雷達圖。請把 `plotly` 加入 requirements 後重新部署。")
        return

    st.plotly_chart(fig, use_container_width=True)

    focus = int(pick[0])
    drow = predictions_df[predictions_df["馬號"].astype(int) == focus].iloc[0]
    st.caption(f"原始因子分（未正規化）— {int(drow['馬號'])} {drow['馬名']}")
    cols = st.columns(len(RADAR_AXES))
    for i, (col, label) in enumerate(RADAR_AXES):
        cols[i].metric(label, f"{float(drow[col]):.2f}")


if view_mode == "整日總覽":
    st.info("整日總覽每場顯示基本資料與融合總分；切換「單場深入」可看雷達圖。")
    for race_id, label, _num in race_options:
        render_race_block(race_id, label, compact=True)
        st.divider()
else:
    selected_race_id = st.selectbox(
        "選擇場次",
        options=[o[0] for o in race_options],
        format_func=lambda x: next(o[1] for o in race_options if o[0] == x),
    )
    label = next(o[1] for o in race_options if o[0] == selected_race_id)
    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("重新計算", type="secondary"):
            _cached_predict.clear()
            st.rerun()
    render_race_block(selected_race_id, label, compact=False)
