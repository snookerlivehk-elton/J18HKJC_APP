"""Pytest safety: never touch live Ad API or production DATABASE_URL during tests."""
from __future__ import annotations

import os


def pytest_configure(config) -> None:  # noqa: ARG001
    # Cloud agent / local shells often inject real AD_API_* / DB secrets; blank them for unit tests.
    for key in (
        "AD_API_BASE_URL",
        "AD_API_PUSH_URL",
        "AD_PACKAGE_API_URL",
        "AD_PACKAGE_BASE_URL",
        "AD_API_PUBLIC_BASE",
        "GROK_BOT_WEBHOOK_URL",
        "SOCIAL_REPLY_BOT_WEBHOOK_URL",
        "REPLY_BOT_WEBHOOK_URL",
        # Allow unit tests to exercise push_ad_package_remote with patched httpx.
        "AD_DISABLE_REMOTE_PUSH",
        # Critical: real DATABASE_URL would dual-write test packages into production Postgres
        # (then ORDER BY updated_at makes junk become /v1/ads/latest).
        "DATABASE_URL",
        "DATABASE_URL_SYNC",
        "RAILWAY_DATABASE_URL",
    ):
        os.environ[key] = ""
    os.environ["USE_SQLITE"] = "true"
    os.environ.setdefault("AD_API_KEY", "test-secret-key")
    os.environ["AD_SKIP_AUTO_PUBLISH"] = "1"
    os.environ["AD_STORE_ENABLED"] = "true"
    # Default off；個別 remote-push unit test 會自行 patch 環境同 httpx
    os.environ["AD_DISABLE_REMOTE_PUSH"] = "1"
