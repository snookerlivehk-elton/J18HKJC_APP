"""全站輕量主題：登入／管理／用戶（賽日）。"""
from __future__ import annotations


def inject_home_screen_icons():
    """
    iOS／Android「加至主畫面」需要穩定的 apple-touch-icon URL。
    Streamlit page_icon 多為暫存 blob，主畫面抓不到 → 只顯示灰底字母。
    圖檔放 static/，並在 .streamlit/config.toml 開啟 enableStaticServing。
    """
    import streamlit.components.v1 as components

    icon = "/app/static/apple-touch-icon.png"
    manifest = "/app/static/manifest.webmanifest"
    components.html(
        f"""
<script>
(function () {{
  const doc = window.parent.document;
  const iconHref = {icon!r};
  const manifestHref = {manifest!r};

  function upsertLink(rel, href, sizes) {{
    let sel = 'link[rel="' + rel + '"]';
    if (sizes) sel += '[sizes="' + sizes + '"]';
    let el = doc.querySelector(sel);
    if (!el) {{
      el = doc.createElement('link');
      el.rel = rel;
      if (sizes) el.sizes = sizes;
      doc.head.appendChild(el);
    }}
    el.href = href;
  }}

  function upsertMeta(name, content) {{
    let el = doc.querySelector('meta[name="' + name + '"]');
    if (!el) {{
      el = doc.createElement('meta');
      el.name = name;
      doc.head.appendChild(el);
    }}
    el.content = content;
  }}

  upsertLink('apple-touch-icon', iconHref, '180x180');
  upsertLink('apple-touch-icon', iconHref, null);
  upsertLink('icon', iconHref, '180x180');
  upsertLink('manifest', manifestHref, null);
  upsertMeta('apple-mobile-web-app-capable', 'yes');
  upsertMeta('mobile-web-app-capable', 'yes');
  upsertMeta('apple-mobile-web-app-title', 'J18AI Plus+');
  upsertMeta('application-name', 'J18AI Plus+');
}})();
</script>
        """,
        height=0,
    )


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
.auth-wrap img { border-radius: 18px; box-shadow: 0 8px 24px rgba(0,0,0,0.18); }
.auth-brand {
  display: inline-block; font-weight: 800; letter-spacing: 0.04em;
  color: #c62828; font-size: 0.85rem; margin: 0;
}
.auth-card h1 {
  font-size: 1.55rem; font-weight: 800; margin: 0.55rem 0 0.4rem;
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
.block-container { padding-top: 0.85rem !important; max-width: 1200px; }

/* 側欄僅作參數面板（頁面導航已改頂部） */
[data-testid="stSidebar"] {
  background-color: var(--secondary-background-color) !important;
  border-right: 1px solid rgba(128, 128, 128, 0.25);
}
[data-testid="stSidebar"] > div:first-child {
  background-color: var(--secondary-background-color) !important;
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

/* —— 平板／手機 —— */
@media (max-width: 992px) {
  .block-container {
    padding-left: 0.85rem !important;
    padding-right: 0.85rem !important;
    padding-top: 0.5rem !important;
    max-width: 100% !important;
  }
  .j18-page-head h1 { font-size: 1.2rem; }
  .j18-page-head p { font-size: 0.85rem; }

  /* 收合側欄：徹底不佔位、不透出選單字 */
  [data-testid="stSidebar"][aria-expanded="false"] {
    display: none !important;
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    transform: translateX(-110%) !important;
    visibility: hidden !important;
    pointer-events: none !important;
  }
  /* 展開側欄：固定抽屜、實底蓋住主內容 */
  [data-testid="stSidebar"][aria-expanded="true"] {
    position: fixed !important;
    left: 0 !important;
    top: 0 !important;
    bottom: 0 !important;
    z-index: 1000002 !important;
    width: min(88vw, 320px) !important;
    min-width: 0 !important;
    max-width: 88vw !important;
    transform: none !important;
    visibility: visible !important;
    background-color: var(--secondary-background-color) !important;
    box-shadow: 8px 0 28px rgba(0, 0, 0, 0.35);
  }
  [data-testid="stSidebar"][aria-expanded="true"] > div:first-child {
    background-color: var(--secondary-background-color) !important;
    height: 100% !important;
    overflow-y: auto !important;
    -webkit-overflow-scrolling: touch;
  }

  section.main, [data-testid="stAppViewContainer"] > .main {
    margin-left: 0 !important;
    width: 100% !important;
  }

  /* 頂部導航可橫滑 */
  [data-testid="stHeadingWithActionElements"],
  header[data-testid="stHeader"],
  [data-testid="stToolbar"] {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch;
  }

  /* 多欄直向堆疊 */
  div[data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
  }
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    min-width: min(100%, 260px) !important;
    flex: 1 1 100% !important;
  }

  [data-testid="stDataFrame"],
  [data-testid="stTable"] {
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
    padding-left: 0.65rem !important;
    padding-right: 0.65rem !important;
  }
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    min-width: 100% !important;
    width: 100% !important;
    flex: 1 1 100% !important;
  }
  section.main .stMarkdown h1 { font-size: 1.25rem !important; }
  section.main .stMarkdown h2 { font-size: 1.08rem !important; }
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
  [data-testid="stSidebar"][aria-expanded="false"] {
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
  }
  [data-testid="stSidebar"][aria-expanded="true"] {
    position: fixed !important;
    z-index: 1000002 !important;
    width: min(88vw, 320px) !important;
    background-color: var(--secondary-background-color) !important;
    box-shadow: 8px 0 28px rgba(0, 0, 0, 0.35);
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
