"""功能选单最后一项：指数评选。"""
from __future__ import annotations

import streamlit as st

from index_selection import STRATEGY_SPECS, hit_rate
from index_selection_feed import load_board, refresh_live
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header("指数评选", "每场 6 个号码，开跑前随赔率跳动；派彩后标冠亚季")
st.caption(
    "入围率是已派彩场次里，这 6 个号码跑进名次 1、2、3 的比例。"
    "样本变多之后再决定留哪一套。内容只供资料对照，不构成投注建议。"
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
.idx-rate { font-variant-numeric: tabular-nums; font-weight:700; }
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
    rates = board.get("rates") or {}
    if not board.get("races"):
        st.info("还没有快照。受注开始后，这一页会每 30 秒重排号码。")
        return

    head1, head2, head3 = st.columns([2, 1, 3])
    head1.markdown("**策略**")
    head2.markdown("**入围率**")
    head3.markdown("**已派彩样本**")
    for strategy_id, label, note in STRATEGY_SPECS:
        stat = rates.get(strategy_id) or {}
        c1, c2, c3 = st.columns([2, 1, 3])
        c1.markdown(f"**{label}**")
        c1.caption(note)
        c2.markdown(f'<span class="idx-rate">{_pct(stat.get("rate"))}</span>', unsafe_allow_html=True)
        races_n = int(stat.get("races") or 0)
        placed = int(stat.get("placed") or 0)
        picks = int(stat.get("picks") or 0)
        c3.caption(f"{races_n} 场 · {placed}/{picks} 个号码进入前三" if races_n else "尚无派彩样本")

    st.divider()
    for race in board["races"]:
        status = SELL_LABEL.get(str(race.get("sell_status") or ""), str(race.get("sell_status") or "—"))
        title = f"第 {race.get('race_no') or '?'} 场 · {status}"
        with st.expander(title, expanded=True):
            for item in race["strategies"]:
                stat = rates.get(item["id"]) or {}
                placed = item.get("placed")
                tail = f"本场 {placed}/{len(item['picks'])}" if placed is not None else "本场未派彩"
                st.markdown(
                    f"**{item['label']}** · 入围 {_pct(stat.get('rate'))} · {tail}",
                )
                st.markdown(_numbers(item["picks"], item["marks"]), unsafe_allow_html=True)


_board()
