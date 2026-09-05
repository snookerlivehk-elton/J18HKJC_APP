"""
J18 量化系統入口：登入關卡 + 依角色導航。
用戶僅見賽日速覽；管理員見全部管理頁。
"""
from __future__ import annotations

import streamlit as st

from auth_utils import (
    ROLE_ADMIN,
    is_logged_in,
    current_role,
    render_login_page,
    render_sidebar_account,
)

st.set_page_config(
    page_title="J18 量化系統",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not is_logged_in():
    render_login_page()
    st.stop()

role = current_role()
render_sidebar_account()

# 依角色組裝導航（顯式 Page，不使用 pages/ 自動發現）
home = st.Page("views/home.py", title="系統主頁", default=(role == ROLE_ADMIN))
data_control = st.Page("views/data_control.py", title="資料控制中心")
meeting_ops = st.Page("views/meeting_ops.py", title="賽日作戰室")
whitelist = st.Page("views/whitelist.py", title="白名單")
raceday = st.Page(
    "views/raceday.py",
    title="賽日速覽",
    default=(role != ROLE_ADMIN),
)
inference = st.Page("views/inference.py", title="融合預測")
calibration = st.Page("views/calibration.py", title="因子命中率")
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

if role == ROLE_ADMIN:
    nav = st.navigation(
        {
            "系統": [home, whitelist],
            "營運": [data_control, meeting_ops],
            "預測": [raceday, inference, calibration, form_ai],
            "因子": [jockey, trainer, synergy, draw, hj, form_nlp, pace, speed, sg],
        }
    )
else:
    # 用戶：僅賽日速覽
    nav = st.navigation([raceday])

nav.run()
