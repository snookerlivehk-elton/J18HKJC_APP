"""
因子命中率校正台 — 賽前快照 × 賽後結算。
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from factor_calibration import FactorCalibration, SIGNAL_DEFS, PLA_FINISH_MAX
from config import ModelConfig
from inference_engine import InferenceEngine

try:
    import plotly.express as px
except ImportError:
    px = None

st.title("📊 因子命中率（賽前快照 → 賽後結算）")
st.caption("用戶瀏覽榜請到「命中率榜」；本頁為管理端寫入／結算校正台。")
st.markdown(
    f"""
**正確流程**
1. **賽前**：建立預測快照（鎖住當日各因子／總分／模型勝率）  
2. **賽後**：J18 歷史爬蟲入庫名次後，執行「結算快照」  
3. 本頁用已結算快照統計各訊號 **WIN／PLA／WQ／T3／T4**，供調 `WEIGHT_*`  

**命中規則**
- **WIN**：推介頭兩位任一跑第 1  
- **PLA**：推介頭兩位任一跑入前 {PLA_FINISH_MAX}  
- **WQ**：推介頭兩位恰為冠、亞（不論順序）  
- **T3**：全部推介馬（不論先後）覆蓋冠亞季  
- **T4**：全部推介馬覆蓋冠亞季殿  

推介隻數與賽日速覽相同（場內份額 + `select_picks_by_share`）。
"""
)

cal = FactorCalibration()
engine = InferenceEngine()

# —— 操作區 ——
st.subheader("① 賽前：建立快照")
upcoming = engine.get_upcoming_races()
default_date = ""
default_course = "ST"
if not upcoming.empty:
    upcoming = upcoming.copy()
    upcoming["_d"] = upcoming["racing_date"].astype(str).str[:10]
    default_date = upcoming["_d"].max()
    default_course = str(upcoming[upcoming["_d"] == default_date].iloc[0]["course"])

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    snap_date = st.text_input("賽日 YYYY-MM-DD", value=default_date or "2026-09-06")
with c2:
    snap_course = st.selectbox(
        "場地",
        ["ST", "HV"],
        index=0 if default_course == "ST" else 1,
    )
with c3:
    st.write("")
    st.write("")
    do_snap = st.button("建立預測快照", type="primary", use_container_width=True)

if do_snap:
    with st.spinner("正在對各場跑推論並寫入快照…"):
        result = cal.snapshot_meeting(snap_date, snap_course)
    if result.get("ok"):
        st.success(
            f"已建立 `{result['batch_id']}`："
            f"{result['n_races']} 場、{result['n_rows']} 匹"
        )
    else:
        st.error(result.get("error", "失敗"))

st.subheader("② 賽後：結算快照")
st.caption(
    "只需 `runners.finish_order_num`（jjjc／J18 賽果）。"
    "**與 NLP／沿路走勢無關**——無評述也可結算。優先馬號、再馬名匹配。"
)
if st.button("結算所有待處理快照", use_container_width=False):
    with st.spinner("比對賽果中…"):
        settled = cal.settle_pending()
    st.info(settled.get("message") or (
        f"更新名次 {settled.get('updated_rows', 0)} 列；"
        f"新結算 batch：{settled.get('settled_batches') or '（無）'}"
    ))
    if settled.get("waiting_results"):
        st.warning(
            "以下 batch 尚無名次可配對（請先 RESULTS 同步）："
            + ", ".join(settled["waiting_results"])
        )

st.subheader("③ 快照清單")
batches = cal.list_batches()
if batches.empty:
    st.warning("尚無快照。請於賽前先建立。")
else:
    show_b = batches.copy()
    show_b["狀態"] = show_b["settled_at"].apply(
        lambda x: "✅ 已結算" if pd.notna(x) else "⏳ 待賽果"
    )
    st.dataframe(
        show_b[
            ["batch_id", "racing_date", "course", "n_rows", "n_filled", "狀態", "created_at"]
        ],
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("④ 命中率統計（僅已結算／已有名次）")

with st.expander("目前推論權重（參考；快照當下已鎖在 DB）", expanded=False):
    st.caption("調整權重請到各因子頁／融合預測；此處僅顯示當前 ModelConfig。")
    for label, _col, wname in SIGNAL_DEFS:
        if wname:
            st.text(f"{label}: {getattr(ModelConfig, wname)}")

only_settled = st.checkbox("只計已標記結算的 batch", value=True)
if st.button("重新整理統計", type="primary"):
    st.cache_data.clear()

@st.cache_data(ttl=60, show_spinner="統計命中率…")
def _stats(only_settled: bool):
    return FactorCalibration().evaluate_settled(only_settled=only_settled)

stats_df, meta = _stats(only_settled)

if meta.get("error"):
    st.warning(meta["error"])
    st.stop()

m1, m2, m3 = st.columns(3)
m1.metric("Batch 數", meta.get("n_batches", 0))
m2.metric("場次數", meta.get("n_races", 0))
m3.metric("平均頭數", f"{meta.get('avg_runners', 0):.1f}")
st.caption(meta.get("note", ""))

st.dataframe(stats_df, use_container_width=True, hide_index=True, height=420)

cov_b = meta.get("coverage_buckets") or []
if cov_b:
    st.subheader("覆蓋度分桶（綜合總分）")
    st.dataframe(pd.DataFrame(cov_b), use_container_width=True, hide_index=True)

if px is not None and not stats_df.empty:
    melt = stats_df.melt(
        id_vars=["訊號"],
        value_vars=["WIN%", "PLA%", "WQ%", "T3%", "T4%"],
        var_name="指標",
        value_name="比率%",
    )
    fig = px.bar(
        melt,
        x="訊號",
        y="比率%",
        color="指標",
        barmode="group",
        title="各訊號 WIN / PLA / WQ / T3 / T4（賽前快照）",
        color_discrete_sequence=["#0B6E4F", "#2F9E6F", "#C45C26", "#5B7C99", "#6B4F3A"],
    )
    if meta.get("avg_runners"):
        fig.add_hline(
            y=min(100.0, 200.0 / meta["avg_runners"]),
            line_dash="dash",
            line_color="#888",
            annotation_text="隨機 WIN 基準（約 2/n）",
        )
    fig.update_layout(height=440, xaxis_tickangle=-25)
    st.plotly_chart(fig, use_container_width=True)

st.markdown(
    """
**調權重建議**
- 看「WIN相對隨機」：明顯較高的訊號可加重 `WEIGHT_*`
- WQ／T3／T4 樣本較稀，需累積多賽日再解讀
- SG 覆蓋率低屬正常（部分場次無 Speed Guide）
"""
)
