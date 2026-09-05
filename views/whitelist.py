"""白名單管理：email／通行碼 × admin｜user。"""
from __future__ import annotations

import streamlit as st

from auth_utils import (
    ROLE_ADMIN,
    ROLE_USER,
    TOKEN_EMAIL,
    TOKEN_PASSWORD,
    AuthStore,
    is_admin,
)
from ui_theme import inject_admin_css, page_header

inject_admin_css()
page_header("白名單", "管理可登入的 Email／通行碼與角色（僅管理員）")

if not is_admin():
    st.error("需要管理員權限")
    st.stop()

store = AuthStore()

st.subheader("新增")
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    new_token = st.text_input("Email 或通行碼", placeholder="user@example.com")
with c2:
    new_role = st.selectbox("角色", [ROLE_USER, ROLE_ADMIN], index=0)
with c3:
    new_type = st.selectbox(
        "類型",
        ["自動", TOKEN_EMAIL, TOKEN_PASSWORD],
        help="自動：含 @ 視為 email",
    )
new_label = st.text_input("備註（可選）", placeholder="例如：賽日訪客")

if st.button("加入白名單", type="primary"):
    ttype = None if new_type == "自動" else new_type
    r = store.add_entry(new_token, new_role, token_type=ttype, label=new_label)
    if r.get("ok"):
        st.success(r.get("message") or ("已更新" if r.get("updated") else "已新增"))
        st.rerun()
    else:
        st.error(r.get("error") or "寫入失敗")

st.divider()
st.subheader("現有名單")
df = store.list_entries(active_only=False)
if df.empty:
    st.info("尚無白名單。若設了 AUTH_BOOTSTRAP_ADMIN 且庫內無 admin，可用開機碼登入後在此新增。")
else:
    show = df.copy()
    show["狀態"] = show["is_active"].apply(
        lambda x: "啟用" if (x is True or x == 1 or str(x).lower() == "true") else "停用"
    )
    st.dataframe(
        show[["id", "token", "token_type", "role", "label", "狀態", "created_at"]],
        use_container_width=True,
        hide_index=True,
    )
    ids = show["id"].astype(int).tolist()
    pick = st.selectbox("選擇要操作的 id", ids)
    b1, b2, b3 = st.columns(3)
    if b1.button("停用", use_container_width=True):
        store.set_active(int(pick), False)
        st.rerun()
    if b2.button("重新啟用", use_container_width=True):
        store.set_active(int(pick), True)
        st.rerun()
    if b3.button("刪除", use_container_width=True):
        store.delete_entry(int(pick))
        st.success("已刪除")
        st.rerun()

st.caption("用戶角色登入後只能進入「賽日速覽」。管理員可進入全部管理頁。")
