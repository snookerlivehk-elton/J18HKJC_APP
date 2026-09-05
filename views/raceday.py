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
from form_ai_picks import build_ai_picks, compute_ai_combo
from ui_theme import inject_user_css
from auth_utils import is_admin
from factor_calibration import place_cutoff

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
  background: var(--secondary-background-color) !important;
  color: var(--text-color) !important;
  border: 1px solid rgba(128,128,128,0.35);
  border-radius: 12px;
  padding: 0.8rem 0.95rem;
  margin: 0.4rem 0 0.85rem 0;
}
.rd-meta .title {
  font-weight: 800; font-size: 1.02rem;
  color: var(--text-color) !important;
  margin-bottom: 0.4rem;
}
.rd-meta .grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 0.3rem 0.7rem; font-size: 0.8rem;
  color: var(--text-color) !important; opacity: 0.88;
}
.rd-meta .grid b { color: var(--text-color) !important; font-weight: 600; opacity: 1; }
.horse-card {
  background: var(--secondary-background-color) !important;
  color: var(--text-color) !important;
  border: 1px solid rgba(128,128,128,0.35);
  border-radius: 12px;
  padding: 0.8rem 0.9rem;
  margin-bottom: 0.65rem;
}
.horse-card.top1 { border-color: #0b6e4f; border-width: 1.5px; }
.horse-card.pick { border-color: #0b6e4f; }
.hc-top { display: flex; justify-content: space-between; gap: 0.5rem; }
.hc-rank {
  display: inline-block; font-size: 0.7rem; font-weight: 700;
  color: #0b6e4f; background: rgba(11,110,79,0.2);
  border-radius: 999px; padding: 0.1rem 0.45rem; margin-bottom: 0.2rem;
}
.hc-name { font-size: 1.08rem; font-weight: 800; line-height: 1.25; color: var(--text-color) !important; }
.hc-no { opacity: 0.7; font-weight: 600; font-size: 0.88rem; }
.hc-prob { text-align: right; flex-shrink: 0; }
.hc-prob .pct { font-size: 1.35rem; font-weight: 800; color: #2f9e6f; line-height: 1; }
.hc-prob .lbl { font-size: 0.66rem; opacity: 0.7; margin-top: 0.12rem; color: var(--text-color) !important; }
.hc-sub { margin-top: 0.45rem; font-size: 0.78rem; opacity: 0.85; line-height: 1.45; color: var(--text-color) !important; }
.hc-sub b { font-weight: 600; opacity: 1; color: var(--text-color) !important; }
.hc-metrics {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem;
  margin-top: 0.5rem; padding-top: 0.5rem;
  border-top: 1px solid rgba(128,128,128,0.3); font-size: 0.78rem;
  color: var(--text-color) !important;
}
.hc-metrics .m-lbl { opacity: 0.7; font-size: 0.68rem; }
.hc-metrics .m-val { font-weight: 700; margin-top: 0.1rem; color: var(--text-color) !important; }
.hc-metrics .ai-pos { color: #2f9e6f !important; }
.hc-metrics .ai-neg { color: #e07a45 !important; }
.rd-picks {
  margin-top: 0.75rem;
  padding-top: 0.65rem;
  border-top: 1px solid rgba(128,128,128,0.3);
}
.rd-picks .sec {
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
  opacity: 0.7; margin: 0.45rem 0 0.3rem;
}
.rd-picks .sec:first-child { margin-top: 0; }
.rd-pick-row {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 0.4rem; padding: 0.28rem 0; font-size: 0.86rem;
  border-bottom: 1px dashed rgba(128,128,128,0.2);
}
.rd-pick-row:last-child { border-bottom: none; }
.rd-pick-row .left { min-width: 0; flex: 1; line-height: 1.3; }
.rd-pick-row .tag {
  display: inline-block; font-size: 0.65rem; font-weight: 700;
  color: #2f9e6f; background: rgba(47,158,111,0.18);
  border-radius: 999px; padding: 0.05rem 0.4rem; margin-right: 0.3rem;
}
.rd-pick-row .nm { font-weight: 700; }
.rd-pick-row .right {
  flex-shrink: 0; text-align: right; font-weight: 700; font-size: 0.82rem;
}
.rd-pick-row .ai {
  display: block; font-size: 0.68rem; font-weight: 600; opacity: 0.85; margin-top: 0.05rem;
}
.rd-pick-row .ai.pos { color: #2f9e6f; }
.rd-pick-row .ai.neg { color: #e07a45; }
.rd-picks .note {
  font-size: 0.68rem; opacity: 0.65; margin-top: 0.45rem; line-height: 1.35;
}
.rd-picks-dual {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0.55rem;
  margin-top: 0.35rem;
}
.rd-picks-col {
  border: 1px solid rgba(128,128,128,0.28);
  border-radius: 10px;
  padding: 0.45rem 0.5rem 0.35rem;
  background: rgba(128,128,128,0.06);
}
.rd-picks-col .col-title {
  font-size: 0.72rem; font-weight: 800; letter-spacing: 0.03em;
  margin-bottom: 0.25rem; opacity: 0.85;
}
.rd-picks-col.ai-col .tag {
  color: #c45c26; background: rgba(196,92,38,0.18);
}
.rd-pick-empty { font-size: 0.78rem; opacity: 0.55; padding: 0.25rem 0; }
@media (max-width: 420px) {
  .rd-picks-dual { grid-template-columns: 1fr; }
}
/* 場次數字 pill：壓低高度 */
div[data-testid="stPills"] button {
  min-width: 2.4rem !important;
  min-height: 2.4rem !important;
  border-radius: 999px !important;
  padding: 0 0.55rem !important;
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

nums = day["race_num"].astype(int).tolist()
num_to_rid = {
    int(r["race_num"]): str(r["race_id"])
    for _, r in day.iterrows()
}
# 目前場次數字
cur_num = int(day[day["race_id"].astype(str) == st.session_state.rd_race_id].iloc[0]["race_num"])

# 緊湊：圓形數字 pill（手機不會再直向堆滿屏）
picked = st.pills(
    "場次",
    options=nums,
    selection_mode="single",
    default=cur_num,
    format_func=lambda n: str(n),
    label_visibility="collapsed",
    key="rd_race_pills",
)
if picked is None:
    picked = cur_num
if int(picked) != cur_num:
    st.session_state.rd_race_id = num_to_rid[int(picked)]
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

if pred_df.empty:
    st.warning("此場暫無預測結果。")
    st.stop()

if "模型勝率" in pred_df.columns:
    pred_df = pred_df.sort_values("模型勝率", ascending=False).reset_index(drop=True)
else:
    pred_df = pred_df.sort_values("總預測分", ascending=False).reset_index(drop=True)

n_runners = len(pred_df)
place_n = place_cutoff(n_runners)
# 爭勝：勝率最高 1～2 匹（第二名勝率 ≥ 頭馬 70% 才並列顯示）
win_n = 1
if n_runners >= 2 and "模型勝率" in pred_df.columns:
    p0 = float(pred_df.iloc[0]["模型勝率"] or 0)
    p1 = float(pred_df.iloc[1]["模型勝率"] or 0)
    if p0 > 0 and p1 >= p0 * 0.70:
        win_n = 2
elif n_runners >= 2:
    win_n = 2

# AI 獨立軌道推介（評價×信心；不混入模型）
ai_rows = []
for _, r in pred_df.iterrows():
    hno = int(r["馬號"])
    ai = ai_map.get(hno)
    sc = float(ai["ai_score"]) if ai is not None and pd.notna(ai.get("ai_score")) else None
    cf = float(ai["confidence"]) if ai is not None and pd.notna(ai.get("confidence")) else None
    ai_rows.append(
        {
            "horse_no": hno,
            "horse_name": r["馬名"],
            "ai_score": sc,
            "confidence": cf,
            "ai_combo": compute_ai_combo(sc, cf),
            "pred_rank": int(r["預測排名"]) if pd.notna(r.get("預測排名")) else None,
            "model_win_prob": float(r["模型勝率"]) if pd.notna(r.get("模型勝率")) else None,
        }
    )
ai_picks = build_ai_picks(ai_rows, n_runners=n_runners)
ai_pick_hnos = {
    int(x["horse_no"])
    for x in (ai_picks.get("win") or []) + (ai_picks.get("place") or [])
    if x.get("horse_no") is not None
}


def _model_pick_rows(df_slice, tag_prefix: str) -> str:
    parts = []
    for i, (_, r) in enumerate(df_slice.iterrows(), start=1):
        hno = int(r["馬號"])
        name = r["馬名"]
        prob = float(r["模型勝率%"]) if pd.notna(r.get("模型勝率%")) else 0.0
        parts.append(
            f'<div class="rd-pick-row">'
            f'<div class="left"><span class="tag">{tag_prefix}{i}</span>'
            f'<span class="nm">{hno} {name}</span></div>'
            f'<div class="right">{prob:.1f}%</div>'
            f"</div>"
        )
    return "".join(parts) if parts else '<div class="rd-pick-empty">—</div>'


def _fmt_ai_display(combo) -> str:
    """推介列簡潔顯示：僅指數百分比（如 72%），不秀算式與 combo 括號。"""
    if combo is None:
        return "—"
    try:
        c = float(combo)
    except (TypeError, ValueError):
        return "—"
    return f"{c * 100:.0f}%"


def _ai_pick_rows(picks: list, tag_prefix: str) -> str:
    if not picks:
        return '<div class="rd-pick-empty">尚無 AI 評價</div>'
    parts = []
    for i, r in enumerate(picks, start=1):
        hno = r.get("horse_no")
        name = r.get("horse_name") or ""
        right = _fmt_ai_display(r.get("ai_combo"))
        parts.append(
            f'<div class="rd-pick-row">'
            f'<div class="left"><span class="tag">{tag_prefix}{i}</span>'
            f'<span class="nm">{hno} {name}</span></div>'
            f'<div class="right">{right}</div>'
            f"</div>"
        )
    return "".join(parts)


win_html = _model_pick_rows(pred_df.head(win_n), "勝")
place_html = _model_pick_rows(pred_df.head(place_n), "圍")
ai_win_html = _ai_pick_rows(ai_picks.get("win") or [], "勝")
ai_place_html = _ai_pick_rows(ai_picks.get("place") or [], "圍")
ai_place_n = ai_picks.get("place_cutoff") or place_n

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
  <div class="rd-picks">
    <div class="rd-picks-dual">
      <div class="rd-picks-col">
        <div class="col-title">模型 · 勝率</div>
        <div class="sec">爭勝</div>
        {win_html}
        <div class="sec">入圍 · 前{place_n}</div>
        {place_html}
      </div>
      <div class="rd-picks-col ai-col">
        <div class="col-title">AI 馬評 · 推介指數</div>
        <div class="sec">爭勝</div>
        {ai_win_html}
        <div class="sec">入圍 · 前{ai_place_n}</div>
        {ai_place_html}
      </div>
    </div>
    <div class="note">雙軌獨立：左＝量化勝率%；右＝AI 推介指數%。明細與算式見下方馬匹詳情。本場 {n_runners} 匹。</div>
  </div>
</div>
"""
st.markdown(meta_html, unsafe_allow_html=True)

st.caption(f"全部 {n_runners} 匹 · 按模型勝率排序")

for _, row in pred_df.iterrows():
    rank = int(row["預測排名"]) if pd.notna(row.get("預測排名")) else 0
    hno = int(row["馬號"])
    top_cls = "top1" if rank == 1 else ("pick" if hno in ai_pick_hnos else "")
    name = row["馬名"]
    prob = float(row["模型勝率%"]) if pd.notna(row.get("模型勝率%")) else 0.0
    total = float(row["總預測分"]) if pd.notna(row.get("總預測分")) else 0.0
    jockey = row.get("騎師") or "-"
    trainer = row.get("練馬師") or "-"
    draw = row.get("檔位")
    hw = row.get("負磅")
    bw = row.get("體重")

    ai = ai_map.get(hno)
    if ai is not None and pd.notna(ai.get("ai_score")):
        ai_score = float(ai["ai_score"])
        ai_conf = float(ai["confidence"]) if pd.notna(ai.get("confidence")) else 0.0
        ai_combo = ai_score * ai_conf
        ai_cls = "ai-pos" if ai_combo >= 0 else "ai-neg"
        ai_badge = " · AI推介" if hno in ai_pick_hnos else ""
        ai_block = (
            f'<div><div class="m-lbl">AI 推介指數{ai_badge}</div>'
            f'<div class="m-val {ai_cls}">{_fmt_ai_display(ai_combo)}</div></div>'
        )
    else:
        ai_block = (
            '<div><div class="m-lbl">AI 馬評</div>'
            '<div class="m-val" style="opacity:0.5">尚無</div></div>'
        )

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
  <div class="hc-metrics">
    <div>
      <div class="m-lbl">統計總分</div>
      <div class="m-val">{total:.2f}</div>
    </div>
    {ai_block}
  </div>
</div>
"""
    st.markdown(card, unsafe_allow_html=True)

    with st.expander(f"詳情 · {hno} {name}", expanded=(rank == 1)):
        chips = []
        for label, val in factor_rows_for_horse(row):
            chips.append(f'<span class="factor-chip">{label} {val:+.2f}</span>')
        st.markdown("".join(chips), unsafe_allow_html=True)

        if ai is not None:
            combo = float(ai["ai_score"]) * float(ai["confidence"])
            st.markdown(
                f"**AI 評價**（指數 **{_fmt_ai_display(combo)}**；"
                f"{float(ai['ai_score']):+.2f} × 信心 {float(ai['confidence']):.0%}＝{combo:+.2f}）  \n"
                f"{ai.get('summary') or ''}"
            )
        else:
            st.caption("尚無 AI 評價")

        if HAS_PLOTLY:
            fig = build_radar_figure(
                pred_df, [hno], height=260, title="", mobile=True,
            )
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.caption("雙軌：模型勝率%｜AI 推介指數%。算式在馬匹詳情；AI 不混入總分。")
