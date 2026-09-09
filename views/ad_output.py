"""廣告輸出 — 全賽日融合主海報 + 模型／AI 對照（固定檔名覆蓋）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from ad_llm_copy import (
    COMMENT_MAX_CHARS,
    DEFAULT_TONE,
    POST_RACE_COMMENT_MAX_CHARS,
    TONE_PRESETS,
    AdSocialCopywriter,
    count_candidate_races,
    format_post_race_post_text,
    format_social_post_text,
    load_post_race_social_copy,
    load_social_copy,
    normalize_tone,
    post_footer_text,
    post_race_social_copy_path,
    save_post_race_social_copy,
    save_social_copy,
    social_copy_path,
    tone_label,
)
from ad_poster import (
    default_output_dir,
    generate_ads_from_snapshot_batch,
    latest_paths,
    load_copy_json,
    make_preview_jpeg,
    zip_batch_bytes,
)
from factor_calibration import FactorCalibration


def _promo_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """UI 表格隱藏內部欄位。"""
    if df is None or df.empty:
        return df
    drop_cols = [c for c in ("hit_codes", "picks_detail") if c in df.columns]
    return df.drop(columns=drop_cols) if drop_cols else df


def _render_outputs(out_root: Path, *, key_prefix: str = "browse") -> None:
    """預覽＋下載（ZIP／單張）。可在瀏覽頁或重產成功後同頁使用。"""
    paths = latest_paths(out_root)
    has_any = (
        paths["fused"].is_file() or paths["model"].is_file() or paths["ai"].is_file()
    )
    if not has_any:
        st.warning("尚無海報。請先完成預測快照，或使用「手動重產」。")
        return

    copy = load_copy_json(out_root)
    meeting = (copy or {}).get("meeting") or {}
    if meeting:
        st.write(
            f"**{meeting.get('racing_date', '')} {meeting.get('course', '')}** · "
            f"{meeting.get('n_races', '?')} 場 · batch `{meeting.get('batch_id', '')}`"
        )
        fb = meeting.get("fused_bytes")
        mb = meeting.get("model_bytes")
        ab = meeting.get("ai_bytes")
        if fb or mb or ab:
            st.caption(
                f"檔案大小：融合 {int(fb or 0) // 1024} KB · "
                f"模型 {int(mb or 0) // 1024} KB · AI {int(ab or 0) // 1024} KB"
            )

    try:
        st.download_button(
            "⬇️ 下載 ZIP（fused + model + ai + copy）",
            data=zip_batch_bytes(out_root),
            file_name="ad_output_latest.zip",
            mime="application/zip",
            key=f"zip_{key_prefix}",
            type="primary",
        )
    except Exception as e:
        st.caption(f"ZIP 失敗：{e}")

    # 主視覺：融合
    st.markdown("**融合推介 · 全賽日（社交主視覺）**")
    p_fused = paths["fused"]
    if p_fused.is_file():
        try:
            st.image(
                make_preview_jpeg(p_fused),
                caption=f"{p_fused.name} · {p_fused.stat().st_size // 1024} KB",
                use_container_width=True,
            )
        except Exception as e:
            st.warning(f"預覽失敗：{e}")
        with open(p_fused, "rb") as f:
            st.download_button(
                f"⬇️ 下載 {p_fused.name}",
                data=f.read(),
                file_name=p_fused.name,
                mime="image/png",
                key=f"dl_{key_prefix}_fused",
            )
    else:
        st.warning("尚無融合海報（請重新產生快照／廣告）")

    cols = st.columns(2)
    for col, label, key in (
        (cols[0], "模型 · 對照", "model"),
        (cols[1], "AI 馬評 · 對照", "ai"),
    ):
        with col:
            st.markdown(f"**{label}**")
            p = paths[key]
            if p.is_file():
                try:
                    st.image(
                        make_preview_jpeg(p),
                        caption=f"{p.name} · {p.stat().st_size // 1024} KB",
                        use_container_width=True,
                    )
                except Exception as e:
                    st.warning(f"預覽失敗：{e}")
                with open(p, "rb") as f:
                    st.download_button(
                        f"⬇️ 下載 {p.name}",
                        data=f.read(),
                        file_name=p.name,
                        mime="image/png",
                        key=f"dl_{key_prefix}_{key}",
                    )
            else:
                st.warning("尚無檔案")

    if copy:
        with st.expander("宣傳文案", expanded=False):
            st.markdown("**融合**")
            st.write(copy.get("fused_copy") or "")
            st.markdown("**模型**")
            st.write(copy.get("model_copy") or "")
            st.markdown("**AI 馬評**")
            st.write(copy.get("ai_copy") or "")


def _render_social_copy(output_root: Path, copy_data: Dict[str, Any]) -> None:
    st.markdown("### AI 社交文案")
    writer = AdSocialCopywriter()
    if writer.is_ready():
        st.caption(f"LLM 模型：`{writer.nlp.model}`")
    else:
        st.warning("未偵測到 OPENAI_API_KEY；暫時無法生成 AI 精選評述。")

    n_cand = count_candidate_races(copy_data)
    if not copy_data:
        st.warning("尚未找到 copy.json。請先完成預測快照或「手動重產」。")
    elif n_cand <= 0:
        st.warning(
            "copy.json 未有推介場次資料，無法生成精選文案。"
            "請先重新生成廣告輸出（需含模型／AI 推介）。"
        )
    else:
        st.caption(f"可用推介場次：{n_cand} 場")

    tone_options = list(TONE_PRESETS.keys())
    tone_labels = {k: TONE_PRESETS[k]["label"] for k in tone_options}
    current_tone = normalize_tone(st.session_state.get("ad_social_tone") or DEFAULT_TONE)
    tone = st.radio(
        "文案語氣",
        options=tone_options,
        index=tone_options.index(current_tone),
        format_func=lambda k: tone_labels[k],
        horizontal=True,
        key="ad_social_tone",
        help="高互動型：像香港 FB／IG 貼文，易讚易留言；文筆固定港式，避免國語翻譯腔。",
    )
    st.caption(TONE_PRESETS[normalize_tone(tone)]["hint"])

    default_prompt = (
        "寫成香港人日常 FB／IG 貼文口吻；"
        "標題帶提問或叫人留言；"
        "優先挑選融合推介名單內、模型與 AI 都有支持的場次；"
        f"每匹馬評述不超過{COMMENT_MAX_CHARS}字；"
        "唔好用國語翻譯腔。"
    )
    custom_prompt = st.text_area(
        "LLM 提示詞",
        value=st.session_state.get("ad_social_prompt") or default_prompt,
        height=110,
        key="ad_social_prompt",
        help="可補充重點或受眾要求；文末固定聲明由系統自動附加。",
    )
    with st.expander("文末固定聲明（系統自動附加）", expanded=False):
        st.code(post_footer_text(), language=None)

    social_data = load_social_copy(output_root)
    c1, c2 = st.columns([1, 1])
    with c1:
        disabled = (not writer.is_ready()) or n_cand <= 0
        if st.button("生成 AI 精選評述", type="primary", key="ad_social_generate", disabled=disabled):
            with st.spinner("AI 正在挑選精選場次與撰寫文案…"):
                try:
                    social_data = writer.generate_social_copy(
                        copy_data,
                        custom_prompt=custom_prompt,
                        tone=tone,
                    )
                    save_social_copy(output_root, social_data)
                    st.session_state["ad_social_result"] = social_data
                    src_note = social_data.get("source") or "llm"
                    if str(src_note).startswith("fallback"):
                        st.warning("LLM 暫時未能完成，已用推介自動補齊精選，並附上固定結尾。")
                    else:
                        st.success(f"已生成 AI 精選評述（{tone_label(tone)}）與 hashtag")
                except Exception as e:
                    st.session_state["ad_social_result"] = {"error": str(e)}
                    st.error(f"生成失敗：{e}")
    with c2:
        p = social_copy_path(output_root)
        if p.is_file():
            st.caption(f"已保存：`{p.name}`")

    social_data = st.session_state.get("ad_social_result") or social_data
    if not social_data:
        st.info("揀好語氣後按「生成 AI 精選評述」，系統會以香港貼文文筆挑選精選場次、產生標題、hashtags，並自動加上文末聲明。")
        return
    if social_data.get("error"):
        st.error(str(social_data.get("error")))
        return

    tone_badge = social_data.get("tone_label") or tone_label(social_data.get("tone"))
    st.caption(f"語氣：{tone_badge} · 香港貼文文筆")
    st.markdown(f"#### {social_data.get('title') or '未提供標題'}")
    if social_data.get("subtitle"):
        st.caption(social_data["subtitle"])

    featured = list(social_data.get("featured") or [])
    if featured:
        cols = st.columns(min(3, len(featured)))
        for col, item in zip(cols, featured):
            with col:
                race_no = item.get("race_no") or "?"
                st.markdown(
                    f"**第{race_no}場 · {item.get('horse_no', '?')} {item.get('horse_name', '')}**"
                )
                st.write(item.get("comment") or "")
                if item.get("basis"):
                    st.caption(item.get("basis"))

    hashtags = list(social_data.get("hashtags") or [])
    if hashtags:
        st.markdown("**Hashtags**")
        st.code(" ".join(hashtags), language=None)

    post_text = str(social_data.get("post_text") or "").strip()
    if not post_text:
        post_text = format_social_post_text(social_data)
    st.text_area(
        "Facebook / IG 貼文（可直接複製）",
        value=post_text,
        height=280,
        key="ad_social_post_layout",
    )

    st.download_button(
        "⬇️ 下載 social_copy.json",
        data=__import__("json").dumps(social_data, ensure_ascii=False, indent=2),
        file_name="social_copy.json",
        mime="application/json",
        key="ad_social_download",
    )


def _render_post_race_ad(output_root: Path) -> None:
    """賽後廣告：顯示宣傳命中場次，並由 AI 撮寫回顧文案。"""
    st.markdown("### 賽後廣告")
    st.caption(
        "當已結算快照符合宣傳規則（冷門獨贏／高賠連贏／三重／四重覆蓋）時，"
        "本頁列出命中場次與推介資料，並可交由 AI 撮寫賽後社交文案。"
    )
    with st.expander("撮寫文案建議（給 AI／人手）", expanded=False):
        st.markdown(
            """
