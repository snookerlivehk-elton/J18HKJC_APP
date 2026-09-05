"""
賽日速覽（手機優先）— 給一般用戶看的場次／馬匹卡片＋雷達。
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from inference_engine import InferenceEngine
from bucket_utils import format_class_display
from radar_charts import RADAR_AXES, build_radar_figure, factor_rows_for_horse

try:
    import plotly.graph_objects as go  # noqa: F401
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

st.set_page_config(
    page_title="賽日速覽",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# —— 手機優先外觀 ——
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');

html, body, [class*="css"] {
  font-family: "Noto Sans TC", "Segoe UI", sans-serif;
}
.block-container {
  padding-top: 1rem !important;
  padding-bottom: 4rem !important;
  max-width: 480px !important;
}
[data-testid="stSidebar"] {
  min-width: 0;
}
/* 預設收合側欄；需要內部工具時可手動打開 */

:root {
  --ink: #14241c;
  --muted: #5a6b62;
  --line: #d5e0d9;
  --card: #f7faf8;
  --accent: #0b6e4f;
  --accent-soft: #e3f2eb;
  --warn: #c45c26;
  --gold: #b8860b;
}

.rd-hero {
  background: linear-gradient(145deg, #0b6e4f 0%, #1a3d32 55%, #243d36 100%);
  color: #f4faf7;
  border-radius: 16px;
  padding: 1rem 1.1rem 1.15rem;
  margin-bottom: 0.85rem;
}
.rd-hero h1 {
  font-size: 1.35rem;
  font-weight: 800;
  margin: 0 0 0.25rem 0;
  letter-spacing: 0.02em;
}
.rd-hero p { margin: 0; opacity: 0.88; font-size: 0.88rem; }

.rd-meta {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 0.85rem 1rem;
  margin: 0.5rem 0 1rem 0;
}
.rd-meta .title {
  font-weight: 800;
  font-size: 1.05rem;
  color: var(--ink);
  margin-bottom: 0.45rem;
}
.rd-meta .grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.35rem 0.75rem;
  font-size: 0.82rem;
  color: var(--muted);
}
.rd-meta .grid b { color: var(--ink); font-weight: 600; }

.horse-card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 0.85rem 0.95rem;
  margin-bottom: 0.75rem;
  box-shadow: 0 1px 0 rgba(20,36,28,0.04);
}
.horse-card.top1 { border-color: #c9a227; background: linear-gradient(180deg,#fffdf5,#fff); }
.horse-card.top2 { border-color: #b0b7be; }
.horse-card.top3 { border-color: #c4a484; }

.hc-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}
.hc-left { min-width: 0; flex: 1; }
.hc-rank {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--accent);
  background: var(--accent-soft);
  border-radius: 999px;
  padding: 0.12rem 0.5rem;
  margin-bottom: 0.25rem;
}
.hc-name {
  font-size: 1.12rem;
  font-weight: 800;
  color: var(--ink);
  line-height: 1.25;
  word-break: break-word;
}
.hc-no {
  color: var(--muted);
  font-weight: 600;
  font-size: 0.9rem;
}
.hc-prob {
  text-align: right;
  flex-shrink: 0;
}
.hc-prob .pct {
  font-size: 1.45rem;
  font-weight: 800;
  color: var(--accent);
  line-height: 1;
}
.hc-prob .lbl {
  font-size: 0.68rem;
  color: var(--muted);
  margin-top: 0.15rem;
}
.hc-sub {
  margin-top: 0.55rem;
  font-size: 0.8rem;
  color: var(--muted);
  line-height: 1.45;
}
.hc-sub b { color: var(--ink); font-weight: 600; }
.hc-score-row {
  display: flex;
  justify-content: space-between;
  margin-top: 0.55rem;
  padding-top: 0.5rem;
  border-top: 1px dashed var(--line);
  font-size: 0.82rem;
}
.factor-chip {
  display: inline-block;
  background: var(--accent-soft);
  color: var(--ink);
  border-radius: 8px;
  padding: 0.2rem 0.45rem;
  margin: 0.15rem 0.2rem 0.15rem 0;
  font-size: 0.72rem;
  font-weight: 600;
}
div[data-testid="stHorizontalBlock"] button {
  border-radius: 999px !important;
  min-height: 2.4rem !important;
  font-weight: 700 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="rd-hero">
  <h1>賽日速覽</h1>
  <p>選場次 → 馬匹卡片（按模型勝率）→ 展開看因子與雷達</p>
</div>
""",
    unsafe_allow_html=True,
)

engine = InferenceEngine()
races_df = engine.get_upcoming_races()

if races_df.empty:
    st.warning("尚無賽日排位。請先在資料控制中心抓取排位表。")
    st.stop()

scores_ok = not engine.calc.load_factor_scores(
    factor_types=["JOCKEY", "TRAINER", "SYNERGY", "DRAW", "HORSE", "PACE", "SPEED"]
).empty
if not scores_ok:
    st.error("尚無因子分數。請回主頁執行「重算並寫入因子分數」。")
    st.stop()


@st.cache_data(ttl=90, show_spinner="計算本場…")
def _predict(race_id: str):
    eng = InferenceEngine()
    df, info, meta = eng.predict_race(race_id)
    info_dict = info.to_dict() if hasattr(info, "to_dict") else (dict(info) if info is not None else {})
    safe = {}
    for k, v in info_dict.items():
        if hasattr(v, "item"):
            try:
                safe[k] = v.item()
                continue
            except Exception:
                pass
        safe[k] = str(v) if hasattr(v, "isoformat") else v
    return {
        "columns": list(df.columns) if df is not None and not df.empty else [],
        "df": df.to_dict(orient="list") if df is not None and not df.empty else {},
        "info": safe,
        "meta": meta,
    }


def load_pred(race_id: str):
    p = _predict(race_id)
    if not p["columns"]:
        return pd.DataFrame(), p["info"], p["meta"]
    return pd.DataFrame(p["df"], columns=p["columns"]), p["info"], p["meta"]


# 依日期分組（通常一日一場地）
races_df = races_df.copy()
races_df["_date"] = races_df["racing_date"].astype(str)
dates = sorted(races_df["_date"].unique().tolist())
date_sel = st.selectbox("賽日", dates, index=len(dates) - 1, label_visibility="collapsed")
day = races_df[races_df["_date"] == date_sel].sort_values("race_num")
course = str(day.iloc[0]["course"])
st.caption(f"{date_sel}　{course}　共 {len(day)} 場")

# 場次選擇（手機大按鈕）
if "rd_race_id" not in st.session_state:
    st.session_state.rd_race_id = str(day.iloc[0]["race_id"])

# 若換日導致舊 race_id 不在列表，重設
day_ids = set(day["race_id"].astype(str))
if st.session_state.rd_race_id not in day_ids:
    st.session_state.rd_race_id = str(day.iloc[0]["race_id"])

st.markdown("**選擇場次**")
nums = day["race_num"].astype(int).tolist()
# 每列 5 個按鈕
for start in range(0, len(nums), 5):
    chunk = nums[start : start + 5]
    cols = st.columns(len(chunk))
    for i, num in enumerate(chunk):
        row = day[day["race_num"] == num].iloc[0]
        rid = str(row["race_id"])
        active = st.session_state.rd_race_id == rid
        if cols[i].button(
            f"第{num}場",
            key=f"race_btn_{rid}",
            type="primary" if active else "secondary",
            use_container_width=True,
        ):
            st.session_state.rd_race_id = rid
            st.rerun()

race_id = st.session_state.rd_race_id
race_row = day[day["race_id"].astype(str) == race_id].iloc[0]
pred_df, _info, meta = load_pred(race_id)

