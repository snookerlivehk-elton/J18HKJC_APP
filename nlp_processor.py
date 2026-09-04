import os
import json
import httpx
import logging

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """你是一個專業的香港賽馬分析師。請閱讀以下賽馬報告，判斷是否遭遇影響名次的受阻。
嚴格輸出 JSON：
{"has_excuse": true/false, "excuse_stage": "early"|"middle"|"late"|"none", "severity": 0.0-1.0, "reason": "繁中簡述"}
規則：否定句（如「未有受困」）不算受阻；僅在確實影響發揮時 has_excuse=true。"""


class NLPProcessor:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        # 官方 OpenAI 預設 gpt-4o-mini；OpenRouter 請設 OPENAI_MODEL=openai/gpt-4o-mini 與 OPENAI_BASE_URL
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = os.getenv(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1/chat/completions",
        )

    def is_ready(self) -> bool:
        return bool(self.api_key)

    def _parse_content(self, content: str) -> dict:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from AI response: {content}")
            return {
                "has_excuse": False,
                "excuse_stage": "none",
                "severity": 0.0,
                "reason": "JSON Parse Error",
            }

    def _payload(self, text: str, system_prompt: str) -> dict:
        return {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"分析以下賽馬報告:\n{text}"},
            ],
            "temperature": 0.2,
        }

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def analyze_report(self, text: str, system_prompt: str) -> dict:
        """呼叫 OpenAI API 分析賽後報告並回傳 JSON（async）。"""
        if not self.is_ready():
            raise ValueError("尚未設定 OPENAI_API_KEY")

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                self.base_url, headers=self._headers(), json=self._payload(text, system_prompt)
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return self._parse_content(content)

    def analyze_report_sync(self, text: str, system_prompt: str = None) -> dict:
        """同步版，供 Streamlit 按鈕直接呼叫。"""
        if not self.is_ready():
            raise ValueError("尚未設定 OPENAI_API_KEY（請在 Railway Variables 設定）")
        prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        with httpx.Client(timeout=45.0) as client:
            response = client.post(
                self.base_url, headers=self._headers(), json=self._payload(text, prompt)
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return self._parse_content(content)