1. **定位**：賽後回顧／兌現，不是再推新貼士；口吻用「賽前有列、賽後兌現」。
2. **優先序**：冷門獨贏（≥7）→ 高賠連贏（冠亞＋其中一匹 >10）→ 三重覆蓋 → 四重覆蓋。
3. **每場結構**：規則標籤 → 推介馬＋名次／賠率 → 一句近績色彩（可選）。
4. **禁用詞**：穩膽、必中、包中、穩贏；可用「融合推介有列出」「賽後兌現」。
5. **篇幅**：標題一句；每場評述約 60–80 字；文末用賽後免責（系統自動附加）。
6. **Hashtag**：可加 `#賽後回顧` `#賽果` `#冷門`，保留 `#J18` `#賽馬`。
            """.strip()
        )

    @st.cache_data(ttl=60, show_spinner="載入賽後宣傳命中…")
    def _load_promo(batch_key: tuple | None):
        ids = list(batch_key) if batch_key else None
        return FactorCalibration().evaluate_ad_promo_hits(
            only_settled=True, batch_ids=ids
        )

    cal = FactorCalibration()
    try:
        bdf = cal.list_batches()
    except Exception as e:
        st.error(f"讀取快照失敗：{e}")
        return

    settled = (
        bdf[bdf["settled_at"].notna()] if bdf is not None and not bdf.empty else bdf
    )
    batch_key = None
    if settled is not None and not settled.empty:
        date_opts = sorted(
            {str(r.racing_date)[:10] for r in settled.itertuples()}, reverse=True
        )
        date_choice = st.selectbox(
            "賽日（可選；留空＝全部已結算）",
            options=["（全部）"] + date_opts,
            key="ad_post_race_date",
        )
        if date_choice != "（全部）":
            ids = [
                str(r.batch_id)
                for r in settled.itertuples()
                if str(r.racing_date)[:10] == date_choice
            ]
            batch_key = tuple(ids) if ids else None
    else:
        st.info("尚無已結算快照。請先完成預測快照並結算後再回來。")
        return

    races, summary, meta = _load_promo(batch_key)
    if meta.get("error"):
        st.info(meta["error"])
        return
    if races is None or races.empty:
        st.info("尚無廣告推介結算資料。")
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("有效場次", meta.get("n_races_scored", 0))
    m2.metric("可宣傳場次", meta.get("n_promo_races", 0))
    m3.metric("推介上限", meta.get("ad_pick_max", 4))
    if meta.get("note"):
        st.caption(meta["note"])
    if summary is not None and not summary.empty:
        st.dataframe(summary, use_container_width=True, hide_index=True)

    only_promo = st.checkbox("只顯示可宣傳場次", value=True, key="ad_post_only_promo")
    show = races[races["可宣傳"] == True] if only_promo else races  # noqa: E712
    st.dataframe(
        _promo_display_df(show),
        use_container_width=True,
        hide_index=True,
        height=320,
    )

    promo = races[races["可宣傳"] == True].copy()  # noqa: E712
    if promo.empty:
        st.warning("目前篩選範圍沒有可宣傳命中場次，暫未能生成賽後文案。")
        return

    # 可多選場次（預設全選當日／範圍內可宣傳）
    labels = []
    label_to_idx: Dict[str, int] = {}
    for i, row in enumerate(promo.to_dict(orient="records")):
        rn = row.get("race_no") or "?"
        rules = row.get("命中規則") or ""
        lab = f"{row.get('賽日','')} {row.get('場地','')} 第{rn}場 · {rules} · {row.get('race_id')}"
        labels.append(lab)
        label_to_idx[lab] = i

    selected = st.multiselect(
        "選擇要入文的命中場次（建議 1–3 場；AI 最多精選 3 場）",
        options=labels,
        default=labels[: min(3, len(labels))],
        key="ad_post_race_select",
    )
    if not selected:
        st.info("請至少選一場命中場次。")
        return

    selected_rows: List[Dict[str, Any]] = [
        promo.iloc[label_to_idx[lab]].to_dict() for lab in selected if lab in label_to_idx
    ]

    writer = AdSocialCopywriter()
    if writer.is_ready():
        st.caption(f"LLM 模型：`{writer.nlp.model}` · 評述上限 {POST_RACE_COMMENT_MAX_CHARS} 字")
    else:
        st.warning("未偵測到 OPENAI_API_KEY；仍可用命中資料自動出本地稿。")

    tone_options = list(TONE_PRESETS.keys())
    tone_labels = {k: TONE_PRESETS[k]["label"] for k in tone_options}
    current_tone = normalize_tone(
        st.session_state.get("ad_post_race_tone") or DEFAULT_TONE
    )
    tone = st.radio(
        "文案語氣",
        options=tone_options,
        index=tone_options.index(current_tone),
        format_func=lambda k: tone_labels[k],
        horizontal=True,
        key="ad_post_race_tone",
        help="賽後回顧同樣用港式文筆；高互動型適合叫人留言「邊場最驚喜」。",
    )
    st.caption(TONE_PRESETS[normalize_tone(tone)]["hint"])

    default_prompt = (
        "寫成香港 FB／IG 賽後回顧；"
        "標題突出「兌現／冷門／覆蓋」其中最有戲一點；"
        "每場講清規則＋推介＋名次／賠率；"
        "唔好寫必中；可叫人留言邊場最驚喜。"
    )
    custom_prompt = st.text_area(
        "額外撮寫指示（可選）",
        value=st.session_state.get("ad_post_race_prompt") or default_prompt,
        height=90,
        key="ad_post_race_prompt",
    )

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("生成賽後 AI 文案", type="primary", key="ad_post_race_go"):
            with st.spinner("撮寫賽後宣傳文案…"):
                try:
                    meeting = {
                        "racing_date": selected_rows[0].get("賽日") or "",
                        "course": selected_rows[0].get("場地") or "",
                        "n_promo_races": len(selected_rows),
                        "batch_ids": sorted(
                            {
                                str(r.get("batch_id"))
                                for r in selected_rows
                                if r.get("batch_id")
                            }
                        ),
                    }
                    data = writer.generate_post_race_copy(
                        selected_rows,
                        meeting=meeting,
                        custom_prompt=custom_prompt,
                        tone=tone,
                    )
                    save_post_race_social_copy(output_root, data)
                    st.session_state["ad_post_race_result"] = data
                    src = str(data.get("source") or "")
                    if src.startswith("fallback"):
                        st.warning(f"已出稿（後備）：{src}")
                    else:
                        st.success(f"已生成賽後文案（{tone_label(tone)}）")
                except Exception as e:
                    st.session_state["ad_post_race_result"] = {"error": str(e)}
                    st.error(f"生成失敗：{e}")
    with c2:
        p = post_race_social_copy_path(output_root)
        if p.is_file():
            st.caption(f"已保存：`{p.name}`")

    social_data = st.session_state.get("ad_post_race_result") or load_post_race_social_copy(
        output_root
    )
    if not social_data:
        st.info("揀好場次與語氣後按「生成賽後 AI 文案」。")
        return
    if social_data.get("error"):
        st.error(str(social_data.get("error")))
        return

    tone_badge = social_data.get("tone_label") or tone_label(social_data.get("tone"))
    st.caption(f"語氣：{tone_badge} · 賽後回顧 · 香港貼文文筆")
    st.markdown(f"#### {social_data.get('title') or '未提供標題'}")
    if social_data.get("subtitle"):
        st.caption(social_data["subtitle"])

    featured = list(social_data.get("featured") or [])
    if featured:
        cols = st.columns(min(3, len(featured)))
        for col, item in zip(cols, featured):
            with col:
                head = item.get("headline") or f"第{item.get('race_no', '?')}場"
                st.markdown(f"**{head}**")
                rules = item.get("rule_labels") or []
                if rules:
                    st.caption("、".join(str(x) for x in rules))
                if item.get("picks_line"):
                    st.write(item["picks_line"])
                st.write(item.get("comment") or "")
                if item.get("basis"):
                    st.caption(item.get("basis"))

    hashtags = list(social_data.get("hashtags") or [])
    if hashtags:
        st.markdown("**Hashtags**")
        st.code(" ".join(hashtags), language=None)

    post_text = str(social_data.get("post_text") or "").strip()
    if not post_text:
        post_text = format_post_race_post_text(social_data)
    st.text_area(
        "Facebook / IG 賽後貼文（可直接複製）",
        value=post_text,
        height=300,
        key="ad_post_race_post_layout",
    )
    st.caption("文末為賽後固定聲明（非賽前十分鐘預告）。")

    st.download_button(
        "⬇️ 下載 post_race_social_copy.json",
        data=__import__("json").dumps(social_data, ensure_ascii=False, indent=2),
        file_name="post_race_social_copy.json",
        mime="application/json",
        key="ad_post_race_download",
    )


st.title("廣告輸出")
st.caption(
    "每次預測快照成功後，系統把**全賽日**推介寫入海報（公司原圖風格）："
    "**融合推介**（社交主視覺）＋模型／AI 對照。"
    "每場最多 **4 匹**（只顯示馬號＋馬名，不含勝率）；"
    "藍／米色隨機；下次生成會**覆蓋**同一檔名；PNG ≤2MB。"
)

out_root = default_output_dir()
paths = latest_paths(out_root)
st.info(
    f"輸出：`{paths['fused'].name}` / `{paths['model'].name}` / `{paths['ai'].name}` @ `{out_root}`"
)
try:
    from ad_poster import font_status, _max_bytes

    fs = font_status()
    if fs.get("ok"):
        st.caption(f"字型：`{fs.get('path')}` · 上限 {_max_bytes() // 1024} KB／張 · 色調藍／米隨機")
    else:
        st.error(f"CJK 字型不可用：{fs.get('error') or '未找到字型檔'}")
except Exception as e:
    st.warning(f"字型檢查失敗：{e}")

tab_browse, tab_post, tab_regen = st.tabs(["瀏覽輸出", "賽後廣告", "手動重產"])

with tab_browse:
    _render_outputs(out_root, key_prefix="browse")
    copy_data = load_copy_json(out_root)
    st.divider()
    _render_social_copy(out_root, copy_data)

with tab_post:
    _render_post_race_ad(out_root)

with tab_regen:
    st.markdown("選擇預測快照批次，依鎖分重產全賽日海報（覆蓋 `model.png` / `ai.png`）。")
    cal = FactorCalibration()
    try:
        bdf = cal.list_batches()
    except Exception as e:
        bdf = None
        st.error(f"讀取快照批次失敗：{e}")
    if bdf is not None and bdf.empty:
        st.warning("尚無預測快照批次")
    elif bdf is not None:
        opts = {
            f"{r.batch_id} · {str(r.racing_date)[:10]} {r.course} · rows={int(r.n_rows)}": str(
                r.batch_id
            )
            for r in bdf.itertuples()
        }
        blabel = st.selectbox("預測批次", list(opts.keys()), key="ad_regen_batch")
        bid = opts[blabel]
        if st.button("重新生成廣告輸出", type="primary", key="ad_regen_go"):
            with st.spinner("生成全賽日海報…"):
                try:
                    result = generate_ads_from_snapshot_batch(bid, output_root=out_root)
                    st.session_state["ad_last_result"] = result
                    if not (result.get("ok") or result.get("races_written")):
                        st.error(result.get("error") or "重產失敗")
                    errs = result.get("errors") or []
                    if errs:
                        st.warning(
                            "部分錯誤："
                            + "；".join(
                                f"{e.get('race_id')}: {e.get('error')}" for e in errs[:5]
                            )
                        )
                except Exception as e:
                    st.session_state["ad_last_result"] = {"ok": False, "error": str(e)}
                    st.error(f"重產失敗：{e}")

        last: Optional[Dict[str, Any]] = st.session_state.get("ad_last_result")
        if last and (last.get("ok") or last.get("races_written")):
            st.success(
                f"完成：{last.get('races_written', 0)} 場合入 2 張海報 · "
                f"模型 {int(last.get('model_bytes') or 0) // 1024} KB / "
                f"AI {int(last.get('ai_bytes') or 0) // 1024} KB"
            )
            st.markdown("#### 立即下載／預覽")
            _render_outputs(out_root, key_prefix="after_regen")
        elif last and last.get("error"):
            st.error(last.get("error"))
