"""
J18AI Plus+ 入口：登入關卡 + 依角色導航。
用戶：賽日速覽 + 命中率榜；管理員見全部管理頁。

公開嵌入（無需登入；勿用 Streamlit 保留參數 embed=）：
  /?view=raceday  → 電腦版賽日速覽（j18.hk/pc 右手邊 iframe）
  /?view=raceday_pc → 開發用：整頁 pc.j18.hk 風格賽日速覽（不取代上者）
  相容：/?j18=raceday 、/?page=raceday
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import streamlit as st

from app_version import get_version, get_version_display
from auth_utils import (
    ROLE_ADMIN,
    is_logged_in,
    current_role,
    render_login_page,
    render_account_bar,
)
from ui_theme import inject_admin_css, inject_home_screen_icons, render_main_nav

_ROOT = Path(__file__).resolve().parent
_LOGO = _ROOT / "assets" / "j18ai_plus_logo.png"
_APP_VER = get_version_display()

st.set_page_config(
    page_title=f"J18AI Plus+ {_APP_VER}",
    page_icon=str(_LOGO) if _LOGO.is_file() else "🏇",
    layout="wide",
    # auto：有參數頁時側欄仍可開；參數已改主區 expander，不依賴側欄
    initial_sidebar_state="auto",
)

_PUBLIC_RACEDAY_VALUES = frozenset({"raceday", "raceday_embed", "1", "true", "yes"})
_PUBLIC_RACEDAY_PC_VALUES = frozenset({"raceday_pc", "raceday-pc"})


def _is_raceday_public_embed() -> bool:
    """
    偵測公開賽日速覽嵌入。
    注意：不可用 query `embed=`——那是 Streamlit 官方保留參數（會被吃掉）。
    """
    candidates = []
    try:
        for key in ("view", "j18", "page", "raceday"):
            candidates.append(st.query_params.get(key, ""))
            try:
                candidates.extend(st.query_params.get_all(key) or [])
            except Exception:
                pass
    except Exception:
        pass
    try:
        url = getattr(st.context, "url", None) or ""
        if url:
            qs = parse_qs(urlparse(str(url)).query)
            for key in ("view", "j18", "page", "raceday"):
                candidates.extend(qs.get(key) or [])
    except Exception:
        pass

    for raw in candidates:
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else ""
        if str(raw).strip().lower() in _PUBLIC_RACEDAY_VALUES:
            return True
    return False


def _query_flag_in(values: frozenset) -> bool:
    candidates = []
    try:
        for key in ("view", "j18", "page"):
            candidates.append(st.query_params.get(key, ""))
            try:
                candidates.extend(st.query_params.get_all(key) or [])
            except Exception:
                pass
    except Exception:
        pass
    try:
        url = getattr(st.context, "url", None) or ""
        if url:
            qs = parse_qs(urlparse(str(url)).query)
            for key in ("view", "j18", "page"):
                candidates.extend(qs.get(key) or [])
    except Exception:
        pass
    for raw in candidates:
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else ""
        if str(raw).strip().lower() in values:
            return True
    return False


def _is_raceday_pc_preview() -> bool:
    """獨立 PC 風格開發頁（不走原有 embed）。"""
    return _query_flag_in(_PUBLIC_RACEDAY_PC_VALUES)


if _is_raceday_pc_preview():
    import streamlit.components.v1 as components

    _pc_html = (_ROOT / "static" / "raceday_pc.html").read_text(encoding="utf-8")
    _pc_html = _pc_html.replace("__APP_VERSION__", get_version())
    st.markdown(
        """
<style>
#MainMenu, header, footer,
[data-testid="stToolbar"], [data-testid="stHeader"], [data-testid="stSidebar"],
section[data-testid="stSidebar"] { display: none !important; }
.block-container { padding: 0 !important; max-width: 100% !important; }
iframe { border: 0 !important; }
</style>
""",
        unsafe_allow_html=True,
    )
    components.html(_pc_html, height=1100, scrolling=True)
    st.stop()

if _is_raceday_public_embed():
    # 無需登入：專為 https://j18.hk/pc 右手邊嵌入
    from views.raceday_embed import render_raceday_embed

    render_raceday_embed()
    st.stop()

inject_home_screen_icons()

if _LOGO.is_file():
    st.logo(str(_LOGO), size="large")

if not is_logged_in():
    render_login_page()
    st.stop()

inject_admin_css()

role = current_role()
render_account_bar()

home = st.Page("views/home.py", title="系統主頁", default=(role == ROLE_ADMIN))
ops_center = st.Page("views/ops_center.py", title="數據營運中心")
meeting_ops = st.Page("views/meeting_ops.py", title="賽日作戰室")
data_control = st.Page("views/data_control.py", title="資料控制中心（舊）")
data_backlog = st.Page("views/data_backlog.py", title="數據遺留清單（舊）")
ad_output = st.Page("views/ad_output.py", title="廣告輸出")
whitelist = st.Page("views/whitelist.py", title="白名單")
raceday = st.Page(
    "views/raceday.py",
    title="賽日速覽",
    default=(role != ROLE_ADMIN),
)
inference = st.Page("views/inference.py", title="融合預測")
calibration = st.Page("views/calibration.py", title="因子命中率")
hit_stats = st.Page("views/hit_stats.py", title="命中率榜")
form_ai = st.Page("views/form_ai.py", title="賽績 AI 評價")
jockey = st.Page("views/jockey_factor.py", title="騎師因子")
trainer = st.Page("views/trainer_factor.py", title="練馬師因子")
synergy = st.Page("views/synergy_factor.py", title="騎練合作")
draw = st.Page("views/draw_factor.py", title="檔位因子")
hj = st.Page("views/horse_jockey_factor.py", title="人馬合作")
form_nlp = st.Page("views/form_nlp_factor.py", title="近績與 NLP")
pace = st.Page("views/pace_factor.py", title="步速形勢")
speed = st.Page("views/speed_factor.py", title="速度指數")
sg = st.Page("views/speed_guide.py", title="官方速勢能量")

# 隱藏預設導航（側欄／頂欄都會在手機變成透明抽屜疊字）
# 改由主畫面「功能選單」st.page_link 切頁
if role == ROLE_ADMIN:
    sections = {
        "系統": [home, whitelist],
        "營運": [ops_center, meeting_ops, ad_output, data_control, data_backlog],
        "預測": [raceday, inference, calibration, hit_stats, form_ai],
        "因子": [jockey, trainer, synergy, draw, hj, form_nlp, pace, speed, sg],
    }
    nav = st.navigation(sections, position="hidden")
    render_main_nav(sections)
else:
    user_sections = {
        "瀏覽": [raceday, hit_stats],
    }
    nav = st.navigation([raceday, hit_stats], position="hidden")
    render_main_nav(user_sections)

nav.run()
