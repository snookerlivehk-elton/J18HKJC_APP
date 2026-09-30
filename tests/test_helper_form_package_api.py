"""helper-form 廣告包：產圖、package JSON、Ad API 端點。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "helper_form_ST_20261001_R1R2.json"


@pytest.fixture()
def helper_raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_publish_helper_form_package(helper_raw, tmp_path, monkeypatch):
    monkeypatch.setenv("AD_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("GROK_BOT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HELPER_FORM_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("AD_API_PUBLIC_BASE", "https://ads.example.com")

    from helper_form_package import (
        load_latest_package,
        package_id,
        public_payload,
        publish_helper_form_package,
    )

    result = publish_helper_form_package(
        racing_date="2026-10-01",
        course="ST",
        output_root=None,
        notify=False,
        force=True,
        raw=helper_raw,
    )
    assert result["ok"] is True
    assert result["status"] == "ready"
    assert result["id"] == "2026-10-01-st-helper-form"
    pkg = result["package"]
    assert len((pkg.get("assets") or {}).get("images") or []) == 2  # fixture 2 races → 1+1
    pub = public_payload(pkg)
    assert pub["purpose"] == "helper_form"
    assert pub["assets"]["images"][0]["url"].endswith("/image/1")
    latest = load_latest_package(ready_only=True)
    assert latest and latest["id"] == package_id("2026-10-01", "ST")


def test_helper_form_api_generate_and_latest(helper_raw, tmp_path, monkeypatch):
    monkeypatch.setenv("AD_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AD_API_KEY", "test-key")
    monkeypatch.setenv("AD_API_PUBLIC_BASE", "https://ads.example.com")
    monkeypatch.delenv("GROK_BOT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HELPER_FORM_WEBHOOK_URL", raising=False)

    # Avoid DB hydrate noise on lifespan
    monkeypatch.setenv("USE_SQLITE", "true")

    from helper_form_package import publish_helper_form_package

    publish_helper_form_package(
        racing_date="2026-10-01",
        course="ST",
        notify=False,
        force=True,
        raw=helper_raw,
    )

    import ad_api

    client = TestClient(ad_api.app)
    headers = {"Authorization": "Bearer test-key"}

    r = client.get("/v1/helper-form/latest", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "2026-10-01-st-helper-form"
    assert data["status"] == "ready"
    assert data["purpose"] == "helper_form"
    assert len(data["assets"]["images"]) >= 1

    img = client.get(f"/v1/helper-form/{data['id']}/image/1")
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/png")
    assert len(img.content) > 1000

    ids = client.get("/v1/helper-form", headers=headers)
    assert ids.status_code == 200
    assert data["id"] in ids.json()["ids"]
