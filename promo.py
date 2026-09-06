"""
J18 公開站推廣入口（j18.hk 風格落地文案與連結）。

預設 WhatsApp／社群號碼與 j18.hk 前台公開相同，可用環境變數覆寫，勿改量化邏輯。
"""
from __future__ import annotations

import os
from typing import Dict
from urllib.parse import quote

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

J18_HOME_URL = (os.getenv("J18_HOME_URL") or "https://j18.hk/").strip()
J18_FACEBOOK_URL = (
    os.getenv("J18_FACEBOOK_URL") or "https://www.facebook.com/j18hk"
).strip()
J18_INSTAGRAM_URL = (
    os.getenv("J18_INSTAGRAM_URL") or "https://www.instagram.com/j18.hk/"
).strip()

# j18.hk 前台公開客服／註冊號（可被環境變數覆寫）
_WA_REGISTER = (os.getenv("J18_WHATSAPP_REGISTER") or "85264507318").strip()
_WA_SUPPORT = (os.getenv("J18_WHATSAPP_SUPPORT") or "85269614567").strip()
_WA_REGISTER_TEXT = os.getenv("J18_WHATSAPP_REGISTER_TEXT") or "想申請成為J18會員"

SLOGAN_BRAND = "J18 全港首創綜合賽馬系統"
SLOGAN_HERO = "市場走勢 一目了然"
SLOGAN_TAGLINE = "專業分析　實時數據　一機在手　助你提高命中率"
SLOGAN_PILLARS = ("專業分析", "實時數據", "一機在手", "提高命中率")
SLOGAN_PLUS = "J18AI Plus+ 會員入口"


def _digits(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def wa_me_url(phone: str, text: str = "") -> str:
    """組成 https://wa.me/<digits>?text=...（無號碼則回空字串）。"""
    digits = _digits(phone)
    if not digits:
        return ""
    url = f"https://wa.me/{digits}"
    msg = (text or "").strip()
    if msg:
        url += f"?text={quote(msg)}"
    return url


def j18_home_url() -> str:
    return J18_HOME_URL or "https://j18.hk/"


def whatsapp_register_url() -> str:
    return wa_me_url(_WA_REGISTER, _WA_REGISTER_TEXT)


def whatsapp_support_url() -> str:
    return wa_me_url(_WA_SUPPORT)


def promo_links() -> Dict[str, str]:
    return {
        "home": j18_home_url(),
        "whatsapp_register": whatsapp_register_url(),
        "whatsapp_support": whatsapp_support_url(),
        "facebook": J18_FACEBOOK_URL,
        "instagram": J18_INSTAGRAM_URL,
    }


def promo_hero_html() -> str:
    pillars = "".join(
        f'<span class="j18-pill">{p}</span>' for p in SLOGAN_PILLARS
    )
    return f"""
<div class="j18-promo">
  <div class="j18-badge">J18</div>
  <p class="j18-kicker">{SLOGAN_BRAND}</p>
  <h1>{SLOGAN_HERO}</h1>
  <p class="j18-tag">{SLOGAN_TAGLINE}</p>
  <div class="j18-pills">{pillars}</div>
</div>
"""


def promo_cta_html() -> str:
    links = promo_links()
    wa_reg = links["whatsapp_register"]
    wa_sup = links["whatsapp_support"]
    wa_reg_btn = (
        f'<a class="j18-btn j18-btn-wa" href="{wa_reg}" target="_blank" rel="noopener noreferrer">WhatsApp 一鍵註冊</a>'
        if wa_reg
        else ""
    )
    wa_sup_btn = (
        f'<a class="j18-btn j18-btn-cs" href="{wa_sup}" target="_blank" rel="noopener noreferrer">WhatsApp 客服諮詢</a>'
        if wa_sup
        else ""
    )
    return f"""
<div class="j18-cta">
  <a class="j18-btn j18-btn-gold" href="{links['home']}" target="_blank" rel="noopener noreferrer">進入 J18 主頁</a>
  {wa_reg_btn}
  {wa_sup_btn}
  <div class="j18-social">
    <a href="{links['facebook']}" target="_blank" rel="noopener noreferrer">Facebook</a>
    <span>·</span>
    <a href="{links['instagram']}" target="_blank" rel="noopener noreferrer">Instagram</a>
  </div>
</div>
"""


def promo_member_heading_html() -> str:
    return f"""
<div class="j18-member-head">
  <h2>{SLOGAN_PLUS}</h2>
  <p>請輸入白名單內的 Email 或通行碼</p>
</div>
"""


def raceday_promo_html() -> str:
    home = j18_home_url()
    return f"""
<div class="rd-promo">
  <span class="rd-promo-kicker">J18</span>
  <span class="rd-promo-copy">{SLOGAN_HERO}</span>
  <a href="{home}" target="_blank" rel="noopener noreferrer">前往主站</a>
</div>
"""
