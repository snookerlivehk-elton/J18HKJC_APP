"""馬匹歷史戰績表 — Helper API 出圖（對齊參考原圖、全中文）。"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from helper_form_client import load_helper_form_for_display, resolve_latest_meeting
from helper_form_poster import default_output_dir, generate_helper_form_png
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header(
    "馬匹歷史戰績表",
    "由 Helper API 產出接近參考原圖的中文戰績長圖；必須核對最新賽馬日後才出圖。",
)

latest = resolve_latest_meeting()
col_a, col_b = st.columns(2)
with col_a:
    if latest.get("ok"):
        st.info(
            f"系統最新賽馬日：**{latest.get('racing_date')}** "
            f"{latest.get('course') or ''}（{latest.get('n_races') or 0} 場）"
        )
    else:
        st.warning(f"未能讀取系統最新賽馬日：{latest.get('error') or 'unknown'}")

with col_b:
    override_date = st.text_input(
        "覆寫核對日期（可選，YYYY-MM-DD）",
        value="",
        help="留空則使用系統最新賽馬日；僅供對照／補救。",
    ).strip()
    override_course = st.selectbox("場地核對", ["（不強制）", "ST", "HV"], index=0)
    require_course = override_course in ("ST", "HV")

st.caption(
    "API：`/calculate/v1/tool/helper?all=1`（無日期參數）→ "
    "解析每場 `title` 日期 → 必須等於最新賽馬日才渲染。"
)

c1, c2, c3 = st.columns(3)
do_preview = c1.button("只核對日期（不打圖）", use_container_width=True)
do_render = c2.button("核對並產出戰績圖", type="primary", use_container_width=True)
allow_stale = c3.checkbox("日期不符仍出圖（除錯）", value=False)

expect_date = override_date or None
expect_course = override_course if require_course else None

if do_preview:
    with st.spinner("抓取 Helper API 並核對日期…"):
        loaded = load_helper_form_for_display(
            expected_date=expect_date,
            expected_course=expect_course,
            require_course=require_course,
        )
    guard = loaded.get("guard") or {}
    if loaded.get("ok"):
        st.success(guard.get("message") or "日期核對通過")
    else:
        st.error(guard.get("message") or "日期核對失敗")
    st.json(guard)
    if loaded.get("races"):
        st.write(f"場次數：{loaded.get('n_races')}")
        st.write("各場標題：")
        for r in loaded["races"]:
            st.text(f"R{r.get('race_num')}: {r.get('title')}")

if do_render:
    out_dir = default_output_dir()
    out_path = out_dir / "helper_form.png"
    with st.spinner("抓取 API、核對日期、渲染中文戰績表…"):
        result = generate_helper_form_png(
            out_path=out_path,
            expected_date=expect_date,
            expected_course=expect_course,
            require_course=require_course,
            render_even_if_stale=allow_stale,
        )
    if not result.get("ok"):
        st.error(result.get("error") or "出圖失敗")
        st.json(result.get("guard") or {})
    else:
        if result.get("stale_rendered"):
            st.warning("日期核對未通過，但已依除錯選項出圖。")
        else:
            st.success(
                f"已產出：{result.get('out_path')} "
                f"（{result.get('n_races')} 場，{result.get('size')}）"
            )
        path = Path(result["out_path"])
        if path.is_file():
            st.image(str(path), caption="馬匹歷史戰績表（中文）", use_container_width=True)
            st.download_button(
                "下載 PNG",
                data=path.read_bytes(),
                file_name="helper_form.png",
                mime="image/png",
            )
