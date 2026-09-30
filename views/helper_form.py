"""馬匹歷史戰績表 — Helper API 出圖（對齊參考原圖、全中文、每賽日最多三幅）。"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from helper_form_client import load_helper_form_for_display, resolve_latest_meeting
from helper_form_poster import (
    default_output_dir,
    generate_helper_form_parts,
    split_race_layout,
)
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header(
    "馬匹歷史戰績表",
    "Helper API 中文戰績圖：核對最新賽馬日後，依總場數拆成最多三幅（每幅 3–4 場）。logo 水印預設關閉。",
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
        help="留空則使用系統最新賽馬日；僅供對照／補救。",
    ).strip()
    override_course = st.selectbox("場地核對", ["（不強制）", "ST", "HV"], index=0)
    require_course = override_course in ("ST", "HV")

st.caption(
    "API：`/calculate/v1/tool/helper?all=1`（無日期參數）→ "
    "解析每場 `title` 日期 → 必須等於最新賽馬日才渲染；"
    "9–12 場固定三幅（例 10→4+3+3、11→4+4+3）。"
)

c1, c2, c3 = st.columns(3)
do_preview = c1.button("只核對日期（不打圖）", use_container_width=True)
do_render = c2.button("核對並產出三幅戰績圖", type="primary", use_container_width=True)
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
    n = int(loaded.get("n_races") or 0)
    if loaded.get("races"):
        st.write(f"場次數：{n}；預排版：`{'+'.join(map(str, split_race_layout(n)))}`")
        st.write("各場標題：")
        for r in loaded["races"]:
            st.text(f"R{r.get('race_num')}: {r.get('title')}")

if do_render:
    out_dir = default_output_dir()
    with st.spinner("抓取 API、核對日期、拆幅渲染中文戰績表…"):
        result = generate_helper_form_parts(
            out_dir=out_dir,
            expected_date=expect_date,
            expected_course=expect_course,
            require_course=require_course,
            render_even_if_stale=allow_stale,
            apply_logo=False,
        )
    if not result.get("ok"):
        st.error(result.get("error") or "出圖失敗")
        st.json(result.get("guard") or {})
    else:
        if result.get("stale_rendered"):
            st.warning("日期核對未通過，但已依除錯選項出圖。")
        layout = result.get("layout") or []
        st.success(
            f"已產出 {len(result.get('parts') or [])} 幅"
            f"（共 {result.get('n_races')} 場，排版 `{'+'.join(map(str, layout))}`）"
            f" → `{out_dir}`"
        )
        st.json(
            {
                "racing_date": result.get("racing_date"),
                "course": result.get("course"),
                "layout": layout,
                "logo": result.get("logo"),
                "manifest_path": result.get("manifest_path"),
            }
        )
        for part in result.get("parts") or []:
            path = Path(part.get("path") or "")
            nums = ",".join(str(x) for x in (part.get("race_nums") or []))
            caption = f"圖 {part.get('index')}｜第 {nums} 場（{part.get('n_races')} 場）"
            if path.is_file():
                st.image(str(path), caption=caption, use_container_width=True)
                st.download_button(
                    f"下載圖 {part.get('index')}",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime="image/png",
                    key=f"dl_helper_form_{part.get('index')}",
                )
