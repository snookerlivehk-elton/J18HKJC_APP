"""馬匹歷史戰績表 — 廣告類：產三幅圖並走 Ad API 下游包。"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from helper_form_client import load_helper_form_for_display, resolve_latest_meeting
from helper_form_package import publish_helper_form_package, public_payload
from helper_form_poster import split_race_layout
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header(
    "賽前歷史戰績",
    "廣告類資產：核對最新賽馬日後產三幅戰績圖，寫入 helper-form 包供下游機械人 "
    "`GET /v1/helper-form/latest` 拉取（見 HELPER_FORM_AI_USAGE.md）。",
)

latest = resolve_latest_meeting()
col_a, col_b = st.columns(2)
with col_a:
    if latest.get("ok"):
        n = int(latest.get("n_races") or 0)
        layout = split_race_layout(n) if n else []
        layout_txt = "+".join(str(x) for x in layout) if layout else "—"
        st.info(
            f"系統最新賽馬日：**{latest.get('racing_date')}** "
            f"{latest.get('course') or ''}（{n} 場 → 排版 `{layout_txt}`）"
        )
    else:
        st.warning(f"未能讀取系統最新賽馬日：{latest.get('error') or 'unknown'}")

with col_b:
    override_date = st.text_input(
        "覆寫核對日期（可選，YYYY-MM-DD）",
        value="",
        help="留空則使用系統最新賽馬日。",
    ).strip()
    override_course = st.selectbox("場地", ["（跟系統）", "ST", "HV"], index=0)
    force = st.checkbox("強制重產（即使已有 ready）", value=False)
    notify = st.checkbox("ready 後 webhook 通知機械人", value=True)

st.caption(
    "排位更新後 meeting_tick 會自動 `helper_form_ensure`；"
    "亦可手動產出。下游：`GET /v1/helper-form/latest`。"
)

c1, c2, c3 = st.columns(3)
do_preview = c1.button("只核對日期", use_container_width=True)
do_render = c2.button("產出並發佈戰績包", type="primary", use_container_width=True)
allow_stale = c3.checkbox("日期不符仍預覽 API（除錯）", value=False)

expect_date = override_date or None
expect_course = None if override_course.startswith("（") else override_course

if do_preview:
    with st.spinner("抓取 Helper API 並核對日期…"):
        loaded = load_helper_form_for_display(
            expected_date=expect_date,
            expected_course=expect_course,
            require_course=bool(expect_course),
        )
    guard = loaded.get("guard") or {}
    if loaded.get("ok"):
        st.success(guard.get("message") or "日期核對通過")
    else:
        st.error(guard.get("message") or "日期核對失敗")
    st.json(guard)
    n = int(loaded.get("n_races") or 0)
    if loaded.get("races"):
        st.write(f"場次數：{n}；預排版：`{'+'.join(map(str, split_race_layout(n)))}`")
        for r in loaded["races"]:
            st.text(f"R{r.get('race_num')}: {r.get('title')}")

if do_render:
    with st.spinner("產三幅圖並寫入 helper-form 包…"):
        result = publish_helper_form_package(
            racing_date=expect_date,
            course=expect_course,
            notify=notify,
            force=force,
        )
    if not result.get("ok"):
        st.error(result.get("error") or "出圖／發佈失敗")
        st.json(result)
    else:
        pkg = result.get("package") or {}
        if result.get("skipped"):
            st.info(f"已有 ready 包，略過重產：`{result.get('id')}`")
        else:
            st.success(f"已發佈：`{result.get('id')}` status={result.get('status')}")
        st.json(public_payload(pkg))
        if result.get("webhook"):
            st.write("webhook：", result.get("webhook"))
        for im in (pkg.get("assets") or {}).get("images") or []:
            path = Path(im.get("path") or "")
            nums = ",".join(str(x) for x in (im.get("race_nums") or []))
            caption = f"圖 {im.get('index')}｜第 {nums} 場"
            if path.is_file():
                st.image(str(path), caption=caption, use_container_width=True)
                st.download_button(
                    f"下載圖 {im.get('index')}",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime="image/png",
                    key=f"dl_hf_{im.get('index')}",
                )

if allow_stale:
    st.caption("除錯模式僅影響上方「只核對日期」解讀；正式發佈仍要求日期匹配。")
