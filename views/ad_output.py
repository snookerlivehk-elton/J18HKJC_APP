"""廣告輸出 — 賽前海報／文案、賽後歸檔、重產（精簡工作流）。"""
from __future__ import annotations

from datetime import date
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
from ad_poster import (
    PRIMARY_TRACK_LABEL,
    default_output_dir,
    font_status,
    latest_paths,
    load_copy_json,
    make_preview_jpeg,
    zip_batch_bytes,
)
from factor_calibration import FactorCalibration
from ui_theme import inject_admin_css, page_header
from views.ad_archive_panel import render_ad_archive_panel

inject_admin_css()
page_header(
    "廣告輸出",
    f"賽前：海報（{PRIMARY_TRACK_LABEL}）＋社交文案 · "
    "賽後：命中評估＋宣傳文案 · 重產：由快照重畫海報",
)


def _show_remote_push(remote: Optional[Dict[str, Any]]) -> None:
    if not remote:
        st.error("未見 remote_push 結果——請確認已設 `AD_API_BASE_URL` + `AD_API_KEY`。")
        return
    if remote.get("ok"):
        st.success(
            f"已推送生產 Ad API：`{remote.get('id') or 'ready'}`"
            + (f" → {remote.get('url')}" if remote.get("url") else "")
        )
        return
    st.error(
        f"推送生產失敗／略過：{remote.get('error') or remote.get('reason') or 'unknown'}"
    )


def _sync_publish_to_prod(out_root: Path, *, notify: bool = False) -> Dict[str, Any]:
    try:
        from ad_package import publish_ad_package_after_outputs

        return publish_ad_package_after_outputs(output_root=out_root, notify=notify)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _hydrate_if_needed(out_root: Path) -> None:
    if (out_root / "fused.png").is_file():
        return
    try:
        from ad_store import (
            hydrate_package_to_disk,
            list_ad_package_ids_db,
            load_latest_ad_package_db,
        )

        latest = load_latest_ad_package_db(ready_only=False)
        if latest and latest.get("id"):
            hydrate_package_to_disk(str(latest["id"]), out_root)
            return
        ids = list_ad_package_ids_db()
        if ids:
            hydrate_package_to_disk(ids[0], out_root)
    except Exception:
        pass


def _status_strip(out_root: Path) -> None:
    paths = latest_paths(out_root)
    has_poster = paths["fused"].is_file()
    social = load_social_copy(out_root) or {}
    has_social = bool(social and not social.get("error") and social.get("post_text"))
    copy = load_copy_json(out_root) or {}
    meeting = copy.get("meeting") or {}

    c1, c2, c3 = st.columns(3)
    c1.metric("海報", "就緒" if has_poster else "未有")
    c2.metric("賽前文案", "就緒" if has_social else "未有")
    label = (
        f"{meeting.get('racing_date', '—')} {meeting.get('course', '')}".strip() or "—"
    )
    c3.metric("目前賽日", label)
    if meeting.get("batch_id"):
        st.caption(f"batch `{meeting.get('batch_id')}` · `{out_root}`")


def _render_poster(out_root: Path, *, key_prefix: str) -> None:
    paths = latest_paths(out_root)
    p_fused = paths["fused"]
    if not p_fused.is_file():
        st.info("尚無海報。請先完成預測快照，或到「重產海報」由批次重畫。")
        return

    copy = load_copy_json(out_root)
    meeting = (copy or {}).get("meeting") or {}
    if meeting:
        st.write(
            f"**{meeting.get('racing_date', '')} {meeting.get('course', '')}** · "
            f"{meeting.get('n_races', '?')} 場"
        )

    dl1, dl2 = st.columns(2)
    with dl1:
        try:
            st.download_button(
                f"⬇️ 下載 ZIP（{PRIMARY_TRACK_LABEL} + copy）",
                data=zip_batch_bytes(out_root),
                file_name="ad_output_latest.zip",
                mime="application/zip",
                key=f"zip_{key_prefix}",
                type="primary",
                use_container_width=True,
            )
        except Exception as e:
            st.caption(f"ZIP 失敗：{e}")
    with dl2:
        with open(p_fused, "rb") as f:
            st.download_button(
                f"⬇️ 只下載 {p_fused.name}",
                data=f.read(),
                file_name=p_fused.name,
                mime="image/png",
                key=f"dl_{key_prefix}_fused",
                use_container_width=True,
            )

    try:
        st.image(
            make_preview_jpeg(p_fused),
            caption=f"{p_fused.name} · {p_fused.stat().st_size // 1024} KB",
            use_container_width=True,
        )
    except Exception as e:
        st.warning(f"預覽失敗：{e}")

    fused_copy = (copy or {}).get("fused_copy") or (copy or {}).get("copy")
    if fused_copy:
        with st.expander("海報內文案", expanded=False):
            st.write(fused_copy)


