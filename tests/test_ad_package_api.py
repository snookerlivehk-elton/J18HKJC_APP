"""廣告包 API：schema、幂等 id、webhook 通知。"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional
from unittest import mock

from ad_package import (
    build_ad_package_from_copy,
    dispatch_ad_webhook,
    public_payload,
    stable_ad_id,
)


def _sample_copy() -> Dict[str, Any]:
    return {
        "meeting": {
            "batch_id": "b1",
            "racing_date": "2026-07-15",
            "course": "HV",
            "primary_track": "fused",
        },
        "fused_copy": "今晚谷草焦點係第5場。",
        "races": [
            {
                "race_no": 1,
                "fused_picks": [
                    {"horse_no": 4, "horse_name": "多利神駒"},
                    {"horse_no": 9, "horse_name": "天下寵兒"},
                    {"horse_no": 2, "horse_name": "飛影"},
                    {"horse_no": 7, "horse_name": "金光"},
                    {"horse_no": 1, "horse_name": "多餘"},
                ],
            },
            {
                "race_no": 2,
                "fused_picks": [
                    {"horse_no": 3, "horse_name": "快馬"},
                    {"horse_no": 5, "horse_name": "穩陣"},
                ],
            },
        ],
    }


class StableIdTest(unittest.TestCase):
    def test_hv_night_id(self):
        with mock.patch("ad_package.resolve_poster_theme", return_value="night"):
            self.assertEqual(
                stable_ad_id("2026-07-15", "HV", session="夜", is_day_meeting=False),
                "2026-07-15-hv-night",
            )

    def test_st_day_id(self):
        with mock.patch("ad_package.resolve_poster_theme", return_value="day"):
            self.assertEqual(
                stable_ad_id("2026-07-16", "ST", is_day_meeting=True),
                "2026-07-16-st-day",
            )

    def test_idempotent_same_inputs(self):
        with mock.patch("ad_package.resolve_poster_theme", return_value="night"):
            a = stable_ad_id("2026-07-15", "HV", is_day_meeting=False)
            b = stable_ad_id("2026-07-15", "HV", is_day_meeting=False)
            self.assertEqual(a, b)


class SchemaAndBuildTest(unittest.TestCase):
    def test_pending_ai_without_social_copy(self):
        """只有海報、未有 AI 文案 → pending_ai（Grok 唔應當 ready）。"""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = Path(tmp) / "empty.db"
            fused = root / "fused.png"
            fused.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            with mock.patch(
                "ad_package.lookup_meeting_session",
                return_value={"session": "夜", "is_day_meeting": False},
            ):
                with mock.patch("ad_package.resolve_poster_theme", return_value="night"):
                    with mock.patch.dict(
                        "os.environ",
                        {
                            "AD_API_PUBLIC_BASE": "https://ads.example.com",
                            "AD_PACKAGE_REQUIRE_AI_SOCIAL": "true",
                            "USE_SQLITE": "true",
                            "AD_STORE_ENABLED": "true",
                            "SQLITE_DB_PATH": str(db_path),
                            "DATABASE_URL": "",
                            "DATABASE_URL_SYNC": "",
                        },
                        clear=False,
                    ):
                        import ad_store

                        old_engine = ad_store._ENGINE
                        old_ensured = ad_store._ENSURED
                        old_use = ad_store.USE_SQLITE
                        old_path = ad_store.SQLITE_DB_PATH
                        ad_store._ENGINE = None
                        ad_store._ENSURED = False
                        ad_store.USE_SQLITE = True
                        ad_store.SQLITE_DB_PATH = str(db_path)
                        try:
                            pkg = build_ad_package_from_copy(
                                _sample_copy(),
                                output_root=root,
                                poster_src=fused,
                                notify=False,
                            )
                        finally:
                            if ad_store._ENGINE is not None:
                                try:
                                    ad_store._ENGINE.dispose()
                                except Exception:
                                    pass
                            ad_store._ENGINE = old_engine
                            ad_store._ENSURED = old_ensured
                            ad_store.USE_SQLITE = old_use
                            ad_store.SQLITE_DB_PATH = old_path
            self.assertEqual(pkg["status"], "pending_ai")
            self.assertIsNone(pkg["copy"].get("ai"))
            self.assertTrue(pkg["assets"]["poster_url"].endswith("/v1/ads/2026-07-15-hv-night/poster"))

    def test_build_schema_ready_with_ai_social(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 假海報
            fused = root / "fused.png"
            fused.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            # AI 精選文案
            (root / "social_copy.json").write_text(
                json.dumps(
                    {
                        "title": "今晚邊場最有睇頭？",
                        "subtitle": "J18 AI 精選",
                        "featured": [
                            {
                                "race_no": 1,
                                "horse_no": 4,
                                "horse_name": "多利神駒",
                                "comment": "近績走勢穩陣，值得一讚",
                            }
                        ],
                        "hashtags": ["#J18", "#賽馬"],
                        "source": "llm",
                        "post_text": "今晚邊場最有睇頭？\n\n第1場｜4 多利神駒\n近績走勢穩陣，值得一讚\n",
                        "meeting": {"generated_at": "2026-07-15T10:00:00+08:00"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with mock.patch(
                "ad_package.lookup_meeting_session",
                return_value={"session": "夜", "is_day_meeting": False},
            ):
                with mock.patch("ad_package.resolve_poster_theme", return_value="night"):
                    with mock.patch.dict(
                        "os.environ",
                        {
                            "AD_API_PUBLIC_BASE": "https://ads.example.com",
                            "AD_PACKAGE_REQUIRE_AI_SOCIAL": "true",
                        },
                        clear=False,
                    ):
                        pkg1 = build_ad_package_from_copy(
                            _sample_copy(),
                            output_root=root,
                            poster_src=fused,
                            notify=False,
                        )
                        created = pkg1["created_at"]
                        pkg2 = build_ad_package_from_copy(
                            _sample_copy(),
                            output_root=root,
                            poster_src=fused,
                            notify=False,
                        )

            self.assertEqual(pkg1["id"], "2026-07-15-hv-night")
            self.assertEqual(pkg2["id"], pkg1["id"])
            self.assertEqual(pkg2["created_at"], created)
            self.assertEqual(pkg1["status"], "ready")
            self.assertEqual(pkg1["meeting"]["venue_code"], "HV")
            self.assertEqual(pkg1["meeting"]["session"], "夜")
            self.assertEqual(len(pkg1["tips"]), 2)
            self.assertEqual(len(pkg1["tips"][0]["horses"]), 4)
            self.assertIn("多利神駒", pkg1["copy"]["facebook"])
            self.assertIsNotNone(pkg1["copy"].get("ai"))
            self.assertEqual(pkg1["copy"]["ai"]["title"], "今晚邊場最有睇頭？")
            self.assertEqual(len(pkg1["copy"]["ai"]["featured"]), 1)
            self.assertTrue(
                pkg1["assets"]["poster_url"].endswith("/v1/ads/2026-07-15-hv-night/poster")
            )

            pub = public_payload(pkg1)
            for key in (
                "id",
                "created_at",
                "status",
                "meeting",
                "intro",
                "tips",
                "copy",
                "assets",
                "publish",
                "links",
            ):
                self.assertIn(key, pub)
            self.assertIn("ai", pub["copy"])
            self.assertEqual(pub["copy"]["ai"]["featured"][0]["horse_name"], "多利神駒")
            self.assertNotIn("webhook", pub)
            self.assertNotIn("meta", pub)
            self.assertNotIn("poster_path", pub.get("assets") or {})

    def test_ready_via_db_archive_without_local_social_file(self):
        """跨服務：本機無 social_copy.json，但 DB archive 有 AI → ready + facebook。"""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = Path(tmp) / "store.db"
            fused = root / "fused.png"
            fused.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

            with mock.patch.dict(
                "os.environ",
                {
                    "USE_SQLITE": "true",
                    "AD_STORE_ENABLED": "true",
                    "SQLITE_DB_PATH": str(db_path),
                    "DATABASE_URL": "",
                    "DATABASE_URL_SYNC": "",
                    "AD_API_PUBLIC_BASE": "https://ads.example.com",
                    "AD_PACKAGE_REQUIRE_AI_SOCIAL": "true",
                },
                clear=False,
            ):
                import ad_store

                old_engine = ad_store._ENGINE
                old_ensured = ad_store._ENSURED
                old_use = ad_store.USE_SQLITE
                old_path = ad_store.SQLITE_DB_PATH
                ad_store._ENGINE = None
                ad_store._ENSURED = False
                ad_store.USE_SQLITE = True
                ad_store.SQLITE_DB_PATH = str(db_path)
                try:
                    ad_store.upsert_archive(
                        "2026-07-15",
                        "HV",
                        "social",
                        {
                            "title": "今晚邊場最有睇頭？",
                            "featured": [
                                {
                                    "race_no": 1,
                                    "horse_no": 4,
                                    "horse_name": "多利神駒",
                                    "comment": "近績唔錯喎",
                                }
                            ],
                            "post_text": (
                                "今晚邊場最有睇頭？\n\n"
                                "第1場｜4 多利神駒\n近績唔錯喎\n\n"
                                "想獲得臨場更多資訊或心水, 請即刻登錄j18.hk了解更多啦!!\n"
                            ),
                            "hashtags": ["#J18", "#賽馬"],
                            "source": "llm",
                            "meeting": {
                                "batch_id": "b1",
                                "racing_date": "2026-07-15",
                                "course": "HV",
                            },
                        },
                        batch_id="b1",
                    )
                    with mock.patch(
                        "ad_package.lookup_meeting_session",
                        return_value={"session": "夜", "is_day_meeting": False},
                    ):
                        with mock.patch(
                            "ad_package.resolve_poster_theme", return_value="night"
                        ):
                            pkg = build_ad_package_from_copy(
                                _sample_copy(),
                                output_root=root,
                                poster_src=fused,
                                notify=False,
                            )
                    self.assertEqual(pkg["status"], "ready")
                    self.assertIsNotNone(pkg["copy"].get("ai"))
                    self.assertIn("j18.hk", pkg["copy"]["facebook"].lower())
                    self.assertIn("多利神駒", pkg["copy"]["facebook"])
                    latest = ad_store.load_latest_ad_package_db(ready_only=True)
                    self.assertIsNotNone(latest)
                    self.assertEqual(latest["id"], pkg["id"])
                    self.assertEqual(latest["status"], "ready")
                    social = ad_store.get_social_json_db(pkg["id"])
                    self.assertIsNotNone(social)
                finally:
                    if ad_store._ENGINE is not None:
                        try:
                            ad_store._ENGINE.dispose()
                        except Exception:
                            pass
                    ad_store._ENGINE = old_engine
                    ad_store._ENSURED = old_ensured
                    ad_store.USE_SQLITE = old_use
                    ad_store.SQLITE_DB_PATH = old_path


class WebhookDispatchTest(unittest.TestCase):
    def test_skips_non_ready(self):
        result = dispatch_ad_webhook({"id": "x", "status": "draft"})
        self.assertTrue(result.get("skipped"))

    def test_webhook_called_and_retries(self):
        received: List[Dict[str, Any]] = []
        hits = {"n": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                hits["n"] += 1
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                received.append(
                    {
                        "body": json.loads(raw.decode("utf-8")),
                        "secret": self.headers.get("X-Webhook-Secret"),
                        "idem": self.headers.get("Idempotency-Key"),
                    }
                )
                # 前兩次失敗，第三次成功
                if hits["n"] < 3:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"fail")
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")

            def log_message(self, format, *args):  # noqa: A003
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{port}/hook"
            with mock.patch.dict(
                "os.environ",
                {
                    "GROK_BOT_WEBHOOK_URL": url,
                    "GROK_BOT_WEBHOOK_SECRET": "test-secret",
                },
                clear=False,
            ):
                with mock.patch("ad_package.time.sleep", return_value=None):
                    result = dispatch_ad_webhook(
                        {
                            "id": "2026-07-15-hv-night",
                            "status": "ready",
                            "meeting": {"date": "2026-07-15"},
                            "tips": [],
                            "copy": {},
                            "assets": {"poster_path": "/tmp/x.png"},
                            "meta": {"internal": 1},
                        },
                        max_attempts=3,
                    )
            self.assertTrue(result.get("ok"))
            self.assertEqual(len(result.get("attempts") or []), 3)
            self.assertEqual(hits["n"], 3)
            self.assertEqual(received[-1]["secret"], "test-secret")
            self.assertEqual(received[-1]["idem"], "2026-07-15-hv-night")
            self.assertNotIn("poster_path", (received[-1]["body"].get("assets") or {}))
            self.assertNotIn("meta", received[-1]["body"])
        finally:
            server.shutdown()


class ApiAuthSmokeTest(unittest.TestCase):
    def test_health_no_key(self):
        from fastapi.testclient import TestClient

        from ad_api import app

        client = TestClient(app)
        r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("service"), "j18-ad-api")

    def test_latest_requires_key(self):
        from fastapi.testclient import TestClient

        from ad_api import app

        with mock.patch.dict("os.environ", {"AD_API_KEY": "secret-key"}, clear=False):
            client = TestClient(app)
            self.assertEqual(client.get("/v1/ads/latest").status_code, 401)
            ok = client.get(
                "/v1/ads/latest",
                headers={"Authorization": "Bearer secret-key"},
            )
            # 未必有資料，但認證應通過（404 或 200）
            self.assertIn(ok.status_code, (200, 404))


class IngestAndLatestTest(unittest.TestCase):
    def test_ingest_makes_latest_ready_with_facebook_and_poster(self):
        import base64

        from fastapi.testclient import TestClient

        from ad_api import app
        from ad_package import build_ad_package_from_copy, public_payload

        with TemporaryDirectory() as prod_tmp, TemporaryDirectory() as api_tmp:
            prod = Path(prod_tmp)
            api_root = Path(api_tmp)
            fused = prod / "fused.png"
            fused.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
            social = {
                "title": "沙田日賽邊場最有睇頭？留言話我知！",
                "featured": [
                    {
                        "race_no": 1,
                        "horse_no": 7,
                        "horse_name": "增旺",
                        "comment": "近績穩",
                    }
                ],
                "hashtags": ["#J18", "#賽馬", "#沙田", "#賽前預測", "#J18HK", "#extra"],
                "post_text": (
                    "【J18】2026-09-13 沙田日賽\n"
                    "邊場最有睇頭？留言話我知！\n"
                    "第1場｜7 增旺\n近績穩\n\n"
                    "想追臨場？登入 J18.hk\n預測只供參考。\n"
                    "#J18 #賽馬 #沙田"
                ),
            }
            (prod / "social_copy.json").write_text(
                json.dumps(social, ensure_ascii=False), encoding="utf-8"
            )
            env = {
                "AD_API_KEY": "secret-key",
                "AD_API_PUBLIC_BASE": "https://ads.example.com",
                "AD_API_BASE_URL": "",
                "AD_PACKAGE_REQUIRE_AI_SOCIAL": "true",
                "AD_STORE_ENABLED": "false",
                "AD_OUTPUT_DIR": str(api_root),
            }
            with mock.patch.dict("os.environ", env, clear=False):
                with mock.patch(
                    "ad_package.lookup_meeting_session",
                    return_value={"session": "日", "is_day_meeting": True},
                ):
                    with mock.patch(
                        "ad_package.resolve_poster_theme", return_value="day"
                    ):
                        built = build_ad_package_from_copy(
                            _sample_copy(),
                            output_root=prod,
                            notify=False,
                        )
                self.assertEqual(built.get("status"), "ready")
                self.assertTrue((built.get("copy") or {}).get("facebook"))
                tags = (built.get("copy") or {}).get("hashtags") or []
                self.assertLessEqual(len(tags), 5)

                poster_path = prod / "packages" / f"{built['id']}.png"
                self.assertTrue(poster_path.is_file())
                poster_b64 = base64.b64encode(poster_path.read_bytes()).decode("ascii")

                client = TestClient(app)
                self.assertEqual(
                    client.get(
                        "/v1/ads/latest",
                        headers={"Authorization": "Bearer secret-key"},
                    ).status_code,
                    404,
                )
                ingested = client.post(
                    "/v1/ads/ingest",
                    headers={"Authorization": "Bearer secret-key"},
                    json={
                        "package": public_payload(built),
                        "poster_png_b64": poster_b64,
                        "notify": False,
                    },
                )
                self.assertEqual(ingested.status_code, 200, ingested.text)
                body = ingested.json()
                self.assertTrue(body.get("ok"))
                self.assertEqual(body.get("status"), "ready")

                latest = client.get(
                    "/v1/ads/latest",
                    headers={"Authorization": "Bearer secret-key"},
                )
                self.assertEqual(latest.status_code, 200, latest.text)
                data = latest.json()
                self.assertEqual(data.get("status"), "ready")
                self.assertIn("facebook", data.get("copy") or {})
                self.assertTrue((data.get("copy") or {}).get("facebook"))
                poster_url = (data.get("assets") or {}).get("poster_url") or ""
                self.assertTrue(poster_url.endswith(f"/v1/ads/{data['id']}/poster"))
                # 公開海報可下載（唔使 login Streamlit）
                rel = poster_url.replace("https://ads.example.com", "")
                poster_resp = client.get(rel)
                self.assertEqual(poster_resp.status_code, 200)
                self.assertTrue(poster_resp.content.startswith(b"\x89PNG"))




class TipsExtractionTest(unittest.TestCase):
    def test_alternate_race_and_horse_fields(self):
        from ad_package import _tips_from_races

        tips = _tips_from_races(
            [
                {
                    "race_num": 1,
                    "fused_picks": [{"no": 7, "name": "增旺"}],
                },
                {
                    "race_no": 2,
                    "model_picks": [{"horse_no": 3, "horse_name": "飛影"}],
                },
            ]
        )
        self.assertEqual(len(tips), 2)
        self.assertEqual(tips[0]["horses"][0]["no"], 7)
        self.assertEqual(tips[1]["horses"][0]["name"], "飛影")


class RejectEmptyPendingPosterTest(unittest.TestCase):
    def test_save_blocks_downgrade_to_empty_pending(self):
        from ad_package import save_ad_package, _package_quality

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg_dir = root / "packages"
            pkg_dir.mkdir(parents=True)
            good = {
                "id": "2026-09-13-st-day",
                "status": "ready",
                "tips": [{"race": 1, "horses": [{"no": 7, "name": "增旺"}]}],
                "copy": {"facebook": "hi", "ai": {"post_text": "hi", "featured": []}},
                "assets": {"poster_url": "https://ads.example.com/v1/ads/2026-09-13-st-day/poster"},
                "meta": {"has_poster": True, "has_ai_social": True},
            }
            (pkg_dir / "2026-09-13-st-day.json").write_text(
                json.dumps(good), encoding="utf-8"
            )
            (pkg_dir / "2026-09-13-st-day.png").write_bytes(b"\x89PNG" + b"0" * 20)
            bad = {
                "id": "2026-09-13-st-day",
                "status": "pending_poster",
                "tips": [],
                "intro": "共 0 場",
                "copy": {"facebook": "共 0 場", "ai": None},
                "assets": {"poster_url": ""},
                "meta": {"has_poster": False},
            }
            with mock.patch.dict(
                "os.environ",
                {"AD_STORE_ENABLED": "false", "AD_API_BASE_URL": ""},
                clear=False,
            ):
                save_ad_package(bad, root, push_remote=False)
            kept = json.loads((pkg_dir / "2026-09-13-st-day.json").read_text(encoding="utf-8"))
            self.assertEqual(kept.get("status"), "ready")
            self.assertTrue(kept.get("tips"))
            self.assertGreater(_package_quality(kept), _package_quality(bad))
            self.assertEqual(bad.get("save_skipped", {}).get("reason"), "downgrade_blocked")

    def test_ingest_rejects_pending_poster(self):
        from fastapi.testclient import TestClient

        from ad_api import app

        with mock.patch.dict("os.environ", {"AD_API_KEY": "secret-key"}, clear=False):
            client = TestClient(app)
            r = client.post(
                "/v1/ads/ingest",
                headers={"Authorization": "Bearer secret-key"},
                json={
                    "package": {
                        "id": "2026-09-13-st-day",
                        "status": "pending_poster",
                        "tips": [],
                        "copy": {"ai": None},
                        "assets": {},
                    },
                    "notify": False,
                },
            )
            self.assertEqual(r.status_code, 400, r.text)
            self.assertIn("ready", (r.json().get("detail") or "").lower())

if __name__ == "__main__":
    unittest.main()