cls_disp = format_class_display(race_row.get("class"))
race_name = race_row.get("race_name") or ""
meta_html = f"""
<div class="rd-meta">
  <div class="title">第 {int(race_row['race_num'])} 場{' · ' + race_name if race_name else ''}</div>
  <div class="grid">
    <div>日期 <b>{race_row['racing_date']}</b></div>
    <div>場地 <b>{race_row['course']}</b></div>
    <div>賽道 <b>{race_row.get('track') or '-'}</b></div>
    <div>距離 <b>{race_row.get('distance_m') or '-'} 米</b></div>
    <div>班次 <b>{cls_disp}</b></div>
    <div>匹配 <b>{meta.get('match_rate', 0):.0%}</b></div>
  </div>
</div>
"""
st.markdown(meta_html, unsafe_allow_html=True)

if pred_df.empty:
    st.warning("此場暫無預測結果。")
    st.stop()

# 依勝率排序（引擎已按總分排；再保險一次）
if "模型勝率" in pred_df.columns:
    pred_df = pred_df.sort_values("模型勝率", ascending=False).reset_index(drop=True)
else:
    pred_df = pred_df.sort_values("總預測分", ascending=False).reset_index(drop=True)

st.caption(f"共 {len(pred_df)} 匹　按模型勝率排序　勝率加總 {meta.get('win_prob_sum', 0):.2f}")

for _, row in pred_df.iterrows():
    rank = int(row["預測排名"]) if pd.notna(row.get("預測排名")) else 0
    top_cls = {1: "top1", 2: "top2", 3: "top3"}.get(rank, "")
    hno = int(row["馬號"])
    name = row["馬名"]
    prob = float(row["模型勝率%"]) if pd.notna(row.get("模型勝率%")) else 0.0
    total = float(row["總預測分"]) if pd.notna(row.get("總預測分")) else 0.0
    jockey = row.get("騎師") or "-"
    trainer = row.get("練馬師") or "-"
    draw = row.get("檔位")
    hw = row.get("負磅")
    bw = row.get("體重")

    def _fmt(v, suffix=""):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "-"
        try:
            return f"{float(v):.0f}{suffix}" if float(v) == int(float(v)) else f"{float(v):.1f}{suffix}"
        except (TypeError, ValueError):
            return str(v)

    card = f"""
<div class="horse-card {top_cls}">
  <div class="hc-top">
    <div class="hc-left">
      <span class="hc-rank">#{rank}</span>
      <div class="hc-name"><span class="hc-no">{hno}</span>　{name}</div>
    </div>
    <div class="hc-prob">
      <div class="pct">{prob:.1f}%</div>
      <div class="lbl">模型勝率</div>
    </div>
  </div>
  <div class="hc-sub">
    騎師 <b>{jockey}</b>　·　練馬師 <b>{trainer}</b><br/>
    檔位 <b>{_fmt(draw)}</b>　·　負磅 <b>{_fmt(hw)}</b>　·　馬重 <b>{_fmt(bw)}</b>
  </div>
  <div class="hc-score-row">
    <span>統計總分</span>
    <b>{total:.2f}</b>
  </div>
</div>
"""
    st.markdown(card, unsafe_allow_html=True)

    with st.expander(f"因子詳情 · {hno} {name}", expanded=(rank == 1)):
        chips = []
        for label, val in factor_rows_for_horse(row):
            chips.append(f'<span class="factor-chip">{label} {val:+.2f}</span>')
        st.markdown("".join(chips), unsafe_allow_html=True)

        if HAS_PLOTLY:
            fig = build_radar_figure(
                pred_df,
                [hno],
                height=280,
                title="",
                mobile=True,
            )
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("未安裝 plotly，無法顯示雷達圖。")

st.markdown("---")
st.caption("雷達為同場相對形狀（非勝率）。模型勝率供參考，並非派彩保證。")