def _render_social_copy(
    out_root: Path, copy_data: Dict[str, Any], *, key_prefix: str
) -> None:
    def _k(name: str) -> str:
        return f"{name}_{key_prefix}"

    writer = AdSocialCopywriter()
    n_cand = count_candidate_races(copy_data or {})

    if not writer.is_ready():
        st.warning("未偵測到 OPENAI_API_KEY，無法生成 AI 文案。")
    elif not copy_data:
        st.info("尚未有 copy.json。請先有海報／快照。")
    elif n_cand <= 0:
        st.info(f"copy.json 未含{PRIMARY_TRACK_LABEL}推介場次，無法生成精選文案。")
    else:
        st.caption(f"LLM `{writer.nlp.model}` · 可用場次 {n_cand}")

    tone_options = list(TONE_PRESETS.keys())
    current = normalize_tone(st.session_state.get(_k("tone")) or DEFAULT_TONE)
    tone = st.radio(
        "語氣",
        options=tone_options,
        index=tone_options.index(current),
        format_func=lambda k: TONE_PRESETS[k]["label"],
        horizontal=True,
        key=_k("tone"),
    )
    st.caption(TONE_PRESETS[normalize_tone(tone)].get("hint") or "")

    default_prompt = (
        "寫成香港人日常 FB／IG「數據研究」貼文口吻；"
        "標題帶提問或叫人留言討論模型觀察；"
        f"優先挑選{PRIMARY_TRACK_LABEL}分析名單內、模型與 AI 都有支持的場次；"
        f"每匹馬評述不超過{COMMENT_MAX_CHARS}字；"
        "近績跑法要用「近績／上仗」開首，唔好用「本場」寫到似今晚已經跑完；"
        "三場 comment 收尾句要唔同；"
        "只講公開數據／統計傾向／模型推演，禁止心水、貼士、投注誘導；"
        "唔好用國語翻譯腔。"
    )
    with st.expander("進階提示詞", expanded=False):
        st.text_area(
            "LLM 提示詞",
            value=st.session_state.get(_k("prompt")) or default_prompt,
            height=100,
            key=_k("prompt"),
            label_visibility="collapsed",
        )
        st.caption("文末合規聲明由系統自動附加：")
        st.code(post_footer_text(), language=None)

    custom_prompt = st.session_state.get(_k("prompt")) or default_prompt
    social_data = load_social_copy(out_root)

    can_gen = writer.is_ready() and n_cand > 0
    if st.button(
        "生成賽前文案並推送生產",
        type="primary",
        key=_k("generate"),
        disabled=not can_gen,
        use_container_width=True,
    ):
        with st.spinner("AI 撰寫中…"):
            try:
                social_data = writer.generate_social_copy(
                    copy_data,
                    custom_prompt=custom_prompt,
                    tone=tone,
                )
                save_social_copy(out_root, social_data)
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
                        write_archive_version(out_root, d, c, "social", social_data)
                        save_social_copy(out_root, social_data)
                    except Exception as arch_exc:
                        st.caption(f"歸檔略過：{arch_exc}")
                try:
                    pkg_out = _sync_publish_to_prod(out_root, notify=True)
                    remote = pkg_out.get("remote_push") or {}
                    if pkg_out.get("ok") and remote.get("ok"):
                        st.success(f"已生成（{tone_label(tone)}）並覆寫生產 latest")
                    elif pkg_out.get("ok"):
                        st.warning("文案已生成，但生產推送未成功——可用下方重試。")
                    else:
                        st.warning(pkg_out.get("error") or "廣告包重建失敗")
                    if remote or pkg_out.get("error"):
                        _show_remote_push(
                            remote or {"ok": False, "error": pkg_out.get("error")}
                        )
                except Exception as pkg_exc:
                    st.caption(f"推送略過：{pkg_exc}")
                st.session_state[_k("result")] = social_data
                if str(social_data.get("source") or "").startswith("fallback"):
                    st.warning("LLM 未完成，已用推介自動補齊。")
            except Exception as e:
                st.session_state[_k("result")] = {"error": str(e)}
                st.error(f"生成失敗：{e}")

    with st.expander("只重試推送生產 API", expanded=False):
        if st.button("重試推送", key=_k("retry_push")):
            with st.spinner("推送中…"):
                push_out = _sync_publish_to_prod(out_root, notify=True)
            _show_remote_push(
                push_out.get("remote_push")
                or (
                    {"ok": False, "error": push_out.get("error")}
                    if push_out.get("error")
                    else push_out
                )
            )

    social_data = st.session_state.get(_k("result")) or social_data
    if not social_data:
        st.caption("日常流程：海報就緒 → 撳一次生成文案並推送。")
        return
    if social_data.get("error"):
        st.error(str(social_data.get("error")))
        return

    st.markdown(f"#### {social_data.get('title') or '（無標題）'}")
    if social_data.get("subtitle"):
        st.caption(social_data["subtitle"])
    st.caption(
        f"語氣：{social_data.get('tone_label') or tone_label(social_data.get('tone'))}"
    )

    featured = list(social_data.get("featured") or [])
    if featured:
        top_n = social_data.get("featured_fused_top_n")
        if top_n:
            st.caption(f"精選馬限制：綜合／名單頭 {top_n} 名內")
        cols = st.columns(min(3, len(featured)))
        for col, item in zip(cols, featured):
            with col:
                st.markdown(
                    f"**第{item.get('race_no') or '?'}場 · "
                    f"{item.get('horse_no', '?')} {item.get('horse_name', '')}**"
                )
                st.write(item.get("comment") or "")
                reason = item.get("pick_reason") if isinstance(item.get("pick_reason"), dict) else {}
                label = str((reason or {}).get("label") or "").strip()
                if not label and item.get("basis"):
                    label = str(item.get("basis"))
                if label:
                    st.caption(f"揀因：{label}")
                angle = item.get("angle") or (reason or {}).get("angle")
                if angle and (not label or f"角度:{angle}" not in label):
                    st.caption(f"觀察角度：{angle}")

    hashtags = list(social_data.get("hashtags") or [])
    if hashtags:
        st.code(" ".join(hashtags), language=None)

    post_text = str(social_data.get("post_text") or "").strip()
    if not post_text:
        post_text = format_social_post_text(social_data)
    st.text_area(
        "Facebook / IG 貼文",
        value=post_text,
        height=240,
        key=_k("post_preview"),
    )
    p = social_copy_path(out_root)
    if p.is_file():
        st.caption(f"已保存 `{p.name}`")


def _render_regen(out_root: Path) -> None:
    fused_name = latest_paths(out_root)["fused"].name
    st.caption(
        f"揀快照批次重畫全賽日{PRIMARY_TRACK_LABEL}海報（覆蓋 `{fused_name}`／copy.json）。"
        "完成後請返「今日輸出」預覽／寫文案。"
    )
    cal = FactorCalibration()
    try:
        bdf = cal.list_batches()
    except Exception as e:
        st.error(f"讀取快照批次失敗：{e}")
        return
    if bdf is None or bdf.empty:
        st.warning("尚無預測快照批次。")
        return

    opts = {
        f"{r.batch_id} · {str(r.racing_date)[:10]} {r.course} · rows={int(r.n_rows)}": str(
            r.batch_id
        )
        for r in bdf.itertuples()
    }
    blabel = st.selectbox("預測批次", list(opts.keys()), key="ad_regen_batch")
    bid = opts[blabel]

    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "開始後台重產", type="primary", key="ad_regen_bg", use_container_width=True
        ):
            from meeting_pipeline import MeetingPipeline

            pipe = MeetingPipeline()
            row = bdf[bdf["batch_id"].astype(str) == str(bid)]
            d = str(row.iloc[0]["racing_date"])[:10] if not row.empty else ""
            c = str(row.iloc[0]["course"]) if not row.empty else ""
            r = pipe.run_action(d, c, "start_ad_regen_background", batch_id=str(bid))
            st.session_state["ad_regen_job_id"] = r.get("job_id")
            if r.get("ok"):
                st.success(r.get("message") or f"已排隊 job `{r.get('job_id')}`")
            else:
                st.error(r.get("error") or r)
            st.rerun()
    with c2:
        if st.button("重新整理進度", key="ad_regen_refresh", use_container_width=True):
            st.rerun()

    from ops_jobs import get_job

    jid = st.session_state.get("ad_regen_job_id")
    st_job = get_job(job_id=jid, job_type="ad_regen")
    job = (st_job or {}).get("job")
    if not job:
        st.caption("尚未有進行中的重產任務。")
        return

    js = str(job.get("status") or "")
    prog = job.get("progress_json") or job.get("progress") or {}
    st.write(f"**任務** `{job.get('job_id')}` — **{js}**")
    if job.get("detail"):
        st.caption(str(job.get("detail")))
    if isinstance(prog, dict) and prog:
        with st.expander("進度細節", expanded=False):
            st.json(prog)

    if js in ("ok", "ok_with_errors"):
        st.success("重產完成。請切換到「今日輸出」查看海報／生成文案。")
        if st.button("前往今日輸出", key="ad_regen_goto_today"):
            st.session_state["ad_output_section"] = "今日輸出"
            st.rerun()
    elif js == "failed":
        st.error("後台失敗，請查看 detail／logs。")
    elif js == "running":
        st.info("進行中——可關頁，稍後回來按「重新整理進度」。")


