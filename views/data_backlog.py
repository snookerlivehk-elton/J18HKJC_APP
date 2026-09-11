"""
數據遺留清單（已併入數據營運中心）

保留此頁作導流，避免舊書籤失效。
"""
from __future__ import annotations

import streamlit as st

from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header("數據遺留清單", "已併入「數據營運中心」")

st.info(
    "多日遺留佇列、入列／處理到期項、單日略過／重開／一鍵遺留鏈"
    "已合併至 **數據營運中心**。"
)
st.page_link("views/ops_center.py", label="前往數據營運中心", icon="🎛️")
st.page_link("views/meeting_ops.py", label="前往賽日作戰室（單日）", icon="⚔️")
