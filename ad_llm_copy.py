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

# UI / API 用的語氣預設鍵值
TONE_PROFESSIONAL = "professional"
TONE_PASSIONATE = "passionate"
TONE_HIGH_INTERACTION = "high_interaction"
DEFAULT_TONE = TONE_HIGH_INTERACTION

TONE_PRESETS: Dict[str, Dict[str, str]] = {
    TONE_PROFESSIONAL: {
        "label": "專業型",
        "hint": "冷靜、事實導向，像資深馬評短評；少用感嘆，重點講走勢同理據。",
        "style_block": """語氣：專業型
- 口吻冷靜、乾淨，像香港馬評短評，唔好煽情。
- 標題可用疑問或焦點句，但保持克制。
- comment 以走勢／近績重點為主，少用感嘆號同口語助詞。""",
    },
    TONE_PASSIONATE: {
        "label": "熱情型",
        "hint": "有氣勢、帶期待感，像賽前「今晚有睇頭」短片旁白。",
        "style_block": """語氣：熱情型
- 有氣勢、帶期待，像賽前短片旁白，但唔好誇大成「必中」。
- 標題可以有節奏感同感染力。
- comment 可稍為有力，但仍要忠於近績事實。""",
    },
    TONE_HIGH_INTERACTION: {
        "label": "高互動型",
        "hint": "像香港人日常 FB／IG 貼文：易讚、易留言、易分享；有問題句或叫人一齊傾。",
        "style_block": """語氣：高互動型（預設）
- 寫成香港人日常 FB／IG／Threads 貼文，易讚、易留言、易分享。
- 標題最好帶提問、叫人留言或一齊睇（例如「今晚邊場先最有睇頭？」）。
- comment 短而有鉤，可留半句俾人回覆，但仍要忠於近績。
- 適量用香港口語助詞（啦／喎／囉／呀），唔好整篇口語到難讀。""",
    },
}


HK_WRITING_RULES = """文筆必須像「香港本地」發出嘅貼文，唔好似國語翻譯腔：
1) 用香港繁體書面語／港式社交文，詞彙同句式要似本地馬圈／粉專貼文。
2) 禁止國語翻譯腔同內地用語，例如：很不错、值得关注、本场赛事、实力强劲、不容小觑、
   表现亮眼、稳操胜券、各位粉丝、今天推荐、比较看好、值得一看、选手、赛况、干货。
3) 改用港式說法，例如：今晚、有睇頭、值得留意、形勢／走勢、望空、沿欄、爭勝機會、
   唔錯、有得傾、邊場、點睇、留意下。
4) 標題、subtitle、comment、basis 全部用繁體；可自然夾少少英文 hashtag，但正文唔好夾雜簡體。
5) 唔好寫到好似機械翻譯：避免「進行分析」「進行關注」「進行分享」呢類書面官腔。"""


