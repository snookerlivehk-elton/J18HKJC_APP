"""Pytest safety: never remote-push ads to a live AD_API_BASE_URL during tests."""
from __future__ import annotations

import os


def pytest_configure(config) -> None:  # noqa: ARG001
    # Cloud agent / local shells often inject real AD_API_* secrets; blank them for unit tests.
    for key in (
        "AD_API_BASE_URL",
        "AD_API_PUSH_URL",
        "AD_PACKAGE_API_URL",
        "AD_PACKAGE_BASE_URL",
        "GROK_BOT_WEBHOOK_URL",
        "SOCIAL_REPLY_BOT_WEBHOOK_URL",
        "REPLY_BOT_WEBHOOK_URL",
    ):
        os.environ[key] = ""
    # Keep AUTH keys as test doubles unless a test overrides them.
    os.environ.setdefault("AD_API_KEY", "test-secret-key")
    os.environ["AD_SKIP_AUTO_PUBLISH"] = "1"
