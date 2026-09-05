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
  color: var(--text-color, #14241c);
}
.auth-sub { color: var(--text-color, #5a6b62); opacity: 0.75; font-size: 0.92rem; margin: 0 0 1rem; }
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
.block-container { padding-top: 1.25rem !important; max-width: 1200px; }

/* 跟隨 Streamlit 主題，勿寫死淺色側欄（Dark 會白底淺字） */
[data-testid="stSidebar"] {
  background-color: var(--secondary-background-color) !important;
  border-right: 1px solid rgba(128, 128, 128, 0.25);
}
[data-testid="stSidebar"] > div:first-child {
  background-color: var(--secondary-background-color) !important;
}
[data-testid="stSidebar"] * {
  color: inherit;
}
div[data-testid="stSidebarNav"] span,
div[data-testid="stSidebarNav"] a,
div[data-testid="stSidebarNav"] p {
  color: var(--text-color) !important;
  font-weight: 500;
}
div[data-testid="stSidebarNav"] [data-testid="stSidebarNavLink"]:hover,
div[data-testid="stSidebarNav"] [aria-selected="true"] {
  background-color: rgba(128, 128, 128, 0.18) !important;
}
/* 導航觸控高度 */
div[data-testid="stSidebarNav"] [data-testid="stSidebarNavLink"] {
  min-height: 2.25rem;
  padding-top: 0.4rem !important;
  padding-bottom: 0.4rem !important;
}

.j18-page-head {
  border-bottom: 1px solid rgba(128, 128, 128, 0.28);
  padding-bottom: 0.65rem;
  margin-bottom: 1rem;
}
.j18-page-head h1 {
  font-size: 1.45rem; font-weight: 800; margin: 0;
  color: var(--text-color); letter-spacing: 0.01em;
}
.j18-page-head p {
  margin: 0.25rem 0 0; color: var(--text-color); opacity: 0.72; font-size: 0.9rem;
}

/* —— 平板／手機：側欄當抽屜、主區可讀、表格可橫滑 —— */
@media (max-width: 992px) {
  .block-container {
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    padding-top: 0.75rem !important;
    max-width: 100% !important;
  }
  .j18-page-head h1 { font-size: 1.25rem; }
  .j18-page-head p { font-size: 0.85rem; }

  /* 側欄：實底＋高 z，避免半透明疊字 */
  [data-testid="stSidebar"] {
    z-index: 1000001 !important;
    background-color: var(--secondary-background-color) !important;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.28);
  }
  [data-testid="stSidebar"] > div:first-child {
    background-color: var(--secondary-background-color) !important;
    height: 100%;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  /* 多欄改直向堆疊，避免擠成重疊 */
  div[data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
    gap: 0.35rem 0 !important;
  }
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    min-width: min(100%, 280px) !important;
    flex: 1 1 100% !important;
  }

  /* 表格／dataframe 橫向捲動 */
  [data-testid="stDataFrame"],
  [data-testid="stTable"],
  div[data-testid="stElementContainer"]:has(table) {
    max-width: 100%;
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch;
  }
  .stButton > button,
  .stDownloadButton > button {
    min-height: 2.6rem;
  }
}

@media (max-width: 640px) {
  .block-container {
    padding-left: 0.7rem !important;
    padding-right: 0.7rem !important;
  }
  /* 極窄：欄一律全寬 */
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    min-width: 100% !important;
    width: 100% !important;
    flex: 1 1 100% !important;
  }
  /* 側欄導航更緊湊（長選單可捲） */
  div[data-testid="stSidebarNav"] span {
    font-size: 0.92rem !important;
  }
  section.main .stMarkdown h1 { font-size: 1.3rem !important; }
  section.main .stMarkdown h2 { font-size: 1.1rem !important; }
  section.main .stMarkdown h3 { font-size: 1rem !important; }
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
[data-testid="stSidebar"] {
  min-width: 0;
  background-color: var(--secondary-background-color) !important;
}
[data-testid="stSidebar"] > div:first-child {
  background-color: var(--secondary-background-color) !important;
}
:root {
  --accent: #0b6e4f;
  --warn: #c45c26;
}
@media (max-width: 640px) {
  .block-container {
    padding-left: 0.75rem !important;
    padding-right: 0.75rem !important;
    max-width: 100% !important;
  }
  [data-testid="stSidebar"] {
    z-index: 1000001 !important;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.28);
  }
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
