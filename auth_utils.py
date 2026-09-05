"""
登入關卡與白名單（email／通行碼 × admin｜user）。

Streamlit session 屬「擋君子」；正式密鑰放 DB／環境變數，勿寫死程式碼。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )

ROLE_ADMIN = "admin"
ROLE_USER = "user"
TOKEN_EMAIL = "email"
TOKEN_PASSWORD = "password"

SESSION_ROLE = "auth_role"
SESSION_IDENTITY = "auth_identity"
SESSION_VIA = "auth_via"  # whitelist | bootstrap


class AuthStore:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL_SYNC)
        self.ensure_table()

    def ensure_table(self):
        if USE_SQLITE:
            ddl = """
            CREATE TABLE IF NOT EXISTS auth_whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                token_type TEXT NOT NULL,
                role TEXT NOT NULL,
                label TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            ddl = """
            CREATE TABLE IF NOT EXISTS auth_whitelist (
                id SERIAL PRIMARY KEY,
                token VARCHAR(255) NOT NULL,
                token_type VARCHAR(20) NOT NULL,
                role VARCHAR(20) NOT NULL,
                label TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        with self.engine.begin() as conn:
            conn.execute(text(ddl))
            if not USE_SQLITE:
                try:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_whitelist_token_role "
                            "ON auth_whitelist (lower(token), role) WHERE is_active = TRUE"
                        )
                    )
                except Exception:
                    pass

    def list_entries(self, active_only: bool = False) -> pd.DataFrame:
        q = "SELECT * FROM auth_whitelist"
        if active_only:
            q += " WHERE is_active = TRUE" if not USE_SQLITE else " WHERE is_active = 1"
        q += " ORDER BY role, id"
        try:
            return pd.read_sql(text(q), self.engine)
        except Exception:
            return pd.DataFrame()

    def count_active_admins(self) -> int:
        q = text(
            "SELECT COUNT(*) AS n FROM auth_whitelist "
            "WHERE role = :r AND is_active = TRUE"
            if not USE_SQLITE
            else "SELECT COUNT(*) AS n FROM auth_whitelist WHERE role = :r AND is_active = 1"
        )
        try:
            row = pd.read_sql(q, self.engine, params={"r": ROLE_ADMIN}).iloc[0]
            return int(row["n"] or 0)
        except Exception:
            return 0

    def add_entry(
        self,
        token: str,
        role: str,
        token_type: str = None,
        label: str = "",
    ) -> Dict[str, Any]:
        token = (token or "").strip()
        if not token:
            return {"ok": False, "error": "帳號／通行碼不可空白"}
        if role not in (ROLE_ADMIN, ROLE_USER):
            return {"ok": False, "error": "角色無效"}
        if token_type not in (TOKEN_EMAIL, TOKEN_PASSWORD, None):
            return {"ok": False, "error": "類型無效"}
        if token_type is None:
            token_type = TOKEN_EMAIL if ("@" in token) else TOKEN_PASSWORD
        store_token = token.lower() if token_type == TOKEN_EMAIL else token
        active_val = True if not USE_SQLITE else 1

        try:
            with self.engine.begin() as conn:
                # 唯一鍵為 lower(token)+role：已存在則更新備註並重新啟用（勿再 INSERT 炸 traceback）
                existing = conn.execute(
                    text(
                        """
                        SELECT id, is_active FROM auth_whitelist
                        WHERE lower(token) = lower(:token) AND role = :role
                        ORDER BY id
                        LIMIT 1
                        """
                    ),
                    {"token": store_token, "role": role},
                ).fetchone()
                if existing:
                    eid = int(existing[0])
                    conn.execute(
                        text(
                            """
                            UPDATE auth_whitelist
                            SET token = :token,
                                token_type = :token_type,
                                label = :label,
                                is_active = :active
                            WHERE id = :id
                            """
                        ),
                        {
                            "token": store_token,
                            "token_type": token_type,
                            "label": label or "",
                            "active": active_val,
                            "id": eid,
                        },
                    )
                    return {
                        "ok": True,
                        "updated": True,
                        "message": f"此帳號／通行碼（{role}）已在白名單，已更新備註並啟用",
                    }

                conn.execute(
                    text(
                        """
                        INSERT INTO auth_whitelist (token, token_type, role, label, is_active)
                        VALUES (:token, :token_type, :role, :label, :active)
                        """
                    ),
                    {
                        "token": store_token,
                        "token_type": token_type,
                        "role": role,
                        "label": label or "",
                        "active": active_val,
                    },
                )
            return {"ok": True, "updated": False, "message": "已新增"}
        except IntegrityError:
            return {
                "ok": False,
                "error": "此帳號／通行碼與角色已存在於白名單（請到下方名單啟用或改備註）",
            }
        except Exception as e:
            return {"ok": False, "error": f"寫入失敗：{e}"}

    def set_active(self, entry_id: int, active: bool) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE auth_whitelist SET is_active = :a WHERE id = :id"
                ),
                {"a": active if not USE_SQLITE else (1 if active else 0), "id": entry_id},
            )

    def delete_entry(self, entry_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM auth_whitelist WHERE id = :id"), {"id": entry_id})

    def match(self, raw: str) -> Optional[Tuple[str, str, str]]:
        """
        回傳 (role, identity, via) 或 None。
        via = whitelist | bootstrap
        """
        raw = (raw or "").strip()
        if not raw:
            return None

        df = self.list_entries(active_only=True)
        if not df.empty:
            for _, row in df.iterrows():
                tok = str(row["token"])
                ttype = str(row["token_type"])
                role = str(row["role"])
                if ttype == TOKEN_EMAIL:
                    if raw.lower() == tok.lower():
                        return role, raw.lower(), "whitelist"
                else:
                    if raw == tok:
                        label = row.get("label") or "通行碼"
                        return role, str(label), "whitelist"

        # bootstrap：僅當庫內尚無 active admin
        boot = (os.getenv("AUTH_BOOTSTRAP_ADMIN") or "").strip()
        if boot and raw == boot and self.count_active_admins() == 0:
            return ROLE_ADMIN, "bootstrap", "bootstrap"
        return None


def is_logged_in() -> bool:
    import streamlit as st
    return st.session_state.get(SESSION_ROLE) in (ROLE_ADMIN, ROLE_USER)


def current_role() -> Optional[str]:
    import streamlit as st
    return st.session_state.get(SESSION_ROLE)


def is_admin() -> bool:
    return current_role() == ROLE_ADMIN


def logout():
    import streamlit as st
    for k in (SESSION_ROLE, SESSION_IDENTITY, SESSION_VIA):
        st.session_state.pop(k, None)


def try_login(raw: str) -> Tuple[bool, str]:
    import streamlit as st
    store = AuthStore()
    hit = store.match(raw)
    if not hit:
        return False, "不在白名單或通行碼錯誤"
    role, identity, via = hit
    st.session_state[SESSION_ROLE] = role
    st.session_state[SESSION_IDENTITY] = identity
    st.session_state[SESSION_VIA] = via
    if via == "bootstrap":
        return True, "已用開機通行碼進入（請立刻到「白名單」新增正式 admin）"
    return True, f"已登入（{role}）"


def render_login_page():
    """簡潔登入頁（未登入時由 ui_app 呼叫）。"""
    import streamlit as st
    from ui_theme import inject_login_css

    inject_login_css()
    st.markdown(
        """
        <div class="auth-wrap">
          <div class="auth-card">
            <h1>J18AI Plus+</h1>
            <p class="auth-sub">請輸入白名單內的 Email 或通行碼</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("login_form", clear_on_submit=False):
        token = st.text_input("Email 或通行碼", type="default", placeholder="you@example.com 或通行碼")
        submitted = st.form_submit_button("進入", type="primary", use_container_width=True)
        if submitted:
            ok, msg = try_login(token)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    st.link_button(
        "進入J18主頁",
        "https://j18.hk/",
        use_container_width=True,
    )


def render_account_bar():
    """主內容區帳號列（搭配頂部導航；避免手機側欄與頁面疊字）。"""
    import streamlit as st
    role = current_role()
    if not role:
        return
    identity = st.session_state.get(SESSION_IDENTITY, "")
    via = st.session_state.get(SESSION_VIA, "")
    left, right = st.columns([4, 1], vertical_alignment="center")
    with left:
        st.caption(f"{'管理' if role == ROLE_ADMIN else '用戶'}｜{identity}")
        if via == "bootstrap":
            st.warning("開機通行碼模式：請立刻到「白名單」新增正式 admin")
    with right:
        if st.button("登出", use_container_width=True):
            logout()
            st.rerun()


def render_sidebar_account():
    """相容舊呼叫：改為主區帳號列。"""
    render_account_bar()

