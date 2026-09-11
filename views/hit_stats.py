"""
命中率瀏覽（用戶／管理端共用，唯讀）

展示各因子與推介軌道的 WIN／PLA／WQ／PQ／T3／T4，以及各賽日 Top 5，
方便依單獨統計挑選參考訊號（非僅綜合推介）。
讀自 hit_rate_day_snapshots（結算時寫入）；缺則自動補算。
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from auth_utils import is_admin
from factor_calibration import FactorCalibration, PLA_FINISH_MAX, SIGNAL_DEFS
from ui_theme import inject_admin_css, inject_user_css, page_header

if is_admin():
    inject_admin_css()
else:
    inject_user_css()
    # 表格頁需要比賽日速覽稍寬
    st.markdown(
        """
<style>
.block-container { max-width: 720px !important; }
</style>
        """,
        unsafe_allow_html=True,
    )

page_header(
    "命中率榜",
    "各因子／推介軌道結算命中 · 各賽日 Top 5（賽前快照 × 賽後名次）",
)

st.markdown(
    f"""
**怎麼用**  
選排序指標（WIN／PLA／WQ／PQ／T3／T4），看總表與各賽日 Top 5，自行挑命中較穩的訊號作參考。  

**規則摘要**  
WIN＝推介頭兩位任一第 1　·　PLA＝頭兩位任一前 {PLA_FINISH_MAX}　·　
WQ＝頭三位含冠及亞　·　PQ＝頭三位命中冠亞季其中≥2席　·　
T3／T4＝全部推介覆蓋冠亞季（殿）
"""
)

METRIC_OPTS = ["WIN%", "PLA%", "WQ%", "PQ%", "T3%", "T4%", "WIN相對隨機"]
DISPLAY_COLS = [
    "訊號",
    "WIN%",
    "PLA%",
    "WQ%",
    "PQ%",
    "T3%",
    "T4%",
    "有效場次",
    "總場次",
    "覆蓋率%",
    "平均推介數",
    "WIN相對隨機",
]

cal = FactorCalibration()
batches = cal.list_batches()
settled = (
    batches[batches["settled_at"].notna()].copy()
    if not batches.empty
    else pd.DataFrame()
)

if settled.empty:
    st.info("尚無已結算快照。結算後才會出現命中率榜（管理員於「因子命中率」頁操作）。")
    st.stop()

settled["_d"] = settled["racing_date"].astype(str).str[:10]
dates = sorted(settled["_d"].unique().tolist(), reverse=True)

c1, c2, c3 = st.columns([1.2, 1, 1])
with c1:
    metric = st.selectbox("排序／Top 指標", METRIC_OPTS, index=0)
with c2:
    top_n = st.selectbox("各賽日 Top", [3, 5, 8, 10], index=1)
with c3:
    scope = st.selectbox(
        "範圍",
        ["全部已結算", "單一賽日"],
        index=0,
    )

day_filter = None
course_filter = None
if scope == "單一賽日":
    d1, d2 = st.columns(2)
    with d1:
        day_filter = st.selectbox("賽日", dates, index=0)
    courses = sorted(
        settled.loc[settled["_d"] == day_filter, "course"].astype(str).unique().tolist()
    )
    with d2:
        course_filter = st.selectbox("場地", courses, index=0)

batch_ids = None
if day_filter and course_filter:
    batch_ids = settled.loc[
        (settled["_d"] == day_filter) & (settled["course"].astype(str) == course_filter),
        "batch_id",
    ].tolist()


@st.cache_data(ttl=120, show_spinner="載入命中統計（日快照）…")
def _load(metric: str, top_n: int, batch_key: tuple | None):
    ids = list(batch_key) if batch_key else None
    return FactorCalibration().evaluate_raceday_rankings(
        only_settled=True,
        metric=metric,
        top_n=top_n,
        batch_ids=ids,
        prefer_snapshot=True,
        recompute_if_missing=True,
    )


batch_key = tuple(batch_ids) if batch_ids else None
overall, day_top, meta = _load(metric, int(top_n), batch_key)

if meta.get("error"):
    st.warning(meta["error"])
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Batch", meta.get("n_batches", 0))
m2.metric("場次", meta.get("n_races", 0))
m3.metric("賽日組", meta.get("n_days", 0))
m4.metric("來源", "日快照" if meta.get("from_snapshot") else "即時重算")
st.caption(meta.get("note", ""))

# —— 總表：依指標排序 ——
st.subheader(f"① 總命中率（依 {metric}）")
if overall.empty:
    st.info("無統計列。")
else:
    show = overall.copy()
    if metric in show.columns:
        show = show.sort_values(
            by=[metric, "有效場次"], ascending=[False, False], kind="mergesort"
        ).reset_index(drop=True)
    cols = [c for c in DISPLAY_COLS if c in show.columns]
    st.dataframe(show[cols], use_container_width=True, hide_index=True, height=420)

    # 訊號類型提示
    factor_labels = {lab for lab, _c, w in SIGNAL_DEFS if w}
    rec_labels = {lab for lab, _c, w in SIGNAL_DEFS if not w}
    st.caption(
        "因子："
        + "、".join(sorted(factor_labels))
        + "　｜　推介軌道："
        + "、".join(sorted(rec_labels))
    )

# —— 各賽日 Top N ——
st.subheader(f"② 各賽日 Top {top_n}（{metric}）")
if day_top.empty:
    st.info("尚無分日排名。")
else:
    day_keys = (
        day_top.groupby(["賽日", "場地"], sort=False).size().reset_index(name="_n")
    )
    for _, dk in day_keys.iterrows():
        d, course = dk["賽日"], dk["場地"]
        sub = day_top[(day_top["賽日"] == d) & (day_top["場地"] == course)].copy()
        n_races = sub["場次數"].iloc[0] if "場次數" in sub.columns and len(sub) else "—"
        with st.expander(f"{d}　{course}　·　{n_races} 場　·　Top {len(sub)}", expanded=(scope == "單一賽日")):
            view_cols = [
                c
                for c in [
                    "排名",
                    "訊號",
                    "WIN%",
                    "PLA%",
                    "WQ%",
                    "PQ%",
                    "T3%",
                    "T4%",
                    "有效場次",
                    "覆蓋率%",
                    "WIN相對隨機",
                ]
                if c in sub.columns
            ]
            st.dataframe(
                sub[view_cols],
                use_container_width=True,
                hide_index=True,
            )

# —— 廣告推介宣傳命中 ——
st.subheader("③ 廣告推介 · 賽後宣傳素材")
st.caption(
    "以賽前鎖定的綜合推介列（最多 4 匹）為準；"
    "篩選可作賽後宣傳的場次（獨贏高賠／冠亞高賠／T3／T4）。"
)


@st.cache_data(ttl=90, show_spinner="載入廣告宣傳命中…")
def _ad_promo(batch_key: tuple | None):
    ids = list(batch_key) if batch_key else None
    return FactorCalibration().evaluate_ad_promo_hits(
        only_settled=True, batch_ids=ids
    )


ad_races, ad_summary, ad_meta = _ad_promo(batch_key)
if ad_meta.get("error"):
    st.info(ad_meta["error"])
elif ad_races.empty:
    st.info("尚無廣告推介結算資料（請用新快照鎖定 ad_pick_rank 後再結算）。")
else:
    a1, a2, a3 = st.columns(3)
    a1.metric("有效場次", ad_meta.get("n_races_scored", 0))
    a2.metric("可宣傳場次", ad_meta.get("n_promo_races", 0))
    a3.metric("推介上限", ad_meta.get("ad_pick_max", 4))
    st.caption(ad_meta.get("note", ""))
    if not ad_summary.empty:
        st.dataframe(ad_summary, use_container_width=True, hide_index=True)
    only_promo = st.checkbox("只顯示可宣傳場次", value=True, key="ad_promo_only")
    show_ad = ad_races[ad_races["可宣傳"] == True] if only_promo else ad_races  # noqa: E712
    st.dataframe(show_ad, use_container_width=True, hide_index=True, height=360)

if is_admin():
    st.divider()
    st.subheader("管理：補回命中率日快照")
    st.caption(
        "新規則（WQ／PQ）或舊結算缺快照時，一鍵重算寫入 `hit_rate_day_snapshots`。"
        "CLI：`python backfill_hit_snapshots.py`"
    )
    b1, b2 = st.columns(2)
    with b1:
        if st.button("只補缺漏", use_container_width=True):
            with st.spinner("補回中…"):
                out = FactorCalibration().backfill_hit_rate_snapshots(only_missing=True)
            st.success(f"完成 {out.get('n_done')}；略過已有 {out.get('n_skip')}")
            st.cache_data.clear()
            st.rerun()
    with b2:
        if st.button("全部重算覆寫", type="primary", use_container_width=True):
            with st.spinner("重算全部日快照…"):
                out = FactorCalibration().backfill_hit_rate_snapshots(only_missing=False)
            st.success(f"完成 {out.get('n_done')} batch")
            st.cache_data.clear()
            st.rerun()
    st.caption("管理端寫入預測快照／結算請到「因子命中率」校正台；本頁命中表唯讀。")
