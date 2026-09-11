"""
資料控制中心（已併入數據營運中心）

保留此頁作導流，避免舊書籤失效。
"""
from __future__ import annotations

import streamlit as st

from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header("資料控制中心", "已併入「數據營運中心」")

st.info(
    "整備度監控、遺留佇列與介入報告已合併至 **數據營運中心**。"
    "單日手動介入請用 **賽日作戰室**。"
)
st.page_link("views/ops_center.py", label="前往數據營運中心", icon="🎛️")
st.page_link("views/meeting_ops.py", label="前往賽日作戰室", icon="⚔️")
st.caption("舊快捷爬蟲仍可在作戰室各階段一鍵完成／備援重抓。")
