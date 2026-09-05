"""
賽日速覽（手機優先）— 用戶主畫面：場次／勝率卡片／因子與雷達。
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from inference_engine import InferenceEngine
from bucket_utils import format_class_display
from radar_charts import build_radar_figure, factor_rows_for_horse
from form_ai_analyst import FormAIAnalyst
from ui_theme import inject_user_css
from auth_utils import is_admin

try:
    import plotly.graph_objects as go  # noqa: F401
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

inject_user_css()
st.markdown(
    """
<style>
.rd-hero {
  background: linear-gradient(160deg, #0b6e4f 0%, #16382e 100%);
  color: #f4faf7;
  border-radius: 14px;
  padding: 1rem 1.05rem;
  margin-bottom: 0.75rem;
}
.rd-hero h1 {
  font-size: 1.28rem; font-weight: 800; margin: 0 0 0.2rem 0;
  letter-spacing: 0.02em;
}
.rd-hero p { margin: 0; opacity: 0.88; font-size: 0.84rem; }
.rd-meta {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.8rem 0.95rem;
  margin: 0.4rem 0 0.85rem 0;
}
.rd-meta .title { font-weight: 800; font-size: 1.02rem; color: var(--ink); margin-bottom: 0.4rem; }
.rd-meta .grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 0.3rem 0.7rem; font-size: 0.8rem; color: var(--muted);
}
.rd-meta .grid b { color: var(--ink); font-weight: 600; }
.horse-card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.8rem 0.9rem;
  margin-bottom: 0.65rem;
}
.horse-card.top1 { border-color: #0b6e4f; border-width: 1.5px; }
.hc-top { display: flex; justify-content: space-between; gap: 0.5rem; }
.hc-rank {
  display: inline-block; font-size: 0.7rem; font-weight: 700;
  color: var(--accent); background: var(--accent-soft);
  border-radius: 999px; padding: 0.1rem 0.45rem; margin-bottom: 0.2rem;
}
.hc-name { font-size: 1.08rem; font-weight: 800; color: var(--ink); line-height: 1.25; }
.hc-no { color: var(--muted); font-weight: 600; font-size: 0.88rem; }
.hc-prob { text-align: right; flex-shrink: 0; }
.hc-prob .pct { font-size: 1.4rem; font-weight: 800; color: var(--accent); line-height: 1; }
.hc-prob .lbl { font-size: 0.66rem; color: var(--muted); margin-top: 0.12rem; }
.hc-sub { margin-top: 0.45rem; font-size: 0.78rem; color: var(--muted); line-height: 1.45; }
.hc-sub b { color: var(--ink); font-weight: 600; }
.hc-score-row {
  display: flex; justify-content: space-between;
  margin-top: 0.45rem; padding-top: 0.45rem;
  border-top: 1px solid var(--line); font-size: 0.8rem;
}
.factor-chip {
  display: inline-block; background: var(--accent-soft); color: var(--ink);
  border-radius: 7px; padding: 0.18rem 0.4rem; margin: 0.12rem 0.15rem 0.12rem 0;
  font-size: 0.7rem; font-weight: 600;
}
div[data-testid="stHorizontalBlock"] button {
  border-radius: 999px !important; min-height: 2.35rem !important; font-weight: 700 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="rd-hero">
  <h1>賽日速覽</h1>
  <p>選場次 · 看勝率 · 展開因子</p>
</div>
""",
    unsafe_allow_html=True,
)

engine = InferenceEngine()
races_df = engine.get_upcoming_races()

if races_df.empty:
    st.warning(
        "尚無賽日排位。"
        + ("請到資料控制中心抓取。" if is_admin() else "請稍後再試或聯絡管理員。")
    )
    st.stop()

scores_ok = not engine.calc.load_factor_scores(
    factor_types=["JOCKEY", "TRAINER", "SYNERGY", "DRAW", "HORSE", "PACE", "SPEED"]
).empty
if not scores_ok:
    st.error(
        "尚無因子分數。"
        + ("請回系統主頁重算。" if is_admin() else "請聯絡管理員。")
    )
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


races_df = races_df.copy()
races_df["_date"] = races_df["racing_date"].astype(str)
dates = sorted(races_df["_date"].unique().tolist())
date_sel = st.selectbox("賽日", dates, index=len(dates) - 1, label_visibility="collapsed")
day = races_df[races_df["_date"] == date_sel].sort_values("race_num")
course = str(day.iloc[0]["course"])
st.caption(f"{date_sel}　{course}　共 {len(day)} 場")

if "rd_race_id" not in st.session_state:
    st.session_state.rd_race_id = str(day.iloc[0]["race_id"])

day_ids = set(day["race_id"].astype(str))
if st.session_state.rd_race_id not in day_ids:
    st.session_state.rd_race_id = str(day.iloc[0]["race_id"])

st.markdown("**場次**")
nums = day["race_num"].astype(int).tolist()
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

ai_map = {}
try:
    ai_df = FormAIAnalyst().load_ai_for_race(race_id)
    if not ai_df.empty:
        for _, a in ai_df.iterrows():
            ai_map[int(a["horse_no"])] = a
except Exception:
    pass

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

if "模型勝率" in pred_df.columns:
    pred_df = pred_df.sort_values("模型勝率", ascending=False).reset_index(drop=True)
else:
    pred_df = pred_df.sort_values("總預測分", ascending=False).reset_index(drop=True)

st.caption(f"{len(pred_df)} 匹 · 按勝率排序")

for _, row in pred_df.iterrows():
    rank = int(row["預測排名"]) if pd.notna(row.get("預測排名")) else 0
    top_cls = "top1" if rank == 1 else ""
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

    with st.expander(f"詳情 · {hno} {name}", expanded=(rank == 1)):
        chips = []
        for label, val in factor_rows_for_horse(row):
            chips.append(f'<span class="factor-chip">{label} {val:+.2f}</span>')
        st.markdown("".join(chips), unsafe_allow_html=True)

        ai = ai_map.get(hno)
        if ai is not None:
            st.markdown(
                f"**AI 評價**（{float(ai['ai_score']):+.2f}｜信心 {float(ai['confidence']):.0%}）  \n"
                f"{ai['summary']}"
            )
        else:
            st.caption("尚無 AI 評價")

        if HAS_PLOTLY:
            fig = build_radar_figure(
                pred_df, [hno], height=260, title="", mobile=True,
            )
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.caption("雷達為同場相對形狀，非勝率。模型勝率僅供參考。")
