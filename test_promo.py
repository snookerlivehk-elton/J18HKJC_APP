"""J18 推廣連結與落地文案。"""
import unittest
from urllib.parse import unquote

import promo


class PromoConfigTests(unittest.TestCase):
    def test_home_url_https(self):
        url = promo.j18_home_url()
        self.assertTrue(url.startswith("https://"))
        self.assertIn("j18.hk", url)

    def test_wa_me_strips_non_digits_and_encodes_text(self):
        url = promo.wa_me_url("+852 6450 7318", "想申請成為J18會員")
        self.assertTrue(url.startswith("https://wa.me/85264507318"))
        self.assertIn("text=", url)
        self.assertIn("想申請成為J18會員", unquote(url))

    def test_wa_me_empty_phone(self):
        self.assertEqual(promo.wa_me_url(""), "")
        self.assertEqual(promo.wa_me_url("abc"), "")

    def test_register_and_support_defaults(self):
        links = promo.promo_links()
        self.assertIn("wa.me/85264507318", links["whatsapp_register"])
        self.assertIn("wa.me/85269614567", links["whatsapp_support"])
        self.assertIn("facebook.com/j18hk", links["facebook"])
        self.assertIn("instagram.com/j18.hk", links["instagram"])

    def test_hero_html_uses_official_slogans(self):
        html = promo.promo_hero_html()
        self.assertIn("市場走勢 一目了然", html)
        self.assertIn("全港首創綜合賽馬系統", html)
        for pillar in promo.SLOGAN_PILLARS:
            self.assertIn(pillar, html)

    def test_cta_html_opens_new_tab(self):
        html = promo.promo_cta_html()
        self.assertIn('target="_blank"', html)
        self.assertIn("進入 J18 主頁", html)
        self.assertIn("WhatsApp 一鍵註冊", html)
        self.assertIn("WhatsApp 客服諮詢", html)

    def test_raceday_strip_links_home(self):
        html = promo.raceday_promo_html()
        self.assertIn(promo.j18_home_url(), html)
        self.assertIn("前往主站", html)


if __name__ == "__main__":
    unittest.main()
