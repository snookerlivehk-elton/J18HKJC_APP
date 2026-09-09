"""廣告輸出：全賽日精選文案（標題／三場精選／hashtags）。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd
from sqlalchemy import bindparam, create_engine, text

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE
from nlp_processor import NLPProcessor

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )

SOCIAL_COPY_FILE = "social_copy.json"

DEFAULT_SOCIAL_SYSTEM_PROMPT = """你是香港賽馬社交媒體文案編輯。你會根據全賽日推介與官方賽績指引近績文字，
挑選 3 場最值得宣傳的精選場次，每場只揀 1 匹馬作重點評述。

你必須遵守：
1) 只能引用輸入中出現過的賽事、馬號、馬名、近績文字與事實，不可虛構。
2) 標題要吸引，但不可偏離事實原意，不可誇大成「穩膽」「必中」。
3) 每匹馬的 comment 必須是繁體中文，40 字內。
4) 優先挑選模型與 AI 都有支持、或官方近績文字有明確痕跡／走勢重點的場次。
5) hashtag 要適合香港賽馬與社交平台搜尋，8 至 15 個，避免重覆。

嚴格輸出 JSON：
{
  "title": "吸引但忠於事實的標題",
  "subtitle": "可選，1 句補充",
  "featured": [
    {
      "race_no": 1,
      "race_id": "20260909HV01",
      "horse_no": 3,
      "horse_name": "馬名",
      "comment": "40字內評述",
      "basis": "簡短說明為何揀這場"
    }
  ],
  "hashtags": ["#J18", "#賽馬", "#賽馬貼士"]
}
featured 必須剛好 3 項；若資料不足也要盡量根據已有資料挑 3 項。"""


def social_copy_path(output_root: Path) -> Path:
    return Path(output_root) / SOCIAL_COPY_FILE


def load_social_copy(output_root: Path) -> Dict[str, Any]:
    p = social_copy_path(output_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_social_copy(output_root: Path, data: Dict[str, Any]) -> Path:
    p = social_copy_path(output_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


class AdSocialCopywriter:
    def __init__(self) -> None:
        self.nlp = NLPProcessor()
        self.engine = create_engine(DATABASE_URL_SYNC)

    def is_ready(self) -> bool:
        return self.nlp.is_ready()

    def load_formguide_map(self, race_ids: List[str]) -> Dict[str, Dict[int, str]]:
        race_ids = [str(x) for x in race_ids if x]
        if not race_ids:
            return {}
        stmt = text(
            "SELECT race_id, horse_no, form_text "
            "FROM upcoming_formguide WHERE race_id IN :race_ids"
        ).bindparams(bindparam("race_ids", expanding=True))
        try:
            df = pd.read_sql(stmt, self.engine, params={"race_ids": race_ids})
        except Exception:
            return {}
        out: Dict[str, Dict[int, str]] = {}
        for row in df.itertuples():
            try:
                out.setdefault(str(row.race_id), {})[int(row.horse_no)] = str(
                    row.form_text or ""
                ).strip()
            except Exception:
                continue
        return out

    def build_llm_payload(
        self,
        copy_data: Dict[str, Any],
        *,
        custom_prompt: str = "",
    ) -> str:
        meeting = (copy_data or {}).get("meeting") or {}
        races = list((copy_data or {}).get("races") or [])
        form_map = self.load_formguide_map([str(r.get("race_id") or "") for r in races])

        packed_races: List[Dict[str, Any]] = []
        for race in races:
            race_id = str(race.get("race_id") or "")
            model_picks = list(race.get("model_picks") or [])
            ai_picks = list(race.get("ai_picks") or [])

            candidates: List[Dict[str, Any]] = []
            seen: set[tuple[int, str]] = set()
            for src, picks in (("model", model_picks), ("ai", ai_picks)):
                for p in picks[:4]:
                    try:
                        horse_no = int(p.get("horse_no"))
                    except Exception:
                        continue
                    horse_name = str(p.get("horse_name") or "").strip()
                    key = (horse_no, horse_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        {
                            "source": src,
                            "horse_no": horse_no,
                            "horse_name": horse_name,
                            "tag": str(p.get("tag") or ""),
                            "share_pct": p.get("share_pct"),
                            "form_text": form_map.get(race_id, {}).get(horse_no, ""),
                        }
                    )

            packed_races.append(
                {
                    "race_no": race.get("race_no"),
                    "race_id": race_id,
                    "race_name": race.get("race_name") or "",
                    "distance": race.get("distance"),
                    "candidates": candidates,
                }
            )

        payload = {
            "meeting": {
                "batch_id": meeting.get("batch_id"),
                "racing_date": meeting.get("racing_date"),
                "course": meeting.get("course"),
                "n_races": meeting.get("n_races"),
            },
            "rules": {
                "pick_three_races": True,
                "one_horse_per_race": True,
                "comment_max_chars": 40,
                "must_be_factual": True,
            },
            "custom_prompt": str(custom_prompt or "").strip(),
            "races": packed_races,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _normalize_result(self, raw: Dict[str, Any], custom_prompt: str) -> Dict[str, Any]:
        featured = raw.get("featured") if isinstance(raw.get("featured"), list) else []
        clean_rows = []
        seen_races: set[str] = set()
        for item in featured:
            if not isinstance(item, dict):
                continue
            race_id = str(item.get("race_id") or "").strip()
            if not race_id or race_id in seen_races:
                continue
            seen_races.add(race_id)
            comment = str(item.get("comment") or "").strip()
            clean_rows.append(
                {
                    "race_no": item.get("race_no"),
                    "race_id": race_id,
                    "horse_no": item.get("horse_no"),
                    "horse_name": str(item.get("horse_name") or "").strip(),
                    "comment": comment[:40],
                    "basis": str(item.get("basis") or "").strip(),
                }
            )

        hashtags = raw.get("hashtags") if isinstance(raw.get("hashtags"), list) else []
        clean_tags: List[str] = []
        for tag in hashtags:
            s = str(tag or "").strip()
            if not s:
                continue
            if not s.startswith("#"):
                s = "#" + s.lstrip("#")
            if s not in clean_tags:
                clean_tags.append(s)

        return {
            "title": str(raw.get("title") or "").strip(),
            "subtitle": str(raw.get("subtitle") or "").strip(),
            "featured": clean_rows[:3],
            "hashtags": clean_tags[:15],
            "custom_prompt": str(custom_prompt or "").strip(),
            "raw": raw,
        }

    def generate_social_copy(
        self,
        copy_data: Dict[str, Any],
        *,
        custom_prompt: str = "",
    ) -> Dict[str, Any]:
        if not self.is_ready():
            raise ValueError("尚未設定 OPENAI_API_KEY")

        user_payload = self.build_llm_payload(copy_data, custom_prompt=custom_prompt)
        messages = [{"role": "system", "content": DEFAULT_SOCIAL_SYSTEM_PROMPT}]
        if str(custom_prompt or "").strip():
            messages.append(
                {
                    "role": "system",
                    "content": f"以下是使用者額外要求，需在不違反事實前提下盡量遵守：\n{custom_prompt.strip()}",
                }
            )
        messages.append({"role": "user", "content": user_payload})

        payload = {
            "model": self.nlp.model,
            "response_format": {"type": "json_object"},
            "messages": messages,
            "temperature": 0.45,
        }
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(self.nlp.base_url, headers=self.nlp._headers(), json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        parsed = self.nlp._parse_content(content)
        normalized = self._normalize_result(parsed, custom_prompt)
        if len(normalized["featured"]) < 3:
            raise ValueError("LLM 未能產生足夠的 3 場精選，請稍後重試或調整提示詞")
        return normalized
