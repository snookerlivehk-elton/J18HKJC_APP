"""廣告輸出 — 全賽日綜合推介海報（固定檔名覆蓋）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

from ad_llm_copy import (
    COMMENT_MAX_CHARS,
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
from views.ad_archive_panel import render_ad_archive_panel
from ad_poster import (
    PRIMARY_TRACK_LABEL,
    default_output_dir,
    latest_paths,
    load_copy_json,
    make_preview_jpeg,
    zip_batch_bytes,
)
from factor_calibration import FactorCalibration


def _show_remote_push(remote: Optional[Dict[str, Any]]) -> None:
    """顯示生產 Ad API ingest 結果（下游 Grok Bot 只睇生產 API）。"""
    if not remote:
        return
    if remote.get("ok"):
        st.success(
            f"已推送生產 Ad API：`{remote.get('id') or 'ready'}`"
            + (f" → {remote.get('url')}" if remote.get("url") else "")
        )
        return
    reason = remote.get("error") or remote.get("reason") or "unknown"
    if remote.get("skipped"):
        st.warning(f"未推送生產 API（略過）：{reason}")
    else:
        st.error(f"推送生產 API 失敗：{reason}")


def _sync_publish_to_prod(out_root: Path, *, notify: bool = False) -> Dict[str, Any]:
    """fused + social／facebook 齊備時 rebuild + POST /v1/ads/ingest。"""
    try:
        from ad_package import publish_ad_package_after_outputs

        return publish_ad_package_after_outputs(output_root=out_root, notify=notify)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _render_outputs(out_root: Path, *, key_prefix: str = "browse") -> None:
    """預覽＋下載（ZIP／單張）。可在瀏覽頁或重產成功後同頁使用。"""
    paths = latest_paths(out_root)
    if not paths["fused"].is_file():
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
        if fb:
            st.caption(f"檔案大小：{PRIMARY_TRACK_LABEL} {int(fb) // 1024} KB")

    # 只提供 ZIP 下載。推送生產改喺「生成 AI」同一掣完成，唔使換頁／撳兩次。
    try:
        st.download_button(
            f"⬇️ 下載 ZIP（{PRIMARY_TRACK_LABEL} PNG + copy）",
            data=zip_batch_bytes(out_root),
            file_name="ad_output_latest.zip",
            mime="application/zip",
            key=f"zip_{key_prefix}",
            type="primary",
        )
    except Exception as e:
        st.caption(f"ZIP 失敗：{e}")

    st.markdown(f"**{PRIMARY_TRACK_LABEL}推介 · 全賽日（社交主視覺）**")
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
        st.warning(f"尚無{PRIMARY_TRACK_LABEL}海報（請重新產生快照／廣告）")

    if copy:
        with st.expander("宣傳文案", expanded=False):
            st.markdown(f"**{PRIMARY_TRACK_LABEL}推介**")
            st.write(copy.get("fused_copy") or "")


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
            f"請先重新生成廣告輸出（需含{PRIMARY_TRACK_LABEL}推介）。"
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
        help="預設高互動型：像香港 FB／IG 貼文，易讚易留言；文筆固定港式，避免國語翻譯腔。",
    )
    st.caption(TONE_PRESETS[normalize_tone(tone)]["hint"])

    default_prompt = (
        "寫成香港人日常 FB／IG 貼文口吻；"
        "標題帶提問或叫人留言；"
        f"優先挑選{PRIMARY_TRACK_LABEL}推介名單內、模型與 AI 都有支持的場次；"
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
        if st.button("生成 AI 精選評述並推送生產", type="primary", key="ad_social_generate", disabled=disabled, help="一次完成：寫文案 → 重建 ready 包 → POST /v1/ads/ingest 去生產 API"):
            with st.spinner("AI 正在挑選精選場次與撰寫文案…"):
                try:
                    social_data = writer.generate_social_copy(
                        copy_data,
                        custom_prompt=custom_prompt,
                        tone=tone,
                    )
                    save_social_copy(output_root, social_data)
                    # 歸檔＋重建廣告包 → status=ready 寫入共用 DB，供 GET /v1/ads/latest
                    meeting = (copy_data or {}).get("meeting") or {}
                    d = str(meeting.get("racing_date") or "")[:10]
                    c = str(meeting.get("course") or "").upper()
                    if d and c:
                        try:
                            from ad_copy_jobs import write_archive_version

                            social_data = dict(social_data)
                            social_data.setdefault(
                                "meeting",
                                {
                                    "batch_id": meeting.get("batch_id") or "",
                                    "racing_date": d,
                                    "course": c,
                                    "kind": "pre_race_social",
                                },
                            )
                            write_archive_version(output_root, d, c, "social", social_data)
                            save_social_copy(output_root, social_data)
                        except Exception as arch_exc:
                            st.caption(f"歸檔略過：{arch_exc}")
                    try:
                        from ad_package import publish_ad_package_after_outputs

                        pkg_out = publish_ad_package_after_outputs(
                            output_root=output_root, notify=True
                        )
                        if pkg_out.get("ok"):
                            st.caption(
                                f"廣告包 `{pkg_out.get('id')}` → **{pkg_out.get('status')}**（已 dual-write DB）"
                            )
                            _show_remote_push(pkg_out.get("remote_push") or {})
                        elif pkg_out.get("error"):
                            st.caption(f"廣告包重建：{pkg_out.get('error')}")
                            _show_remote_push(pkg_out.get("remote_push") or {})
                    except Exception as pkg_exc:
                        st.caption(f"廣告包重建略過：{pkg_exc}")
                    st.session_state["ad_social_result"] = social_data
                    src_note = social_data.get("source") or "llm"
                    if str(src_note).startswith("fallback"):
                        st.warning(
                            "LLM 暫時未能完成，已用推介自動補齊精選（系統提示只顯示喺呢度，"
                            "唔會寫入 facebook_copy／生產 API）。"
                        )
                    else:
                        st.success(f"已生成 AI 精選評述（{tone_label(tone)}）並推送生產 API")
                except Exception as e:
                    st.session_state["ad_social_result"] = {"error": str(e)}
                    st.error(f"生成失敗：{e}")
    with c2:
        p = social_copy_path(output_root)
        if p.is_file():
            st.caption(f"已保存：`{p.name}`")

    # 補推／重試（已有 social 時先用；正常唔使撳）
    with st.expander("進階：只重試推送生產 API", expanded=False):
        st.caption("正常撳上面「生成 AI…並推送生產」已夠。呢度只係 ingest 失敗時補推。")
        if st.button("重試推送生產 API", key=f"ad_social_retry_push"):
            with st.spinner("推送 /v1/ads/ingest …"):
                push_out = _sync_publish_to_prod(output_root, notify=True)
            if push_out.get("ok"):
                st.caption(f"`{push_out.get('id')}` → {push_out.get('status')}")
            _show_remote_push(
                push_out.get("remote_push")
                or ({"ok": False, "error": push_out.get("error")} if push_out.get("error") else {})
            )

    social_data = st.session_state.get("ad_social_result") or social_data
    if not social_data:
        st.info(
            "一次流程：撳「生成 AI 精選評述並推送生產」→ 寫文案 → 自動 ingest 生產 API；"
            "唔使換頁再撳推送。文筆港式，自動加 hashtags／文末聲明。"
        )
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
    "每次預測快照成功後，系統把**全賽日**推介寫入海報（公司原圖風格）："
    f"**{PRIMARY_TRACK_LABEL}推介**（社交主視覺）。"
    "每場最多 **4 匹**（只顯示馬號＋馬名，不含勝率）；"
    "日馬啡色／夜馬藍色；下次生成會**覆蓋**同一檔名；PNG ≤2MB。"
)

out_root = default_output_dir()
# 跨服務：若本機無海報，試從共用 DB hydrate（CORN 產、Streamlit 讀）
try:
    from ad_store import hydrate_package_to_disk, list_ad_package_ids_db, load_latest_ad_package_db

    if not (out_root / "fused.png").is_file():
        latest = load_latest_ad_package_db(ready_only=False)
        if latest and latest.get("id"):
            hydrate_package_to_disk(str(latest["id"]), out_root)
        else:
            ids = list_ad_package_ids_db()
            if ids:
                hydrate_package_to_disk(ids[0], out_root)
except Exception:
    pass
paths = latest_paths(out_root)
st.info(f"輸出：`{paths['fused'].name}` @ `{out_root}`")
try:
    from ad_poster import font_status, _max_bytes

    fs = font_status()
    if fs.get("ok"):
        st.caption(f"字型：`{fs.get('path')}` · 上限 {_max_bytes() // 1024} KB／張 · 日馬啡色／夜馬藍色（依賽日 session）")
    else:
        st.error(f"CJK 字型不可用：{fs.get('error') or '未找到字型檔'}")
except Exception as e:
    st.warning(f"字型檢查失敗：{e}")

tab_browse, tab_regen = st.tabs(["瀏覽輸出", "手動重產"])

with tab_browse:
    st.info(
        "日常用法：海報齊 → 下面撳「生成 AI 精選評述並推送生產」一次搞掂。"
        "「手動重產」完成後亦會留喺該頁預覽，唔使嚟回切換。"
    )
    _render_outputs(out_root, key_prefix="browse")
    copy_data = load_copy_json(out_root)
    st.divider()
    _render_social_copy(out_root, copy_data)

    st.divider()
    render_ad_archive_panel(output_root=out_root, key_prefix="ad_out_arch", show_pre_race=True, show_post_race=True)

with tab_regen:
    st.markdown(
        f"選擇預測快照批次，依鎖分重產全賽日**{PRIMARY_TRACK_LABEL}推介**海報與宣傳文案"
        f"（覆蓋 `{paths['fused'].name}`／`copy.json`）。"
    )
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
        st.caption("重產改走後台任務（關閉本頁不中斷）；進度見下方。")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("後台重產廣告輸出", type="primary", key="ad_regen_bg"):
                from meeting_pipeline import MeetingPipeline

                pipe = MeetingPipeline()
                # 從 batch_id 解析日期場地（若可）
                row = bdf[bdf["batch_id"].astype(str) == str(bid)]
                d = str(row.iloc[0]["racing_date"])[:10] if not row.empty else ""
                c = str(row.iloc[0]["course"]) if not row.empty else ""
                r = pipe.run_action(
                    d, c, "start_ad_regen_background", batch_id=str(bid)
                )
                st.session_state["ad_regen_job_id"] = r.get("job_id")
                if r.get("ok"):
                    st.success(r.get("message") or f"job `{r.get('job_id')}`")
                else:
                    st.error(r.get("error") or r)
                st.rerun()
        with c2:
            if st.button("重新整理進度", key="ad_regen_refresh"):
                st.rerun()

        from ops_jobs import get_job

        jid = st.session_state.get("ad_regen_job_id")
        st_job = get_job(job_id=jid, job_type="ad_regen")
        job = (st_job or {}).get("job")
        if job:
            js = str(job.get("status") or "")
            prog = job.get("progress_json") or {}
            st.write(f"**後台任務** `{job.get('job_id')}` — **{js}**")
            st.caption(str(job.get("detail") or ""))
            if isinstance(prog, dict) and prog:
                st.json(prog)
            if js in ("ok", "ok_with_errors"):
                st.success("重產完成（後台已自動跑 AI 文案＋推送生產）。下面可直接預覽，唔使換頁。")
                st.session_state["ad_last_result"] = {
                    "ok": True,
                    "races_written": (prog or {}).get("result", {}).get("races_written"),
                }
            elif js == "failed":
                st.error("後台失敗，請看 detail／logs。")
            elif js == "running":
                st.info("進行中——可關頁，稍後回來按「重新整理進度」。")

        last: Optional[Dict[str, Any]] = st.session_state.get("ad_last_result")
        if last and (last.get("ok") or last.get("races_written")):
            st.markdown("#### 立即下載／預覽（同頁，唔使轉「瀏覽輸出」）")
            _render_outputs(out_root, key_prefix="after_regen")
            st.divider()
            copy_after = load_copy_json(out_root)
            _render_social_copy(out_root, copy_after or {})
        elif last and last.get("error"):
            st.error(last.get("error"))