out_root = default_output_dir()
_hydrate_if_needed(out_root)

try:
    fs = font_status()
    if not fs.get("ok"):
        st.error(f"CJK 字型不可用：{fs.get('error') or '未找到字型檔'}")
except Exception as e:
    st.warning(f"字型檢查失敗：{e}")

_status_strip(out_root)

section = st.radio(
    "工作區",
    ["今日輸出", "賽後管理", "重產海報"],
    horizontal=True,
    key="ad_output_section",
    label_visibility="collapsed",
)

st.divider()

if section == "今日輸出":
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("海報")
        _render_poster(out_root, key_prefix="today")
    with right:
        st.subheader("賽前文案")
        _render_social_copy(
            out_root, load_copy_json(out_root) or {}, key_prefix="today"
        )

elif section == "賽後管理":
    st.subheader("賽後命中／文案")
    st.caption(
        "SETTLED 後由 tick／賽果自動結算觸發產出；呢度用嚟翻查進度同人手重做。"
    )
    render_ad_archive_panel(
        output_root=out_root,
        key_prefix="ad_post",
        show_pre_race=False,
        show_post_race=True,
        default_racing_date=date.today().isoformat(),
        default_course="HV",
    )
    with st.expander("賽前歸檔（較少用）", expanded=False):
        render_ad_archive_panel(
            output_root=out_root,
            key_prefix="ad_pre",
            show_pre_race=True,
            show_post_race=False,
        )

else:
    st.subheader("重產海報")
    _render_regen(out_root)
