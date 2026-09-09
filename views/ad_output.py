"""廣告輸出 — 全賽日模型／AI 各一張海報（固定檔名覆蓋）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

from ad_llm_copy import (
    DEFAULT_TONE,
    TONE_PRESETS,
    AdSocialCopywriter,
    count_candidate_races,
    format_social_post_text,
    load_social_copy,
    normalize_tone,
    post_footer_text,
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


def _render_outputs(out_root: Path, *, key_prefix: str = "browse") -> None:
    """預覽＋下載（ZIP／單張）。可在瀏覽頁或重產成功後同頁使用。"""
    paths = latest_paths(out_root)
    has_any = paths["model"].is_file() or paths["ai"].is_file()
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
        mb = meeting.get("model_bytes")
        ab = meeting.get("ai_bytes")
        if mb or ab:
            st.caption(
                f"檔案大小：模型 {int(mb or 0) // 1024} KB · AI {int(ab or 0) // 1024} KB"
            )

    try:
        st.download_button(
            "⬇️ 下載 ZIP（model + ai + copy）",
            data=zip_batch_bytes(out_root),
            file_name="ad_output_latest.zip",
            mime="application/zip",
            key=f"zip_{key_prefix}",
            type="primary",
        )
    except Exception as e:
        st.caption(f"ZIP 失敗：{e}")

    cols = st.columns(2)
    for col, label, key in (
        (cols[0], "模型 · 全賽日", "model"),
        (cols[1], "AI 馬評 · 全賽日", "ai"),
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
        "優先挑選模型與 AI 都有支持的場次；"
        "每匹馬評述不超過40字；"
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


st.title("廣告輸出")
st.caption(
    "每次預測快照成功後，系統把**全賽日**推介寫入兩張海報（公司原圖風格）："
    "模型／AI 馬評。每場最多 **4 匹**（只顯示馬號＋馬名，不含勝率）；"
    "藍／米色隨機；下次生成會**覆蓋**同一檔名；PNG ≤2MB。"
)

out_root = default_output_dir()
paths = latest_paths(out_root)
st.info(f"輸出：`{paths['model'].name}` / `{paths['ai'].name}` @ `{out_root}`")
try:
    from ad_poster import font_status, _max_bytes

    fs = font_status()
    if fs.get("ok"):
        st.caption(f"字型：`{fs.get('path')}` · 上限 {_max_bytes() // 1024} KB／張 · 色調藍／米隨機")
    else:
        st.error(f"CJK 字型不可用：{fs.get('error') or '未找到字型檔'}")
except Exception as e:
    st.warning(f"字型檢查失敗：{e}")

tab_browse, tab_regen = st.tabs(["瀏覽輸出", "手動重產"])

with tab_browse:
    _render_outputs(out_root, key_prefix="browse")
    copy_data = load_copy_json(out_root)
    st.divider()
    _render_social_copy(out_root, copy_data)

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
