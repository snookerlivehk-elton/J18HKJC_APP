"""
因子命中率校正台 — 各訊號獨立獨贏／入圍統計，供調 WEIGHT_* 參考。
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from factor_calibration import FactorCalibration, SIGNAL_DEFS
from config import ModelConfig

try:
    import plotly.express as px
except ImportError:
    px = None

st.set_page_config(page_title="因子命中率", layout="wide")

st.title("📊 因子／總分／勝率 — 獨立命中統計")
st.markdown(
    """
用**現行** `factor_scores` 對近期完賽場次做回溯：每個訊號單獨取「場內最高分」一匹，  
統計其**獨贏率**與**入圍率**（≤6 匹前 2；≥7 匹前 3）。  

適合比較「哪個因子較準」以調權重；**不是**嚴格無洩漏回測（現行分數含賽後資訊）。  
Speed Guide 無歷史存檔，本頁不含。
"""
)

with st.sidebar:
    st.subheader("樣本範圍")
    lookback = st.slider("回溯天數", 30, 365, 90, 15)
    max_races = st.slider("最多場次", 50, 800, 300, 50)
    min_hits = st.slider("場均最少因子命中數（過濾）", 0, 5, 2, 1)
    run = st.button("重新計算", type="primary", use_container_width=True)

    st.divider()
    st.caption("目前推論權重（只讀參考）")
    for label, _col, wname in SIGNAL_DEFS:
        if wname:
            st.text(f"{label}: {getattr(ModelConfig, wname)}")


@st.cache_data(ttl=300, show_spinner="計算各訊號命中率…")
def _run(lookback_days: int, max_races: int, min_factor_hits: int):
    cal = FactorCalibration()
    return cal.evaluate(
        lookback_days=lookback_days,
        max_races=max_races,
        min_factor_hits=min_factor_hits,
    )


if run:
    _run.clear()

stats_df, meta = _run(lookback, max_races, min_hits)

if meta.get("error"):
    st.error(meta["error"])
    st.stop()

if stats_df.empty:
    st.warning("無統計結果。請確認有歷史賽果與 factor_scores。")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("有效場次", meta.get("n_races_after_filter", 0))
c2.metric("平均頭數", f"{meta.get('avg_runners', 0):.1f}")
c3.metric("隨機獨贏基準", f"{100.0 / meta['avg_runners']:.1f}%" if meta.get("avg_runners") else "-")
c4.metric("回溯天數", meta.get("lookback_days"))

st.caption(meta.get("note", ""))

st.subheader("命中率總表（按獨贏率排序）")
st.dataframe(stats_df, use_container_width=True, hide_index=True, height=420)

if px is not None:
    melt = stats_df.melt(
        id_vars=["訊號"],
        value_vars=["獨贏率%", "入圍率%"],
        var_name="指標",
        value_name="比率%",
    )
    fig = px.bar(
        melt,
        x="訊號",
        y="比率%",
        color="指標",
        barmode="group",
        title="各訊號獨贏率 vs 入圍率",
        color_discrete_sequence=["#0B6E4F", "#C45C26"],
    )
    fig.add_hline(
        y=100.0 / meta["avg_runners"] if meta.get("avg_runners") else 0,
        line_dash="dash",
        line_color="#888",
        annotation_text="隨機獨贏基準",
    )
    fig.update_layout(height=420, xaxis_tickangle=-25)
    st.plotly_chart(fig, use_container_width=True)

    if "獨贏相對隨機" in stats_df.columns:
        fig2 = px.bar(
            stats_df,
            x="訊號",
            y="獨贏相對隨機",
            title="獨贏率 ÷ 隨機基準（>1 表示優於亂猜）",
            color="獨贏相對隨機",
            color_continuous_scale="Tealgrn",
        )
        fig2.add_hline(y=1.0, line_dash="dash", line_color="#888")
        fig2.update_layout(height=380, xaxis_tickangle=-25)
        st.plotly_chart(fig2, use_container_width=True)

st.markdown(
    """
**怎麼用來調權重**
- **獨贏相對隨機** 明顯較高的訊號 → 可考慮提高對應 `WEIGHT_*`
- 覆蓋率低（常全場 0 分）→ 先修匹配／重算，再談權重
- 綜合總分／模型勝率應優於多數單一因子；若不然，權重組合可能失衡
"""
)
