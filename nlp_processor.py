import os
import json
import httpx
import logging

logger = logging.getLogger(__name__)

class NLPProcessor:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = "https://api.openai.com/v1/chat/completions"

    def is_ready(self) -> bool:
        return bool(self.api_key)

    async def analyze_report(self, text: str, system_prompt: str) -> dict:
        """呼叫 OpenAI API 分析賽後報告並回傳 JSON"""
        if not self.is_ready():
            raise ValueError("尚未設定 OPENAI_API_KEY")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"分析以下賽馬報告:\n{text}"}
            ],
            "temperature": 0.2
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            
            content = data["choices"][0]["message"]["content"]
            try:
                result_json = json.loads(content)
                return result_json
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from AI response: {content}")
                return {"has_excuse": False, "excuse_stage": "none", "severity": 0.0, "reason": "JSON Parse Error"}
