"""廣告歸檔瀏覽＋重做（賽前／賽後共用；只存 JSON，不存海報 PNG）。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from ad_copy_jobs import (
    ARCHIVE_KINDS,
    default_output_dir,
    list_archive_meetings,
    load_archive_latest,
    redo_archive_job,
)

_KIND_LABELS = {
    "copy": "海報資料",
    "social": "賽前文案",
    "promo_hits": "賽後命中",
    "post_race": "賽後文案",
}


def _allowed_kinds(*, show_pre_race: bool, show_post_race: bool) -> List[str]:
    allowed: List[str] = []
    if show_pre_race:
        allowed.extend(["copy", "social"])
    if show_post_race:
        allowed.extend(["promo_hits", "post_race"])
    return allowed




def _render_empty_post_race_generate(
    *,
    out_root: Path,
    key_prefix: str,
    default_racing_date: Optional[str] = None,
    default_course: Optional[str] = None,
) -> None:
    """無歸檔時仍可人手補跑（SETTLED 後 tick 漏跑嘅救援路徑）。"""
    st.caption("SETTLED 後應自動產出；若自動化漏咗，可喺下面人手重跑命中＋文案。")
    c1, c2, c3 = st.columns([2, 1, 2])
    with c1:
        d_default = date.fromisoformat(
            (default_racing_date or date.today().isoformat())[:10]
        )
        d_pick = st.date_input(
            "賽日",
            value=d_default,
            key=f"{key_prefix}_empty_date",
        )
    with c2:
        courses = ["HV", "ST"]
        c_default = (default_course or "HV").upper()
        c_idx = courses.index(c_default) if c_default in courses else 0
        c_pick = st.selectbox(
            "場地",
            courses,
            index=c_idx,
            key=f"{key_prefix}_empty_course",
        )
    with c3:
        st.write("")
        do_gen = st.button(
            "立即產出賽後命中＋文案",
            type="primary",
            key=f"{key_prefix}_empty_cascade",
            use_container_width=True,
        )
    if not do_gen:
        return
    with st.spinner("promo_hits → post_race…"):
        result = redo_archive_job(
            kind="cascade",
            racing_date=d_pick.isoformat(),
            course=str(c_pick),
            output_root=out_root,
        )
    st.session_state[f"{key_prefix}_last_redo"] = result
    if result.get("ok"):
        promo = result.get("promo_hits") or {}
        st.success(f"完成：可宣傳 {promo.get('n_promo_races', '—')} 場")
    else:
        st.error(result.get("error") or str(result))
    st.rerun()


def render_ad_archive_panel(
    *,
    output_root: Optional[Path] = None,
    key_prefix: str = "ad_arch",
    show_pre_race: bool = True,
    show_post_race: bool = True,
    default_racing_date: Optional[str] = None,
    default_course: Optional[str] = None,
) -> None:
    """
    共用歸檔面板（精簡版）。
    - show_pre_race: copy / social
    - show_post_race: promo_hits / post_race
    """
    out_root = Path(output_root) if output_root else default_output_dir()
    st.caption("只存 JSON，不存海報 PNG。海報請用「重產海報」由快照重畫。")

    rows = list_archive_meetings(out_root)
    if not rows:
        st.info(
            f"尚未有歸檔。目錄：`{out_root / 'archive'}`"
            "（亦會讀共用 DB `ad_archives`）"
        )
        if show_post_race:
            _render_empty_post_race_generate(
                out_root=out_root,
                key_prefix=key_prefix,
                default_racing_date=default_racing_date,
                default_course=default_course,
            )
        return

    labels = [r["label"] for r in rows]
    pick = st.selectbox("賽日／場地", labels, key=f"{key_prefix}_meeting")
    meeting = next(r for r in rows if r["label"] == pick)
    d, c = meeting["racing_date"], meeting["course"]
    kinds: Dict[str, Any] = meeting.get("kinds") or {}

    allowed = _allowed_kinds(show_pre_race=show_pre_race, show_post_race=show_post_race)
    present = [k for k in ARCHIVE_KINDS if k in kinds and k in allowed]
    if not present:
        st.warning("此賽日尚未有符合本區的歸檔。")
        if show_post_race and st.button(
            "立即產出賽後命中＋文案",
            type="primary",
            key=f"{key_prefix}_missing_cascade",
        ):
            with st.spinner("promo_hits → post_race…"):
                result = redo_archive_job(
                    kind="cascade",
                    racing_date=d,
                    course=c,
                    output_root=out_root,
                )
            st.session_state[f"{key_prefix}_last_redo"] = result
            if result.get("ok"):
                st.success("已產出")
            else:
                st.error(result.get("error") or str(result))
            st.rerun()
        return

    status_bits = [
        f"**{_KIND_LABELS.get(k, k)}** {'✅' if k in kinds else '—'}" for k in allowed
    ]
    st.markdown(" · ".join(status_bits))

    kind = st.radio(
        "類型",
        present,
        format_func=lambda k: _KIND_LABELS.get(k, k),
        horizontal=True,
        key=f"{key_prefix}_kind",
        label_visibility="collapsed",
    )
    payload = load_archive_latest(out_root, d, c, kind)
    if not payload:
        st.warning("找不到 latest 檔。")
        return

    bid = str((kinds.get(kind) or {}).get("batch_id") or "")
    st.caption(f"batch `{bid or '—'}`")

    is_post = kind in ("promo_hits", "post_race") and show_post_race
    do_cascade = False
    do_redo = False

    if is_post:
        a1, a2, a3 = st.columns([1, 1, 2])
        with a1:
            do_cascade = st.button(
                "重做命中＋文案",
                type="primary",
                key=f"{key_prefix}_cascade",
                help="一次重跑 promo_hits → post_race",
                use_container_width=True,
            )
        with a2:
            do_redo = st.button(
                "只重做此類型",
                key=f"{key_prefix}_redo",
                use_container_width=True,
            )
        with a3:
            st.download_button(
                "⬇️ 下載 JSON",
                data=json.dumps(payload, ensure_ascii=False, indent=2),
                file_name=f"{d}_{c}_{kind}_latest.json",
                mime="application/json",
                key=f"{key_prefix}_dl",
                use_container_width=True,
            )
    else:
        a1, a2 = st.columns([1, 2])
        with a1:
            do_redo = st.button(
                "重做此類型",
                type="primary",
                key=f"{key_prefix}_redo",
                use_container_width=True,
                disabled=(kind == "copy"),
                help=(
                    "海報請用「重產海報」由快照重畫"
                    if kind == "copy"
                    else "強制重跑此類型文案"
                ),
            )
        with a2:
            st.download_button(
                "⬇️ 下載 JSON",
                data=json.dumps(payload, ensure_ascii=False, indent=2),
                file_name=f"{d}_{c}_{kind}_latest.json",
                mime="application/json",
                key=f"{key_prefix}_dl",
                use_container_width=True,
            )

    if do_cascade:
        with st.spinner("重做命中＋文案…"):
            result = redo_archive_job(
                kind="cascade",
                racing_date=d,
                course=c,
                batch_id=bid,
                output_root=out_root,
            )
        st.session_state[f"{key_prefix}_last_redo"] = result
        if result.get("ok"):
            st.success("賽後 cascade 完成")
        else:
            st.error(result.get("error") or str(result))
        st.rerun()

    if do_redo:
        with st.spinner("重做中…"):
            result = redo_archive_job(
                kind=kind,
                racing_date=d,
                course=c,
                batch_id=bid,
                output_root=out_root,
            )
        st.session_state[f"{key_prefix}_last_redo"] = result
        if result.get("ok"):
            st.success(
                "完成"
                + ("（已略過／幂等）" if result.get("skipped") else "")
                + f"：{result.get('reason') or result.get('source') or kind}"
            )
        else:
            st.error(result.get("error") or str(result))
        st.rerun()

    if kind == "post_race" and payload.get("post_text"):
        st.text_area(
            "賽後貼文",
            value=str(payload.get("post_text")),
            height=220,
            key=f"{key_prefix}_post",
        )
    elif kind == "promo_hits":
        promo = list(payload.get("promo_races") or [])
        st.caption(
            f"可宣傳 {len(promo)} / 評分 {payload.get('n_races_scored') or '—'} 場"
        )
        if promo:
            st.dataframe(promo[:8], use_container_width=True, hide_index=True)
    elif kind == "social":
        if payload.get("post_text"):
            st.text_area(
                "賽前貼文",
                value=str(payload.get("post_text")),
                height=200,
                key=f"{key_prefix}_social",
            )
        else:
            st.json(
                {
                    k: payload.get(k)
                    for k in ("title", "subtitle", "featured", "hashtags")
                    if k in payload
                }
            )
    elif kind == "copy":
        st.caption("海報生成資料（無 PNG）。請到「重產海報」按 batch 重畫。")
        st.write(payload.get("meeting") or {})

    with st.expander("完整 JSON", expanded=False):
        st.json(payload)
