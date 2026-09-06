"""全站輕量主題：登入／管理／用戶（賽日）。"""
from __future__ import annotations


def inject_home_screen_icons():
    """
    iOS／Android「加至主畫面」需要穩定的 apple-touch-icon URL。
    Streamlit page_icon 多為暫存 blob，主畫面抓不到 → 只顯示灰底字母。
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
  upsertMeta('description', 'J18 全港首創綜合賽馬系統｜專業分析 實時數據 一機在手 助你提高命中率');
}})();
</script>
        """,
        height=0,
    )


def inject_sidebar_solid_bg():
    """
    強制左側抽屜實心底色 + 遮罩（解決透明側欄與主內容疊字）。
    用 JS 讀主區背景色，不依賴可能為透明的 CSS 變數。
    """
    import streamlit.components.v1 as components

    components.html(
        """
<script>
(function () {
  const doc = window.parent.document;

  function appBg() {
    const root =
      doc.querySelector('[data-testid="stAppViewContainer"]') ||
      doc.querySelector('.stApp') ||
      doc.body;
    const bg = window.getComputedStyle(root).backgroundColor;
    if (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') {
      const isLight = (doc.documentElement.dataset.theme === 'light');
      return isLight ? '#ffffff' : '#0e1117';
    }
    return bg;
  }

  function paint(el, bg) {
    if (!el) return;
    el.style.setProperty('background', bg, 'important');
    el.style.setProperty('background-color', bg, 'important');
    el.style.setProperty('opacity', '1', 'important');
  }

  function ensureOverlay(show) {
    let ov = doc.getElementById('j18-sidebar-scrim');
    if (!ov) {
      ov = doc.createElement('div');
      ov.id = 'j18-sidebar-scrim';
      ov.style.cssText = [
        'position:fixed', 'inset:0', 'background:rgba(0,0,0,0.55)',
        'z-index:999990', 'display:none', 'pointer-events:auto'
      ].join(';');
      ov.addEventListener('click', function () {
        const btn = doc.querySelector('[data-testid="stSidebarCollapseButton"] button') ||
                    doc.querySelector('button[kind="header"]');
        // 點遮罩時嘗試點擊收合；找不到則只隱藏遮罩
        const collapse = doc.querySelector('[data-testid="stBaseButton-headerNoPadding"]');
        if (collapse) collapse.click();
      });
      doc.body.appendChild(ov);
    }
    ov.style.display = show ? 'block' : 'none';
  }

  function isSidebarOpen(sidebar) {
    if (!sidebar) return false;
    const aria = sidebar.getAttribute('aria-expanded');
    if (aria === 'false') return false;
    if (aria === 'true') return true;
    const rect = sidebar.getBoundingClientRect();
    return rect.width > 40 && rect.left > -20;
  }

  function fix() {
    const sidebar =
      doc.querySelector('section[data-testid="stSidebar"]') ||
      doc.querySelector('[data-testid="stSidebar"]');
    if (!sidebar) {
      ensureOverlay(false);
      return;
    }
    const bg = appBg();
    const open = isSidebarOpen(sidebar);
    paint(sidebar, bg);
    paint(sidebar.querySelector(':scope > div'), bg);
    paint(sidebar.querySelector('[data-testid="stSidebarContent"]'), bg);
    paint(sidebar.querySelector('[data-testid="stSidebarUserContent"]'), bg);
    paint(sidebar.querySelector('[data-testid="stVerticalBlock"]'), bg);
    sidebar.style.setProperty('z-index', '999995', 'important');
    sidebar.style.setProperty('box-shadow', open ? '8px 0 28px rgba(0,0,0,0.45)' : 'none', 'important');
    // 窄螢幕才加遮罩
    const narrow = window.parent.innerWidth <= 992;
    ensureOverlay(narrow && open);
  }

  fix();
  if (!window.__j18SidebarFix) {
    window.__j18SidebarFix = true;
    const mo = new MutationObserver(function () { fix(); });
    mo.observe(doc.body, { childList: true, subtree: true, attributes: true });
    window.parent.addEventListener('resize', fix);
    setInterval(fix, 600);
  }
})();
</script>
        """,
        height=0,
    )


def inject_login_css():
    """j18.hk 推廣彈窗風格：深藍底 + 金黃主標 + 白底會員卡。"""
    import streamlit as st
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');
html, body, [class*="css"] { font-family: "Noto Sans TC", "Microsoft YaHei", "Segoe UI", sans-serif; }

[data-testid="stSidebar"] { display: none; }
header[data-testid="stHeader"] { background: transparent !important; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > .main {
  background: linear-gradient(180deg, #1a2e5c 0%, #243a6e 48%, #1d2b62 100%) !important;
}
.block-container {
  max-width: 440px;
  padding-top: 1.6rem !important;
  padding-bottom: 2.4rem !important;
}

.j18-promo { text-align: center; color: #fff; margin: 0 0 0.85rem; }
.j18-badge {
  display: inline-block;
  background: linear-gradient(180deg, #ffa659 0%, #ff7a2e 100%);
  color: #fff; font-weight: 800; font-size: 1.05rem; letter-spacing: 0.04em;
  border-radius: 10px; padding: 0.35rem 0.7rem; margin-bottom: 0.55rem;
  box-shadow: 0 4px 14px rgba(255, 122, 46, 0.35);
}
.j18-kicker {
  margin: 0 0 0.25rem; font-size: 0.82rem; font-weight: 600;
  color: #c9d6f0; letter-spacing: 0.04em;
}
.j18-promo h1 {
  font-size: 1.72rem; font-weight: 800; margin: 0.15rem 0 0.45rem;
  color: #ffe48d; letter-spacing: 0.04em; line-height: 1.25;
}
.j18-tag {
  margin: 0 auto 0.7rem; max-width: 22rem;
  color: #e8eef8; opacity: 0.92; font-size: 0.86rem; line-height: 1.5;
}
.j18-pills {
  display: flex; flex-wrap: wrap; justify-content: center; gap: 0.35rem;
}
.j18-pill {
  background: rgba(255,255,255,0.12); color: #ffeeb8;
  border: 1px solid rgba(255,228,141,0.35);
  border-radius: 999px; padding: 0.18rem 0.55rem;
  font-size: 0.72rem; font-weight: 700;
}

.j18-cta { display: flex; flex-direction: column; gap: 0.45rem; margin: 0.2rem 0 1.05rem; }
.j18-btn {
  display: block; text-align: center; text-decoration: none !important;
  font-weight: 800; font-size: 0.95rem; border-radius: 10px;
  padding: 0.72rem 0.8rem; line-height: 1.2;
}
.j18-btn-gold {
  background: linear-gradient(180deg, #ffe48d 0%, #f6c960 100%);
  color: #1a2e5c !important; box-shadow: 0 4px 12px rgba(246, 201, 96, 0.35);
}
.j18-btn-wa {
  background: #24b679; color: #fff !important;
}
.j18-btn-cs {
  background: #304170; color: #9ec5ff !important;
  border: 1px solid #6caaf9;
}
.j18-social {
  text-align: center; margin-top: 0.15rem;
  font-size: 0.78rem; color: #9aa8c7;
}
.j18-social a { color: #c9d6f0 !important; text-decoration: none !important; font-weight: 600; }
.j18-social span { margin: 0 0.35rem; opacity: 0.6; }

.j18-member-head { text-align: center; margin: 0 0 0.35rem; }
.j18-member-head h2 {
  margin: 0; font-size: 1.02rem; font-weight: 800; color: #fff;
}
.j18-member-head p {
  margin: 0.2rem 0 0; font-size: 0.8rem; color: #c9d6f0; opacity: 0.9;
}

div[data-testid="stForm"] {
  background: #ffffff;
  border-radius: 12px;
  padding: 0.85rem 0.95rem 1.05rem;
  box-shadow: 0 10px 28px rgba(0,0,0,0.28);
}
div[data-testid="stForm"] label, div[data-testid="stForm"] p {
  color: #333 !important;
}
div[data-testid="stForm"] button,
div[data-testid="stForm"] [data-testid="stBaseButton-primary"],
div[data-testid="stForm"] button[kind="primary"],
[data-testid="stFormSubmitButton"] button,
.stFormSubmitButton button,
.stApp button,
section.main button,
[data-testid="stMain"] button {
  background: #3d5a8f !important;
  background-color: #3d5a8f !important;
  background-image: none !important;
  border: none !important;
  color: #fff !important;
  font-weight: 800 !important;
}
.stApp button p, .stApp button span, .stApp button div {
  color: #fff !important;
}
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

/* 硬編碼實底（勿只靠可能透明的 CSS 變數） */
section[data-testid="stSidebar"],
[data-testid="stSidebar"] {
  background-color: #0e1117 !important;
  background: #0e1117 !important;
  border-right: 1px solid rgba(128, 128, 128, 0.35);
}
section[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"] {
  background-color: #0e1117 !important;
  background: #0e1117 !important;
}
/* Light theme */
html[data-theme="light"] section[data-testid="stSidebar"],
html[data-theme="light"] [data-testid="stSidebar"],
html[data-theme="light"] section[data-testid="stSidebar"] > div,
html[data-theme="light"] [data-testid="stSidebar"] > div,
html[data-theme="light"] [data-testid="stSidebarContent"],
html[data-theme="light"] [data-testid="stSidebarUserContent"] {
  background-color: #ffffff !important;
  background: #ffffff !important;
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

.j18-nav-box {
  border: 1px solid rgba(128, 128, 128, 0.28);
  border-radius: 10px;
  padding: 0.35rem 0.6rem 0.55rem;
  margin-bottom: 0.75rem;
  background: var(--secondary-background-color, rgba(128,128,128,0.08));
}

@media (max-width: 992px) {
  .block-container {
    padding-left: 0.85rem !important;
    padding-right: 0.85rem !important;
    padding-top: 0.5rem !important;
    max-width: 100% !important;
  }
  .j18-page-head h1 { font-size: 1.2rem; }

  section[data-testid="stSidebar"][aria-expanded="true"],
  [data-testid="stSidebar"][aria-expanded="true"] {
    position: fixed !important;
    left: 0 !important;
    top: 0 !important;
    bottom: 0 !important;
    z-index: 999995 !important;
    width: min(88vw, 320px) !important;
    min-width: 0 !important;
    max-width: 88vw !important;
    transform: none !important;
    visibility: visible !important;
    background: #0e1117 !important;
    background-color: #0e1117 !important;
    box-shadow: 8px 0 28px rgba(0, 0, 0, 0.45) !important;
  }
  html[data-theme="light"] section[data-testid="stSidebar"][aria-expanded="true"],
  html[data-theme="light"] [data-testid="stSidebar"][aria-expanded="true"] {
    background: #ffffff !important;
    background-color: #ffffff !important;
  }

  section.main, [data-testid="stAppViewContainer"] > .main {
    margin-left: 0 !important;
    width: 100% !important;
  }

  div[data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    min-width: min(100%, 260px) !important;
    flex: 1 1 100% !important;
  }
  [data-testid="stDataFrame"], [data-testid="stTable"] {
    max-width: 100%;
    overflow-x: auto !important;
  }
  .stButton > button, .stDownloadButton > button { min-height: 2.6rem; }
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
}
</style>
        """,
        unsafe_allow_html=True,
    )
    inject_sidebar_solid_bg()


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
section[data-testid="stSidebar"],
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div {
  background: #0e1117 !important;
  background-color: #0e1117 !important;
}
html[data-theme="light"] section[data-testid="stSidebar"],
html[data-theme="light"] [data-testid="stSidebar"],
html[data-theme="light"] [data-testid="stSidebar"] > div {
  background: #ffffff !important;
  background-color: #ffffff !important;
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
}
</style>
        """,
        unsafe_allow_html=True,
    )
    inject_sidebar_solid_bg()


def render_main_nav(sections: dict):
    """
    主內容區選頁（搭配 st.navigation(position='hidden')）。
    不走左側透明抽屜，手機直屏可正常點選。
    """
    import streamlit as st

    with st.expander("📑 功能選單（點此切換頁面）", expanded=False):
        for section, pages in sections.items():
            st.caption(section)
            cols = st.columns(2)
            for i, page in enumerate(pages):
                with cols[i % 2]:
                    st.page_link(page, label=page.title, use_container_width=True)


def page_header(title: str, subtitle: str = ""):
    import streamlit as st
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f'<div class="j18-page-head"><h1>{title}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )
