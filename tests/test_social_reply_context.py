"""留言機械人 reply-context：綜合推介 + Form AI 評價 + webhook。"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List
from unittest import mock

import pandas as pd

from social_reply_context import (
    build_reply_context,
    dispatch_reply_webhook,
    enrich_tips_with_ai,
    format_reply_context_prompt,
    load_latest_reply_context,
    public_reply_payload,
    publish_reply_context,
    race_id_from_meeting,
    save_reply_context,
)


def _sample_ad_pkg() -> Dict[str, Any]:
    return {
        "id": "2026-07-15-hv-night",
        "status": "ready",
        "meeting": {
            "date": "2026-07-15",
            "weekday": "星期三",
            "venue": "谷草",
            "venue_code": "HV",
            "session": "夜",
            "start_time": "約晚上7時15分",
        },
        "intro": "2026-07-15 星期三谷草夜賽共 2 場，J18 綜合推介已出爐。",
        "tips": [
            {
                "race": 1,
                "horses": [
                    {"no": 4, "name": "多利神駒"},
                    {"no": 9, "name": "天下寵兒"},
                ],
            },
            {
                "race": 2,
                "horses": [{"no": 3, "name": "快馬"}],
            },
        ],
        "copy": {
            "ai": {
                "featured": [
                    {
                        "race_no": 1,
                        "horse_no": 4,
                        "horse_name": "多利神駒",
                        "comment": "近績走勢穩陣",
                    }
                ]
            }
        },
    }


def _sample_copy() -> Dict[str, Any]:
    return {
        "meeting": {"racing_date": "2026-07-15", "course": "HV"},
        "races": [
            {
                "race_id": "20260715HV01",
                "race_no": 1,
                "fused_picks": [
                    {
                        "horse_no": 4,
                        "horse_name": "多利神駒",
                        "share_pct": 28.5,
                        "tag": "爭勝",
                    },
                    {
                        "horse_no": 9,
                        "horse_name": "天下寵兒",
                        "share_pct": 22.0,
                        "tag": "推介",
                    },
                ],
            },
            {
                "race_id": "20260715HV02",
                "race_no": 2,
                "fused_picks": [
                    {
                        "horse_no": 3,
                        "horse_name": "快馬",
                        "share_pct": 31.0,
                        "tag": "爭勝",
                    }
                ],
            },
        ],
    }


def _ai_loader(race_id: str):
    rows = {
        "20260715HV01": [
            {
                "horse_no": 4,
                "ai_score": 1.2,
                "confidence": 0.8,
                "summary": "近績穩陣，距離適性佳。",
                "tags_json": '["穩陣","適性"]',
                "risks_json": '["檔位一般"]',
                "evidence_json": '["近兩仗入位"]',
            },
            {
                "horse_no": 9,
                "ai_score": 0.5,
                "confidence": 0.6,
                "summary": "升班有挑戰。",
                "tags": ["升班"],
                "risks": [],
                "evidence": [],
            },
        ],
        "20260715HV02": [
            {
                "horse_no": 3,
                "ai_score": 1.0,
                "confidence": 0.7,
                "summary": "速步突出。",
                "tags_json": "[]",
                "risks_json": "[]",
                "evidence_json": "[]",
            }
        ],
    }
    data = rows.get(race_id) or []
    return pd.DataFrame(data)


class RaceIdTest(unittest.TestCase):
    def test_build_race_id(self):
        self.assertEqual(
            race_id_from_meeting("2026-07-15", "HV", 1), "20260715HV01"
        )
        self.assertEqual(
            race_id_from_meeting("2026-09-13", "ST", 10), "20260913ST10"
        )


class EnrichTipsTest(unittest.TestCase):
    def test_enrich_attaches_ai_and_meta(self):
        tips = _sample_ad_pkg()["tips"]
        out = enrich_tips_with_ai(
            tips,
            racing_date="2026-07-15",
            course="HV",
            copy_data=_sample_copy(),
            form_ai_loader=_ai_loader,
        )
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["race_id"], "20260715HV01")
        h0 = out[0]["horses"][0]
        self.assertEqual(h0["no"], 4)
        self.assertEqual(h0["tag"], "爭勝")
        self.assertEqual(h0["share_pct"], 28.5)
        self.assertIsNotNone(h0["ai"])
        self.assertEqual(h0["ai"]["ai_score"], 1.2)
        self.assertIn("近績穩陣", h0["ai"]["summary"])
        self.assertEqual(h0["ai"]["tags"], ["穩陣", "適性"])


class BuildAndPromptTest(unittest.TestCase):
    def test_build_ready_and_prompt(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = build_reply_context(
                _sample_ad_pkg(),
                copy_data=_sample_copy(),
                output_root=root,
                form_ai_loader=_ai_loader,
            )
            self.assertEqual(ctx["status"], "ready")
            self.assertEqual(ctx["purpose"], "social_reply")
            self.assertEqual(ctx["meta"]["n_ai_evals"], 3)
            self.assertEqual(ctx["meta"]["n_horses"], 3)
            pub = public_reply_payload(ctx)
            self.assertIn("tips", pub)
            self.assertNotIn("webhook", pub)

            text = format_reply_context_prompt(ctx)
            self.assertIn("多利神駒", text)
            self.assertIn("近績穩陣", text)
            self.assertIn("第1場", text)
            self.assertIn("社交精選評述", text)


class PublishAndWebhookTest(unittest.TestCase):
    def test_publish_saves_latest_and_webhooks(self):
        received: List[Dict[str, Any]] = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                received.append(
                    {
                        "secret": self.headers.get("X-Webhook-Secret"),
                        "purpose": self.headers.get("X-Context-Purpose"),
                        "body": json.loads(body.decode()),
                    }
                )
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), H)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with TemporaryDirectory() as tmp:
                root = Path(tmp)
                with mock.patch.dict(
                    "os.environ",
                    {
                        "SOCIAL_REPLY_BOT_WEBHOOK_URL": f"http://127.0.0.1:{port}/hook",
                        "SOCIAL_REPLY_BOT_WEBHOOK_SECRET": "reply-secret",
                        "SOCIAL_REPLY_AUTO_PUBLISH": "true",
                    },
                    clear=False,
                ):
                    result = publish_reply_context(
                        _sample_ad_pkg(),
                        output_root=root,
                        copy_data=_sample_copy(),
                        notify=True,
                        form_ai_loader=_ai_loader,
                    )
                self.assertTrue(result["ok"])
                self.assertEqual(result["status"], "ready")
                latest = load_latest_reply_context(root)
                self.assertIsNotNone(latest)
                self.assertEqual(latest["id"], "2026-07-15-hv-night")
                # wait briefly for webhook
                for _ in range(20):
                    if received:
                        break
                    import time

                    time.sleep(0.05)
                self.assertEqual(len(received), 1)
                self.assertEqual(received[0]["secret"], "reply-secret")
                self.assertEqual(received[0]["purpose"], "social_reply")
                self.assertEqual(received[0]["body"]["purpose"], "social_reply")
                self.assertEqual(received[0]["body"]["tips"][0]["horses"][0]["no"], 4)
        finally:
            server.shutdown()

    def test_webhook_skipped_without_url(self):
        with mock.patch.dict(
            "os.environ",
            {"SOCIAL_REPLY_BOT_WEBHOOK_URL": "", "REPLY_BOT_WEBHOOK_URL": ""},
            clear=False,
        ):
            ctx = build_reply_context(
                _sample_ad_pkg(),
                copy_data=_sample_copy(),
                form_ai_loader=_ai_loader,
            )
            result = dispatch_reply_webhook(ctx)
            self.assertTrue(result.get("skipped"))


class ApiRouteSmokeTest(unittest.TestCase):
    def test_fastapi_routes_exist(self):
        from ad_api import app

        paths = {r.path for r in app.routes if hasattr(r, "path")}
        self.assertIn("/v1/reply-context/latest", paths)
        self.assertIn("/v1/reply-context/latest/prompt", paths)
        self.assertIn("/v1/reply-context/rebuild", paths)
        self.assertIn("/v1/reply-context/{context_id}/notify", paths)

    def test_health_includes_reply_flag(self):
        from fastapi.testclient import TestClient

        from ad_api import app

        client = TestClient(app)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("reply_webhook_configured", data)

    def test_latest_endpoint(self):
        from fastapi.testclient import TestClient

        from ad_api import app

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = build_reply_context(
                _sample_ad_pkg(),
                copy_data=_sample_copy(),
                output_root=root,
                form_ai_loader=_ai_loader,
            )
            save_reply_context(ctx, root)
            with mock.patch.dict(
                "os.environ",
                {"AD_API_KEY": "test-key", "AD_OUTPUT_DIR": str(root)},
                clear=False,
            ):
                client = TestClient(app)
                resp = client.get(
                    "/v1/reply-context/latest",
                    headers={"Authorization": "Bearer test-key"},
                )
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertEqual(body["id"], "2026-07-15-hv-night")
                self.assertEqual(body["tips"][0]["horses"][0]["ai"]["ai_score"], 1.2)

                prompt_resp = client.get(
                    "/v1/reply-context/latest/prompt",
                    headers={"X-API-Key": "test-key"},
                )
                self.assertEqual(prompt_resp.status_code, 200)
                self.assertIn("多利神駒", prompt_resp.json()["prompt"])


class BotCliTest(unittest.TestCase):
    def test_bot_show_after_publish(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            publish_reply_context(
                _sample_ad_pkg(),
                output_root=root,
                copy_data=_sample_copy(),
                notify=False,
                form_ai_loader=_ai_loader,
            )
            from social_reply_bot import prompt_latest, show_latest

            shown = show_latest(output_root=root)
            self.assertTrue(shown["ok"])
            text = prompt_latest(output_root=root)
            self.assertIn("J18 賽事答覆參考資料", text)


if __name__ == "__main__":
    unittest.main()
