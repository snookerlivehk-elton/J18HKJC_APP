"""廣告歸檔瀏覽＋重做（賽前／賽後共用；只存 JSON，不存海報 PNG）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

from ad_copy_jobs import (
    ARCHIVE_KINDS,
    default_output_dir,
    list_archive_meetings,
    load_archive_latest,
    redo_archive_job,
)

_KIND_LABELS = {
    "copy": "海報生成資料",
    "social": "賽前社交文案",
    "promo_hits": "賽後命中評估",
    "post_race": "賽後宣傳文案",
}


def render_ad_archive_panel(
    *,
    output_root: Optional[Path] = None,
    key_prefix: str = "ad_arch",
    show_pre_race: bool = True,
    show_post_race: bool = True,
) -> None:
    """
    共用歸檔面板。
    - show_pre_race: copy / social
    - show_post_race: promo_hits / post_race
    """
    out_root = Path(output_root) if output_root else default_output_dir()
    st.markdown("### 歷史歸檔（可翻查／重做）")
    st.caption(
        "只保存生成用 JSON（`copy`／文案／命中），**不存海報 PNG**。"
        "海報請用「手動重產」由快照重畫；賽後文案會用結構化名次／賠率／馬名交 AI。"
    )

    rows = list_archive_meetings(out_root)
    if not rows:
        st.info(f"尚未有歸檔。目錄：`{out_root / 'archive'}`")
        return

    labels = [r["label"] for r in rows]
    pick = st.selectbox("賽日／場地", labels, key=f"{key_prefix}_meeting")
    meeting = next(r for r in rows if r["label"] == pick)
    d, c = meeting["racing_date"], meeting["course"]
    kinds: Dict[str, Any] = meeting.get("kinds") or {}

    allowed = []
    if show_pre_race:
        allowed.extend(["copy", "social"])
    if show_post_race:
        allowed.extend(["promo_hits", "post_race"])

    present = [k for k in ARCHIVE_KINDS if k in kinds and k in allowed]
    if not present:
        st.warning("此賽日尚未有符合本頁範圍的歸檔。")
        return

    cols = st.columns(len(present))
    for i, kind in enumerate(present):
        meta = kinds[kind]
        with cols[i]:
            st.metric(_KIND_LABELS.get(kind, kind), "有" if meta else "—")
            bid = meta.get("batch_id") or "—"
            st.caption(f"batch `{bid}`")

    kind = st.radio(
        "檢視／重做類型",
        present,
        format_func=lambda k: _KIND_LABELS.get(k, k),
        horizontal=True,
        key=f"{key_prefix}_kind",
    )
    payload = load_archive_latest(out_root, d, c, kind)
    if not payload:
        st.warning("找不到 latest 檔。")
        return

    bid = str((kinds.get(kind) or {}).get("batch_id") or "")
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("強制重做", type="primary", key=f"{key_prefix}_redo"):
            with st.spinner("重做中…"):
                result = redo_archive_job(
                    kind=kind if kind != "promo_hits" else "promo_hits",
                    racing_date=d,
                    course=c,
                    batch_id=bid,
                    output_root=out_root,
                )
            if kind == "promo_hits":
                # 命中後可一併重產文案
                pass
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
    with c2:
        if show_post_race and st.button(
            "重做命中＋文案", key=f"{key_prefix}_cascade", disabled=not show_post_race
        ):
            with st.spinner("cascade…"):
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
    with c3:
        st.download_button(
            "⬇️ 下載此份 JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2),
            file_name=f"{d}_{c}_{kind}_latest.json",
            mime="application/json",
            key=f"{key_prefix}_dl",
        )

    if kind == "post_race" and payload.get("post_text"):
        st.text_area("貼文預覽", value=str(payload.get("post_text")), height=220, key=f"{key_prefix}_post")
    elif kind == "promo_hits":
        promo = list(payload.get("promo_races") or [])
        st.caption(f"可宣傳 {len(promo)} / 評分 {payload.get('n_races_scored') or '—'} 場")
        if promo:
            st.json(promo[:5])
    elif kind == "copy":
        st.caption("海報生成資料（無 PNG）。可用「手動重產」按 batch 重畫。")
        meeting_meta = payload.get("meeting") or {}
        st.write(meeting_meta)
    elif kind == "social":
        if payload.get("post_text"):
            st.text_area("賽前貼文", value=str(payload.get("post_text")), height=200, key=f"{key_prefix}_social")
        else:
            st.json({k: payload.get(k) for k in ("title", "subtitle", "featured", "hashtags") if k in payload})

    with st.expander("完整 JSON", expanded=False):
        st.json(payload)
