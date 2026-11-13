"""Form AI：主端口欠费时改走备用 chat 端口，未配置则立刻停。"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import pandas as pd

from form_ai_analyst import BillingBlocked, FormAIAnalyst, is_billing_failure


class BillingDetectTest(unittest.TestCase):
    def test_402_is_billing(self):
        self.assertTrue(is_billing_failure(402, ""))

    def test_401_quota_is_billing(self):
        self.assertTrue(is_billing_failure(401, "insufficient credits"))

    def test_500_is_not_billing(self):
        self.assertFalse(is_billing_failure(500, "payment required"))


class FallbackSwitchTest(unittest.TestCase):
    def _analyst(self):
        analyst = FormAIAnalyst.__new__(FormAIAnalyst)
        analyst.nlp = type(
            "N",
            (),
            {
                "base_url": "https://openrouter.ai/api/v1/chat/completions",
                "api_key": "primary",
                "model": "deepseek/deepseek-chat",
                "_parse_content": staticmethod(json.loads),
            },
        )()
        analyst._fallback_latched = False
        analyst.is_ready = lambda: True
        analyst.build_user_payload = lambda *args, **kwargs: "user"
        return analyst

    def test_402_switches_and_latches_fallback(self):
        analyst = self._analyst()
        calls = []

        def chat(*, base_url, api_key, model, user):
            calls.append(base_url)
            if "openrouter" in base_url:
                raise BillingBlocked("402")
            return json.dumps(
                {
                    "summary": "备用评价",
                    "ai_score": 0.4,
                    "confidence": 0.6,
                    "tags": [],
                    "risks": [],
                    "evidence": [],
                }
            )

        analyst._chat_content = chat
        env = {
            "FORM_AI_FALLBACK_BASE_URL": "https://fallback.example/v1/chat/completions",
            "FORM_AI_FALLBACK_API_KEY": "sk-fallback",
            "FORM_AI_FALLBACK_MODEL": "gpt-4o-mini",
        }
        with patch.dict(os.environ, env, clear=False):
            first = analyst.analyze_one({}, pd.Series({"馬號": 1}), "")
            second = analyst.analyze_one({}, pd.Series({"馬號": 2}), "")
        self.assertEqual(first["provider"], "fallback")
        self.assertEqual(second["provider"], "fallback")
        self.assertEqual(calls[0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertTrue(all("fallback.example" in url for url in calls[1:]))
        self.assertTrue(analyst._fallback_latched)

    def test_402_without_fallback_stops(self):
        analyst = self._analyst()
        def chat(**kwargs):
            raise BillingBlocked("402")

        analyst._chat_content = chat
        with patch.dict(
            os.environ,
            {"FORM_AI_FALLBACK_BASE_URL": "", "FORM_AI_FALLBACK_API_KEY": ""},
            clear=False,
        ):
            with self.assertRaises(BillingBlocked) as ctx:
                analyst.analyze_one({}, pd.Series({"馬號": 1}), "")
        self.assertIn("FORM_AI_FALLBACK_BASE_URL", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
