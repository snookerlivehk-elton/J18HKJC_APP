"""功能选单最后一项：指数评选。"""
from __future__ import annotations

import streamlit as st

from index_selection import STRATEGY_SPECS, hit_rate
from index_selection_feed import load_board, refresh_live
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header("指数评选", "每场 6 个号码，开跑前随赔率跳动；派彩后标冠亚季")
st.caption(
    "本赛日入围率只算眼前这一天已派彩的场次。"
    "累积入围率把以往每个赛日的已派彩场次加在一起。"
    "两者都是这 6 个号码跑进名次 1、2、3 的比例。内容只供资料对照，不构成投注建议。"
)

SELL_LABEL = {
    "START_SELL": "受注中",
    "STOP_SELL": "已截止",
    "PAYOUT": "已派彩",
    "REFUND": "退款",
}


def _pct(rate) -> str:
    if rate is None:
        return "—"
    return f"{rate * 100:.1f}%"


def _numbers(picks, marks) -> str:
    bits = []
    for no, mark in zip(picks, marks):
        if mark in (1, 2, 3):
            bits.append(
                f'<span class="idx-chip is-{mark}">{no}<sup>{mark}</sup></span>'
            )
        else:
            bits.append(f'<span class="idx-chip">{no}</span>')
    return " ".join(bits) if bits else '<span class="idx-empty">暂无</span>'


st.markdown(
    """
<style>
.idx-chip { display:inline-block; min-width:1.8rem; margin:0.15rem 0.2rem;
  padding:0.15rem 0.4rem; border-radius:999px; background:#1f2937; color:#f8fafc;
  font-weight:700; text-align:center; }
.idx-chip sup { margin-left:0.1rem; font-size:0.7em; }
.idx-chip.is-1 { background:#b45309; }
.idx-chip.is-2 { background:#475569; }
.idx-chip.is-3 { background:#9a3412; }
.idx-empty { color:#94a3b8; }
.idx-rate { font-variant-numeric: tabular-nums; font-weight:700; white-space:nowrap; }
.idx-sum { display:flex; align-items:baseline; gap:0.75rem; padding:0.15rem 0;
  border-bottom:1px solid rgba(148,163,184,0.25); }
.idx-sum-name { flex:1 1 auto; min-width:0; }
.idx-sum-name b { margin-right:0.45rem; }
.idx-sum-note { color:#64748b; font-size:0.85rem; }
.idx-sum-meta { color:#64748b; font-size:0.8rem; font-weight:500; margin-left:0.45rem; }
</style>
""",
    unsafe_allow_html=True,
)


@st.fragment(run_every=30)
def _board() -> None:
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("立即刷新", type="primary"):
            with st.spinner("正在向马会对齐各池…"):
                summary = refresh_live(force=True)
            st.session_state["index_sel_summary"] = summary
    summary = st.session_state.get("index_sel_summary")
    if summary is None:
        with st.spinner("正在向马会对齐各池…"):
            summary = refresh_live()
        st.session_state["index_sel_summary"] = summary
    with col2:
        if summary.get("meeting_date"):
            st.caption(
                f"会议 {summary.get('meeting_date')} {summary.get('venue') or ''} · "
                f"本轮新写入 {summary.get('fetched') or 0} 场"
            )
        else:
            st.caption("马会这刻没有返回受注会议。")

    board = load_board()
    day_rates = board.get("day_rates") or {}
    cumulative_rates = board.get("cumulative_rates") or {}
    if not board.get("races"):
        st.info("还没有快照。受注开始后，这一页会每 30 秒重排号码。")
        return

    st.caption("入围写成「本赛日（累积）」。括号里是以往赛日加在一起的入围率。")
    rows = []
    for strategy_id, label, note in STRATEGY_SPECS:
        day = day_rates.get(strategy_id) or {}
        total = cumulative_rates.get(strategy_id) or {}
        day_races = int(day.get("races") or 0)
        total_races = int(total.get("races") or 0)
        rows.append(
            "<div class='idx-sum'>"
            f"<div class='idx-sum-name'><b>{label}</b>"
            f"<span class='idx-sum-note'>{note}</span></div>"
            f"<div class='idx-rate'>{_pct(day.get('rate'))}"
            f"（{_pct(total.get('rate'))}）"
            f"<span class='idx-sum-meta'>本日 {day_races} 场 · 累计 {total_races} 场</span></div>"
            "</div>"
        )
    st.markdown("".join(rows), unsafe_allow_html=True)

    st.divider()
    for race in board["races"]:
        status = SELL_LABEL.get(str(race.get("sell_status") or ""), str(race.get("sell_status") or "—"))
        title = f"第 {race.get('race_no') or '?'} 场 · {status}"
        with st.expander(title, expanded=True):
            for item in race["strategies"]:
                day = day_rates.get(item["id"]) or {}
                total = cumulative_rates.get(item["id"]) or {}
                placed = item.get("placed")
                tail = f"本场 {placed}/{len(item['picks'])}" if placed is not None else "本场未派彩"
                st.markdown(
                    f"**{item['label']}** · {_pct(day.get('rate'))}"
                    f"（{_pct(total.get('rate'))}） · {tail}",
                )
                st.markdown(_numbers(item["picks"], item["marks"]), unsafe_allow_html=True)


_board()