DEFAULT_SOCIAL_SYSTEM_PROMPT = """你是香港賽馬社交媒體文案編輯。你會根據全賽日推介與官方賽績指引近績文字，
挑選 3 場最值得宣傳的精選場次，每場只揀 1 匹馬作重點評述。

你必須遵守：
1) 只能引用輸入中出現過的賽事、馬號、馬名、近績文字與事實，不可虛構。
2) 標題要吸引，但不可偏離事實原意，不可誇大成「穩膽」「必中」。
3) 每匹馬的 comment 必須是繁體中文，40 字內。
4) 優先挑選模型與 AI 都有支持、或官方近績文字有明確痕跡／走勢重點的場次。
5) hashtag 要適合香港賽馬與社交平台搜尋，8 至 15 個，避免重覆。
6) """ + HK_WRITING_RULES + """

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


def normalize_tone(tone: Optional[str]) -> str:
    key = str(tone or "").strip().lower()
    aliases = {
        "專業": TONE_PROFESSIONAL,
        "專業型": TONE_PROFESSIONAL,
        "professional": TONE_PROFESSIONAL,
        "熱情": TONE_PASSIONATE,
        "熱情型": TONE_PASSIONATE,
        "passionate": TONE_PASSIONATE,
        "高互動": TONE_HIGH_INTERACTION,
        "高互動型": TONE_HIGH_INTERACTION,
        "high_interaction": TONE_HIGH_INTERACTION,
        "high-interaction": TONE_HIGH_INTERACTION,
        "interactive": TONE_HIGH_INTERACTION,
    }
    return aliases.get(key, key if key in TONE_PRESETS else DEFAULT_TONE)


def tone_label(tone: Optional[str]) -> str:
    key = normalize_tone(tone)
    return TONE_PRESETS[key]["label"]


def tone_style_block(tone: Optional[str]) -> str:
    key = normalize_tone(tone)
    return TONE_PRESETS[key]["style_block"]


def build_system_prompt(tone: Optional[str] = None) -> str:
    return (
        DEFAULT_SOCIAL_SYSTEM_PROMPT
        + "\n\n"
        + tone_style_block(tone)
        + "\n\n請嚴格依上述語氣同香港文筆要求寫作。"
    )


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
        tone: Optional[str] = None,
    ) -> str:
        meeting = (copy_data or {}).get("meeting") or {}
        races = list((copy_data or {}).get("races") or [])
        form_map = self.load_formguide_map([str(r.get("race_id") or "") for r in races])
        tone_key = normalize_tone(tone)

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
                "writing_locale": "hong_kong_social",
                "avoid_mandarin_translation_tone": True,
            },
            "tone": tone_key,
            "tone_label": tone_label(tone_key),
            "custom_prompt": str(custom_prompt or "").strip(),
            "races": packed_races,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _normalize_result(
        self,
        raw: Dict[str, Any],
        custom_prompt: str,
        *,
        tone: Optional[str] = None,
    ) -> Dict[str, Any]:
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

        tone_key = normalize_tone(tone)
        return {
            "title": str(raw.get("title") or "").strip(),
            "subtitle": str(raw.get("subtitle") or "").strip(),
            "featured": clean_rows[:3],
            "hashtags": clean_tags[:15],
            "tone": tone_key,
            "tone_label": tone_label(tone_key),
            "custom_prompt": str(custom_prompt or "").strip(),
            "raw": raw,
        }

    def generate_social_copy(
        self,
        copy_data: Dict[str, Any],
        *,
        custom_prompt: str = "",
        tone: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.is_ready():
            raise ValueError("尚未設定 OPENAI_API_KEY")

        tone_key = normalize_tone(tone)
        user_payload = self.build_llm_payload(
            copy_data, custom_prompt=custom_prompt, tone=tone_key
        )
        messages = [{"role": "system", "content": build_system_prompt(tone_key)}]
        if str(custom_prompt or "").strip():
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "以下是使用者額外要求，需在不違反事實、不偏離香港文筆前提下盡量遵守：\n"
                        + custom_prompt.strip()
                    ),
                }
            )
        messages.append({"role": "user", "content": user_payload})

        # 高互動型略提高溫度，專業型偏低
        temperature = {
            TONE_PROFESSIONAL: 0.35,
            TONE_PASSIONATE: 0.55,
            TONE_HIGH_INTERACTION: 0.65,
        }.get(tone_key, 0.5)

        payload = {
            "model": self.nlp.model,
            "response_format": {"type": "json_object"},
            "messages": messages,
            "temperature": temperature,
        }
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(self.nlp.base_url, headers=self.nlp._headers(), json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        parsed = self.nlp._parse_content(content)
        normalized = self._normalize_result(parsed, custom_prompt, tone=tone_key)
        if len(normalized["featured"]) < 3:
            raise ValueError("LLM 未能產生足夠的 3 場精選，請稍後重試或調整提示詞")
        return normalized
