"""全站輕量主題：登入／管理／用戶（賽日）。"""
from __future__ import annotations


def inject_login_css():
    import streamlit as st
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');
html, body, [class*="css"] { font-family: "Noto Sans TC", "Segoe UI", sans-serif; }
[data-testid="stSidebar"] { display: none; }
.block-container { max-width: 420px; padding-top: 4rem !important; }
.auth-wrap { text-align: center; margin-bottom: 0.5rem; }
.auth-brand {
  display: inline-block; font-weight: 800; letter-spacing: 0.12em;
  color: #0b6e4f; font-size: 0.85rem; margin: 0;
}
.auth-card h1 {
  font-size: 1.55rem; font-weight: 800; margin: 0.35rem 0 0.4rem;
  color: #14241c;
}
.auth-sub { color: #5a6b62; font-size: 0.92rem; margin: 0 0 1rem; }
</style>
        """,
        unsafe_allow_html=True,
    )


def inject_admin_css():
    import streamlit as st
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');
html, body, [class*="css"] { font-family: "Noto Sans TC", "Segoe UI", sans-serif; }
:root {
  --j18-ink: #14241c;
  --j18-muted: #5a6b62;
  --j18-line: #d7e3dc;
  --j18-accent: #0b6e4f;
  --j18-bg: #f4f7f5;
}
.block-container { padding-top: 1.25rem !important; }
[data-testid="stSidebar"] {
  background: #f7faf8;
  border-right: 1px solid var(--j18-line);
}
div[data-testid="stSidebarNav"] span {
  font-weight: 500;
}
.j18-page-head {
  border-bottom: 1px solid var(--j18-line);
  padding-bottom: 0.65rem;
  margin-bottom: 1rem;
}
.j18-page-head h1 {
  font-size: 1.45rem; font-weight: 800; margin: 0;
  color: var(--j18-ink); letter-spacing: 0.01em;
}
.j18-page-head p {
  margin: 0.25rem 0 0; color: var(--j18-muted); font-size: 0.9rem;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def inject_user_css():
    import streamlit as st
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');
html, body, [class*="css"] { font-family: "Noto Sans TC", "Segoe UI", sans-serif; }
.block-container {
  padding-top: 0.85rem !important;
  padding-bottom: 3.5rem !important;
  max-width: 440px !important;
}
[data-testid="stSidebar"] { min-width: 0; }
:root {
  --ink: #14241c;
  --muted: #5a6b62;
  --line: #d5e0d9;
  --card: #f7faf8;
  --accent: #0b6e4f;
  --accent-soft: #e3f2eb;
  --warn: #c45c26;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = ""):
    import streamlit as st
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f'<div class="j18-page-head"><h1>{title}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )
