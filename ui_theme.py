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
.auth-card h1 {
  font-size: 1.55rem; font-weight: 800; margin: 0.55rem 0 0.15rem;
  color: var(--text-color, #14241c);
}
.auth-ver {
  margin: 0 0 0.55rem; font-size: 0.82rem; font-weight: 700;
  letter-spacing: 0.04em; opacity: 0.55;
  color: var(--text-color, #5a6b62);
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
.j18-app-ver {
  text-align: right;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  opacity: 0.55;
  color: var(--text-color);
  padding-top: 0.15rem;
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


def inject_raceday_embed_css():
    """
    j18.hk/pc 右手邊嵌入用：隱藏 Streamlit 殼、深色寛版、三欄出馬卡。
    左欄固定 450px，本頁吃剩餘寛度（約 ≥640px）。
    """
    import streamlit as st

    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');
html, body, [class*="css"], .stApp {
  font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif !important;
  background: #1e1e1e !important;
  color: #f2f2f2 !important;
}
/* 藏殼：頂欄／選單／footer／側欄 */
#MainMenu, header, footer,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stHeader"],
[data-testid="stSidebar"],
section[data-testid="stSidebar"] {
  display: none !important;
  visibility: hidden !important;
  width: 0 !important;
  min-width: 0 !important;
}
.stApp > header { display: none !important; }
.block-container {
  padding: 1rem 1.25rem 2rem !important;
  max-width: 1280px !important;
}
:root {
  --accent: #f0c14b;
  --good: #3ecf8e;
  --bg-card: #262626;
  --line: rgba(255,255,255,0.10);
}
.rd-hero {
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.75rem;
  margin-bottom: 0.65rem;
}
.rd-hero .mark {
  font-size: 0.72rem; font-weight: 800; letter-spacing: 0.14em;
  color: var(--accent); text-transform: uppercase;
}
.rd-hero h1 {
  font-size: 1.55rem; font-weight: 800; margin: 0.15rem 0 0;
  letter-spacing: 0.02em; color: #f2f2f2;
}
.rd-hero p { margin: 0.25rem 0 0; opacity: 0.62; font-size: 0.86rem; color: #f2f2f2; }
.rd-panel {
  display: block;
  margin: 0.5rem 0 0.75rem;
}
.rd-meta, .rd-fuse, .rd-side {
  background: var(--bg-card) !important;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0.85rem 0.95rem;
  color: #f2f2f2 !important;
}
.rd-meta { margin-bottom: 0; }
.rd-tips {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0 0 0.85rem;
}
@media (max-width: 980px) {
  .rd-tips { grid-template-columns: 1fr; }
}
.rd-fuse {
  border-color: rgba(62,207,142,0.35) !important;
}
.rd-meta .title { font-weight: 800; font-size: 1.08rem; margin-bottom: 0.45rem; }
.rd-meta .grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 0.28rem 0.7rem; font-size: 0.84rem; opacity: 0.88;
}
.rd-meta .grid b { opacity: 1; font-weight: 700; }
.rd-fuse .col-title, .rd-side .col-title {
  font-size: 0.72rem; font-weight: 800; letter-spacing: 0.06em;
  opacity: 0.7; margin-bottom: 0.35rem; text-transform: uppercase;
}
.rd-fuse .note { font-size: 0.68rem; opacity: 0.65; margin-top: 0.45rem; }
.rd-pick-row {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 0.4rem; padding: 0.28rem 0; font-size: 0.9rem;
  border-bottom: 1px dashed rgba(255,255,255,0.08);
}
.rd-pick-row:last-child { border-bottom: none; }
.rd-pick-row .tag {
  display: inline-block; font-size: 0.65rem; font-weight: 800;
  color: var(--good); background: rgba(62,207,142,0.16);
  border-radius: 999px; padding: 0.05rem 0.4rem; margin-right: 0.3rem;
}
.rd-pick-row .tag.pos {
  color: var(--accent); background: rgba(240,193,75,0.16);
}
.rd-pick-row .nm { font-weight: 700; }
.rd-pick-row .right { font-weight: 800; color: var(--good); }
.rd-pick-empty { font-size: 0.82rem; opacity: 0.55; padding: 0.25rem 0; }
.horse-card {
  background: var(--bg-card) !important;
  color: #f2f2f2 !important;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0.75rem 0.9rem;
  margin-bottom: 0.55rem;
  display: grid;
  /* 左資料｜中雷達｜右 AI 評價（右欄寛度仍保持三區橫向） */
  grid-template-columns: minmax(180px, 1fr) 132px minmax(200px, 1.4fr);
  gap: 0.45rem 0.7rem;
  align-items: center;
}
.horse-card.top1 { border-color: var(--accent); box-shadow: inset 0 0 0 1px rgba(240,193,75,0.25); }
.horse-card.pick { border-color: rgba(62,207,142,0.55); }
.hc-info {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.35rem 0.75rem;
  align-items: start;
}
.hc-rank {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 1.7rem; height: 1.7rem;
  font-size: 0.72rem; font-weight: 800;
  color: #d8ffe9; background: #0b6e4f;
  border-radius: 999px; padding: 0 0.4rem; margin-bottom: 0.2rem;
}
.hc-name { font-size: 1.12rem; font-weight: 800; line-height: 1.25; }
.hc-no { opacity: 0.7; font-weight: 700; font-size: 0.95rem; margin-right: 0.3rem; }
.hc-prob { text-align: right; flex-shrink: 0; padding-top: 0.1rem; }
.hc-prob .pct { font-size: 1.4rem; font-weight: 800; color: var(--good); line-height: 1; }
.hc-prob .lbl { font-size: 0.66rem; opacity: 0.65; margin-top: 0.18rem; }
.hc-sub {
  margin-top: 0.22rem; font-size: 0.76rem; opacity: 0.72; line-height: 1.45;
}
.hc-radar {
  display: flex; align-items: center; justify-content: center;
  width: 132px; height: 124px;
}
.hc-radar svg { width: 128px; height: 120px; display: block; }
.hc-radar .radar-empty { font-size: 0.72rem; opacity: 0.55; text-align: center; }
.hc-ai { min-width: 0; }
.hc-ai .ai-head {
  font-size: 0.84rem; font-weight: 800; line-height: 1.35; margin-bottom: 0.25rem;
}
.hc-ai .ai-head .meta { font-weight: 600; opacity: 0.62; font-size: 0.74rem; }
.hc-ai .ai-body {
  font-size: 0.78rem; opacity: 0.9; line-height: 1.45;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical;
  overflow: hidden;
}
.hc-ai .ai-empty { font-size: 0.78rem; opacity: 0.55; }
@media (max-width: 720px) {
  .horse-card {
    grid-template-columns: minmax(0, 1fr) 120px;
    grid-template-areas:
      "info radar"
      "ai ai";
  }
  .hc-info { grid-area: info; }
  .hc-radar { grid-area: radar; width: 120px; height: 110px; }
  .hc-radar svg { width: 112px; height: 110px; }
  .hc-ai { grid-area: ai; }
}
@media (max-width: 520px) {
  .horse-card {
    grid-template-columns: 1fr;
    grid-template-areas:
      "info"
      "radar"
      "ai";
  }
  .hc-radar { width: 100%; justify-content: flex-start; }
}
div[data-testid="stPills"] button {
  min-width: 2.5rem !important; min-height: 2.5rem !important;
  border-radius: 999px !important; font-weight: 800 !important;
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
.j18-app-ver {
  text-align: right;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  opacity: 0.55;
  color: var(--text-color);
  padding-top: 0.15rem;
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
