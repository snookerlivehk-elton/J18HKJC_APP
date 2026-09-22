"""公開賽日速覽嵌入 API／payload 測試。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class RacedayEmbedApiTest(unittest.TestCase):
    def test_html_page_serves_and_allows_j18_frame(self):
        from raceday_embed_api import create_app

        client = TestClient(create_app())
        r = client.get("/embed/raceday")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        csp = r.headers.get("content-security-policy", "")
        self.assertIn("frame-ancestors", csp)
        self.assertIn("j18.hk", csp)
        self.assertNotIn("x-frame-options", {k.lower() for k in r.headers.keys()})
        self.assertIn("賽日速覽", r.text)
        self.assertIn("/embed/api/default", r.text)
        self.assertIn("horse-radar", r.text)
        self.assertIn("AI 評價", r.text)
        self.assertIn("radarSvg", r.text)

    def test_pc_style_dev_page_is_separate_from_embed(self):
        from raceday_embed_api import create_app

        client = TestClient(create_app())
        pc = client.get("/embed/raceday-pc")
        self.assertEqual(pc.status_code, 200)
        self.assertIn("text/html", pc.headers.get("content-type", ""))
        self.assertIn("賽日速覽", pc.text)
        self.assertIn("綜合走勢", pc.text)
        self.assertIn("推介指數", pc.text)
        self.assertIn('class="sidebar"', pc.text)
        self.assertIn("/embed/api/default", pc.text)
        # 已移除暫不適用的導航／登錄／賠率時間軸
        self.assertNotIn("倍率/指數", pc.text)
        self.assertNotIn("開始賠率", pc.text)
        self.assertNotIn(">登錄<", pc.text)
        # 原嵌入頁未改：仍是右手邊深色卡，不含 PC 整頁側欄
        old = client.get("/embed/raceday")
        self.assertEqual(old.status_code, 200)
        self.assertIn("horse-radar", old.text)
        self.assertNotIn('class="sidebar"', old.text)
        self.assertNotIn("綜合走勢", old.text)

    def test_racecard_board_prototype_serves(self):
        from raceday_embed_api import create_app

        client = TestClient(create_app())
        r = client.get("/embed/racecard")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("排位", r.text)
        self.assertIn("pin-odds", r.text)
        self.assertIn("pin-id", r.text)
        self.assertIn("--pin-id", r.text)
        self.assertIn("hno", r.text)
        self.assertIn("has-img", r.text)
        self.assertIn("background-size: contain", r.text)
        self.assertIn("background-color: transparent", r.text)
        self.assertIn("margin: 0 0 0 -1px", r.text)
        self.assertIn("馬號", r.text)
        self.assertIn("檔位", r.text)
        self.assertIn("draw-lab", r.text)
        self.assertIn("draw-no", r.text)
        self.assertIn("draw-sort", r.text)
        self.assertIn(".hno", r.text)
        self.assertIn("color: #fff;\n      font-size: 15px", r.text)
        self.assertIn(".odds .win { font-size: 14px", r.text)
        self.assertIn(".odds .pla { font-size: 14px", r.text)
        self.assertIn("font-weight: 400", r.text)
        self.assertIn(".hrow:not(.head) .cell.pin-odds", r.text)
        self.assertIn("justify-content: center;\n      gap: 3px", r.text)
        self.assertIn(".draw-no", r.text)
        self.assertIn("border-radius: 50%", r.text)
        self.assertIn("font-size: 13px;\n      font-weight: 400", r.text)
        self.assertIn("width: 15px; height: 15px", r.text)
        self.assertIn("--pin-id: 57px", r.text)
        self.assertIn("width: 22px;\n      height: 22px", r.text)
        self.assertIn("width: 21px;\n      height: 21px", r.text)
        self.assertIn("background: var(--nav)", r.text)
        self.assertIn("--head-fs: 13px", r.text)
        self.assertIn("height: 47px", r.text)
        self.assertIn(".hname {\n      display: block;\n      font-size: 13px; font-weight: 400", r.text)
        self.assertIn(".odds { display: flex; flex-direction: column; align-items: center; gap: 1px", r.text)
        self.assertNotIn("pin-draw", r.text)
        self.assertNotIn("draw-dot", r.text)
        self.assertNotIn("draw-pct", r.text)
        self.assertNotIn("--pin-draw", r.text)
        self.assertIn("fmtDrawPct", r.text)
        self.assertIn("DRAW_WIN_DEMO", r.text)
        self.assertIn("10.8", r.text)
        self.assertIn("獨贏", r.text)
        self.assertIn("位置", r.text)
        self.assertIn("賽前", r.text)
        self.assertIn("綜合分", r.text)
        self.assertIn("外祖父", r.text)
        self.assertIn("左鎖", r.text)
        self.assertIn("lock-cluster", r.text)
        self.assertIn("堅多福", r.text)
        self.assertIn("投注頁", r.text)
        self.assertIn('"win":3.4', r.text)
        self.assertIn('"place":1.5', r.text)
        self.assertIn('"win":13', r.text)
        self.assertIn("fmtOdds", r.text)
        self.assertNotIn("尚未開出", r.text)
        self.assertIn("跑馬地", r.text)
        self.assertIn("騎師", r.text)
        self.assertIn("練馬師", r.text)
        self.assertIn("splitNameAllow", r.text)
        self.assertIn("v stacked", r.text)
        self.assertIn("v.stacked .sub", r.text)
        self.assertIn("font: inherit", r.text)
        self.assertIn("fitScrollColWidths", r.text)
        self.assertIn("applyMeeting", r.text)
        self.assertIn("COL_FIT", r.text)
        self.assertIn("dataToRulePx: 2", r.text)
        self.assertIn("--scroll-col-gap: 2px", r.text)
        self.assertIn("width: max-content", r.text)
        self.assertNotIn("min-width: 54px", r.text)
        self.assertNotIn(".scroll-col.sm", r.text)
        self.assertIn("var(--scroll-col-gap)", r.text)
        self.assertNotIn("top: 6px; bottom: 6px", r.text)
        self.assertIn("周俊樂 (-2)", r.text)
        self.assertIn("南風讓賽", r.text)
        self.assertNotIn("辣得金", r.text)
        self.assertNotIn("scrollHeadClip", r.text)
        self.assertNotIn("translate3d", r.text)
        self.assertIn("head-static", r.text)
        self.assertIn("sort-ico", r.text)
        self.assertNotIn('data-sort="name"', r.text)
        self.assertNotIn('data-sort="place"', r.text)
        self.assertNotIn('data-sort="win"', r.text)
        self.assertIn('data-sort="draw"', r.text)
        self.assertNotIn("tabbar", r.text)
        self.assertNotIn("主選單", r.text)
        self.assertNotIn("名家", r.text)
        # 不取代原有賽日嵌入頁
        old = client.get("/embed/raceday")
        self.assertNotIn("pin-odds", old.text)

    def test_health_and_default_empty(self):
        from raceday_embed_api import create_app

        client = TestClient(create_app())
        h = client.get("/embed/api/health")
        self.assertEqual(h.status_code, 200)
        self.assertEqual(h.json().get("service"), "j18-raceday-embed")

        d = client.get("/embed/api/default")
        self.assertEqual(d.status_code, 200)
        body = d.json()
        self.assertTrue(body.get("ok"))
        self.assertIn("races", body)

    def test_race_not_found(self):
        from raceday_embed_api import create_app

        with patch(
            "raceday_embed_payload.build_race_prediction",
            return_value={"ok": False, "error": "no_prediction", "race_id": "x"},
        ):
            # patch where used inside build_public_race_view
            with patch(
                "raceday_embed_payload.build_public_race_view",
                return_value={"ok": False, "error": "no_prediction", "race_id": "x"},
            ):
                client = TestClient(create_app())
                r = client.get("/embed/api/races/NOPE")
                self.assertEqual(r.status_code, 404)

    def test_mounted_on_ad_api(self):
        import ad_api

        client = TestClient(ad_api.app)
        r = client.get("/embed/raceday")
        self.assertEqual(r.status_code, 200)
        self.assertIn("賽日速覽", r.text)

    def test_public_race_view_includes_fused(self):
        from raceday_embed_payload import build_public_race_view

        fake_base = {
            "ok": True,
            "race_id": "20260906ST01",
            "race": {
                "racing_date": "2026-09-06",
                "course": "ST",
                "race_num": 1,
                "n_runners": 2,
                "expected_pace": "快",
            },
            "meta": {"match_rate": 0.9, "avg_model_coverage": 0.8, "provisional": False},
            "picks": {
                "win": [{"horse_no": 1, "horse_name": "甲", "model_win_prob_pct": 60}],
                "place": [
                    {"horse_no": 1, "horse_name": "甲", "model_win_prob_pct": 60},
                    {"horse_no": 2, "horse_name": "乙", "model_win_prob_pct": 40},
                ],
            },
            "runners": [
                {
                    "horse_no": 1,
                    "horse_name": "甲",
                    "draw": 1,
                    "jockey": "J1",
                    "trainer": "T1",
                    "pred_rank": 1,
                    "total_score": 5.55,
                    "model_win_prob": 0.6,
                    "model_win_prob_pct": 60.0,
                    "factors": {
                        "jockey": 1.0,
                        "trainer": 0.8,
                        "synergy": 0.9,
                        "draw": 0.5,
                        "form": 1.2,
                        "pace": 0.7,
                        "speed": 1.1,
                        "speed_guide": 0.4,
                    },
                    "ai": {"ai_score": 0.8, "confidence": 0.9, "ai_combo": 0.72, "summary": "穩"},
                },
                {
                    "horse_no": 2,
                    "horse_name": "乙",
                    "draw": 2,
                    "jockey": "J2",
                    "trainer": "T2",
                    "pred_rank": 2,
                    "total_score": 4.10,
                    "model_win_prob": 0.4,
                    "model_win_prob_pct": 40.0,
                    "factors": {
                        "jockey": 0.2,
                        "trainer": 0.3,
                        "synergy": 0.1,
                        "draw": 0.9,
                        "form": 0.4,
                        "pace": 0.2,
                        "speed": 0.3,
                        "speed_guide": 0.8,
                    },
                    "ai": {"ai_score": 0.2, "confidence": 0.5, "ai_combo": 0.1, "summary": ""},
                },
            ],
        }
        with patch(
            "raceday_embed_payload.build_race_prediction", return_value=fake_base
        ):
            out = build_public_race_view("20260906ST01")
        self.assertTrue(out["ok"])
        self.assertIn("fused", out["picks"])
        self.assertEqual(out["race"]["course_label"], "沙田")
        self.assertEqual(len(out["runners"]), 2)
        self.assertIn("fused_share_pct", out["runners"][0])
        r0 = out["runners"][0]
        self.assertIn("radar", r0)
        self.assertEqual(len(r0["radar"]["labels"]), 8)
        self.assertEqual(len(r0["radar"]["values"]), 8)
        self.assertEqual(r0["ai_combo"], 0.72)
        self.assertEqual(r0["ai_summary"], "穩")
        self.assertIn("radar_axes", out)

    def test_json_safe_handles_numpy(self):
        import numpy as np

        from raceday_embed_payload import _json_safe

        raw = {
            "a": np.float64(1.25),
            "b": np.int64(3),
            "c": [np.float32(0.5), {"d": np.bool_(True)}],
        }
        out = _json_safe(raw)
        self.assertEqual(out["a"], 1.25)
        self.assertEqual(out["b"], 3)
        self.assertEqual(out["c"][0], 0.5)
        self.assertIs(out["c"][1]["d"], True)
        import json

        json.dumps(out)  # must not raise


if __name__ == "__main__":
    unittest.main()
