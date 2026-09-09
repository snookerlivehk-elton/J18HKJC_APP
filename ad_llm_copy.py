"""廣告輸出：全賽日精選文案（標題／三場精選／hashtags）。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# 精選評述字數上限（繁體字元）
COMMENT_MAX_CHARS = 60

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

# 所有社交文案結尾固定加入（程式強制附加，唔依賴 LLM）
POST_FOOTER_LINES: List[str] = [
    "賽前十分鐘如有變動，將在j18.hk網站公佈,\n 想獲得臨場更多資訊或心水, 請即刻登錄j18.hk了解更多啦!!",
    "數據僅供參考，投注前請自行判斷。關注 J18.HK 獲取更多賽日速覽。",
]


def post_footer_text() -> str:
    return "\n\n".join(POST_FOOTER_LINES)


HK_WRITING_RULES = """文筆必須像「香港本地」發出嘅貼文，唔好似國語翻譯腔：
1) 用香港繁體書面語／港式社交文，詞彙同句式要似本地馬圈／粉專貼文。
2) 禁止國語翻譯腔同內地用語，例如：很不错、值得关注、本场赛事、实力强劲、不容小觑、
   表现亮眼、稳操胜券、各位粉丝、今天推荐、比较看好、值得一看、选手、赛况、干货。
3) 改用港式說法，例如：今晚、有睇頭、值得留意、形勢／走勢、望空、沿欄、爭勝機會、
   唔錯、有得傾、邊場、點睇、留意下。
4) 標題、subtitle、comment、basis 全部用繁體；可自然夾少少英文 hashtag，但正文唔好夾雜簡體。
5) 唔好寫到好似機械翻譯：避免「進行分析」「進行關注」「進行分享」呢類書面官腔。
6) 唔好自行加入免責／宣傳結尾；系統會在文末自動附加固定聲明。"""


DEFAULT_SOCIAL_SYSTEM_PROMPT = (
    "你是香港賽馬社交媒體文案編輯。你會根據全賽日「融合推介」名單與官方賽績指引近績文字，\n"
    "挑選 3 場最值得宣傳的精選場次，每場只揀 1 匹馬作重點評述。\n"
    "\n"
    "你必須遵守：\n"
    "1) 精選馬必須來自各場 candidates（以融合推介為主）；不可另選名單外的馬。\n"
    "2) comment 只能引用該馬的官方近績文字（form_text）事實，不可虛構，亦不要用勝率％湊字數。\n"
    "3) 標題要吸引，但不可偏離事實原意，不可誇大成「穩膽」「必中」。\n"
    f"4) 每匹馬的 comment 必須是繁體中文，{COMMENT_MAX_CHARS} 字內。\n"
    "5) 優先挑選：融合頭位、同時獲模型與 AI 支持（sources 含 model+ai）、或近績有明確痕跡／走勢重點的場次。\n"
    "6) hashtag 要適合香港賽馬與社交平台搜尋，8 至 15 個，避免重覆。\n"
    "7) " + HK_WRITING_RULES + "\n"
    "\n"
    "嚴格輸出 JSON（不要 markdown 代碼塊）：\n"
    "{\n"
    '  "title": "吸引但忠於事實的標題",\n'
    '  "subtitle": "可選，1 句補充",\n'
    '  "featured": [\n'
    "    {\n"
    '      "race_no": 1,\n'
    '      "race_id": "20260909HV01",\n'
    '      "horse_no": 3,\n'
    '      "horse_name": "馬名",\n'
    f'      "comment": "{COMMENT_MAX_CHARS}字內評述（忠於近績）",\n'
    '      "basis": "簡短說明為何揀這場"\n'
    "    }\n"
    "  ],\n"
    '  "hashtags": ["#J18", "#賽馬", "#賽馬貼士"]\n'
    "}\n"
    "featured 必須剛好 3 項；若資料不足也要盡量根據已有資料挑 3 項。"
)


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


def parse_llm_json(content: str) -> Dict[str, Any]:
    """Robust JSON parse for chat model outputs (fences / trailing text)."""
    text = str(content or "").strip()
    if not text:
        raise ValueError("LLM 回傳空白內容")

    candidates: List[str] = [text]
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        candidates.insert(0, fence.group(1).strip())

    # 擷取第一個 { ... } 區塊
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    last_err: Optional[Exception] = None
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise ValueError(f"LLM JSON 解析失敗：{last_err}")


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


def count_candidate_races(copy_data: Dict[str, Any]) -> int:
    n = 0
    for race in list((copy_data or {}).get("races") or []):
        if (
            list(race.get("fused_picks") or [])
            or list(race.get("model_picks") or [])
            or list(race.get("ai_picks") or [])
        ):
            n += 1
    return n


def format_social_post_text(social_data: Dict[str, Any]) -> str:
    """Facebook / IG 可貼文排版（含固定結尾）。"""
    lines: List[str] = []
    title = str((social_data or {}).get("title") or "").strip()
    if title:
        lines.append(title)
    subtitle = str((social_data or {}).get("subtitle") or "").strip()
    if subtitle:
        lines.append(subtitle)
    if lines:
        lines.append("")

    for item in list((social_data or {}).get("featured") or []):
        race_no = item.get("race_no") or "?"
        horse_no = item.get("horse_no") or "?"
        horse_name = item.get("horse_name") or ""
        comment = item.get("comment") or ""
        lines.append(f"第{race_no}場｜{horse_no} {horse_name}".rstrip())
        if comment:
            lines.append(str(comment))
        lines.append("")

    hashtags = list((social_data or {}).get("hashtags") or [])
    if hashtags:
        lines.append(" ".join(str(t) for t in hashtags))
        lines.append("")

    footer = str((social_data or {}).get("footer") or "").strip() or post_footer_text()
    lines.append(footer)
    return "\n".join(lines).strip() + "\n"


class AdSocialCopywriter:
    def __init__(self) -> None:
        self.nlp = NLPProcessor()
        self.engine = create_engine(DATABASE_URL_SYNC)

    def is_ready(self) -> bool:
        return self.nlp.is_ready()

    def _request_headers(self) -> Dict[str, str]:
        headers = dict(self.nlp._headers())
        # OpenRouter 建議帶 referer／title，可減少被拒機會
        if "openrouter.ai" in str(self.nlp.base_url or "").lower():
            headers.setdefault("HTTP-Referer", "https://j18.hk")
            headers.setdefault("X-Title", "J18AI Plus+ Ad Social Copy")
        return headers

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
            fused_picks = list(race.get("fused_picks") or [])
            model_picks = list(race.get("model_picks") or [])
            ai_picks = list(race.get("ai_picks") or [])
            model_hnos = {
                int(p.get("horse_no"))
                for p in model_picks
                if p.get("horse_no") is not None
            }
            ai_hnos = {
                int(p.get("horse_no"))
                for p in ai_picks
                if p.get("horse_no") is not None
            }

            # 主池：融合；無融合時退回模型 → AI（與海報對齊）
            primary = fused_picks or model_picks or ai_picks
            pool_source = (
                "fused" if fused_picks else ("model" if model_picks else "ai")
            )

            candidates: List[Dict[str, Any]] = []
            seen: set[int] = set()
            for p in primary[:4]:
                try:
                    horse_no = int(p.get("horse_no"))
                except Exception:
                    continue
                if horse_no in seen:
                    continue
                seen.add(horse_no)
                sources = [pool_source]
                if pool_source == "fused":
                    if horse_no in model_hnos:
                        sources.append("model")
                    if horse_no in ai_hnos:
                        sources.append("ai")
                form_text = form_map.get(race_id, {}).get(horse_no, "")
                if len(form_text) > 220:
                    form_text = form_text[:220] + "…"
                candidates.append(
                    {
                        "pool": pool_source,
                        "sources": sources,
                        "dual_track": (
                            pool_source == "fused"
                            and horse_no in model_hnos
                            and horse_no in ai_hnos
                        ),
                        "horse_no": horse_no,
                        "horse_name": str(p.get("horse_name") or "").strip(),
                        "tag": str(p.get("tag") or ""),
                        "share_pct": p.get("share_pct"),
                        "form_text": form_text,
                    }
                )

            packed_races.append(
                {
                    "race_no": race.get("race_no"),
                    "race_id": race_id,
                    "race_name": race.get("race_name") or "",
                    "distance": race.get("distance"),
                    "pick_pool": pool_source,
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
                "candidates_from_fused_primary": True,
                "comment_source": "form_text_only",
                "comment_max_chars": COMMENT_MAX_CHARS,
                "must_be_factual": True,
                "writing_locale": "hong_kong_social",
                "avoid_mandarin_translation_tone": True,
                "do_not_include_footer": True,
            },
            "tone": tone_key,
            "tone_label": tone_label(tone_key),
            "custom_prompt": str(custom_prompt or "").strip(),
            "races": packed_races,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _score_candidate(
        self, cand: Dict[str, Any], sources: set[str]
    ) -> Tuple[int, int, int, float]:
        """優先：融合池 → 雙軌共識 → 有近績 → 份額。"""
        in_fused = 1 if "fused" in sources or cand.get("pool") == "fused" else 0
        dual = 1 if ("model" in sources and "ai" in sources) else 0
        has_form = 1 if str(cand.get("form_text") or "").strip() else 0
        try:
            share = float(cand.get("share_pct") or 0.0)
        except Exception:
            share = 0.0
        return (in_fused, dual, has_form, share)

    def build_fallback_featured(
        self, copy_data: Dict[str, Any], *, limit: int = 3
    ) -> List[Dict[str, Any]]:
        """當 LLM 失敗／不足 3 場時，用融合推介（退回模型／AI）+ 近績自動補齊。"""
        race_rows: List[Dict[str, Any]] = []
        for race in list((copy_data or {}).get("races") or []):
            race_id = str(race.get("race_id") or "").strip()
            if not race_id:
                continue
            fused_picks = list(race.get("fused_picks") or [])
            model_picks = list(race.get("model_picks") or [])
            ai_picks = list(race.get("ai_picks") or [])
            primary = fused_picks or model_picks or ai_picks
            pool_source = (
                "fused" if fused_picks else ("model" if model_picks else "ai")
            )
            model_hnos = {
                int(p.get("horse_no"))
                for p in model_picks
                if p.get("horse_no") is not None
            }
            ai_hnos = {
                int(p.get("horse_no"))
                for p in ai_picks
                if p.get("horse_no") is not None
            }

            by_horse: Dict[int, Dict[str, Any]] = {}
            sources_map: Dict[int, set[str]] = {}
            for p in primary[:4]:
                try:
                    horse_no = int(p.get("horse_no"))
                except Exception:
                    continue
                sources = {pool_source}
                if pool_source == "fused":
                    if horse_no in model_hnos:
                        sources.add("model")
                    if horse_no in ai_hnos:
                        sources.add("ai")
                sources_map[horse_no] = sources
                if horse_no not in by_horse:
                    by_horse[horse_no] = {
                        "horse_no": horse_no,
                        "horse_name": str(p.get("horse_name") or "").strip(),
                        "tag": str(p.get("tag") or ""),
                        "share_pct": p.get("share_pct"),
                        "form_text": "",
                        "pool": pool_source,
                        "source": pool_source,
                    }
            if not by_horse:
                continue

            form_map = self.load_formguide_map([race_id]).get(race_id, {})
            best = None
            best_score = (-1, -1, -1, -1.0)
            for horse_no, cand in by_horse.items():
                cand["form_text"] = form_map.get(horse_no, "")
                score = self._score_candidate(cand, sources_map.get(horse_no, set()))
                if score > best_score:
                    best_score = score
                    best = cand
            if not best:
                continue

            form = str(best.get("form_text") or "").strip()
            if form:
                comment = form.replace("\n", " ")[:COMMENT_MAX_CHARS]
            else:
                tag = str(best.get("tag") or "推介").strip() or "推介"
                comment = f"{tag}走勢值得留意，今晚有得傾"[:COMMENT_MAX_CHARS]

            dual = "model" in sources_map.get(int(best["horse_no"]), set()) and "ai" in sources_map.get(
                int(best["horse_no"]), set()
            )
            basis = "自動補齊：融合推介"
            if pool_source != "fused":
                basis = f"自動補齊：{pool_source}（無融合名單）"
            elif dual:
                basis = "自動補齊：融合推介（雙軌共識）"

            race_rows.append(
                {
                    "race_no": race.get("race_no"),
                    "race_id": race_id,
                    "horse_no": best.get("horse_no"),
                    "horse_name": best.get("horse_name"),
                    "comment": comment,
                    "basis": basis,
                    "_score": best_score,
                }
            )

        race_rows.sort(key=lambda x: x.get("_score") or (0, 0, 0, 0), reverse=True)
        out = []
        for row in race_rows[:limit]:
            row = dict(row)
            row.pop("_score", None)
            out.append(row)
        return out

    def _normalize_result(
        self,
        raw: Dict[str, Any],
        custom_prompt: str,
        *,
        tone: Optional[str] = None,
        copy_data: Optional[Dict[str, Any]] = None,
        source: str = "llm",
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
                    "comment": comment[:COMMENT_MAX_CHARS],
                    "basis": str(item.get("basis") or "").strip(),
                }
            )

        # 不足 3 場時用本地推介補齊
        if len(clean_rows) < 3 and copy_data:
            for fb in self.build_fallback_featured(copy_data, limit=6):
                rid = str(fb.get("race_id") or "")
                if not rid or rid in seen_races:
                    continue
                seen_races.add(rid)
                clean_rows.append(fb)
                if len(clean_rows) >= 3:
                    break

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
        for default_tag in ("#J18", "#賽馬", "#賽馬貼士", "#J18HK", "#香港賽馬"):
            if default_tag not in clean_tags:
                clean_tags.append(default_tag)
            if len(clean_tags) >= 8:
                break

        tone_key = normalize_tone(tone)
        title = str(raw.get("title") or "").strip()
        subtitle = str(raw.get("subtitle") or "").strip()
        if not title:
            meeting = (copy_data or {}).get("meeting") or {}
            course = meeting.get("course") or ""
            racing_date = str(meeting.get("racing_date") or "")[:10]
            title = f"{racing_date} {course} 今晚邊場最有睇頭？".strip()

        footer = post_footer_text()
        result = {
            "title": title,
            "subtitle": subtitle,
            "featured": clean_rows[:3],
            "hashtags": clean_tags[:15],
            "footer": footer,
            "footer_lines": list(POST_FOOTER_LINES),
            "post_text": "",
            "tone": tone_key,
            "tone_label": tone_label(tone_key),
            "custom_prompt": str(custom_prompt or "").strip(),
            "source": source,
            "raw": raw,
        }
        result["post_text"] = format_social_post_text(result)
        return result

    def _chat_json(self, messages: List[Dict[str, str]], *, temperature: float) -> Dict[str, Any]:
        headers = self._request_headers()
        base_payload: Dict[str, Any] = {
            "model": self.nlp.model,
            "messages": messages,
            "temperature": temperature,
        }

        last_error: Optional[Exception] = None
        # 先試 json_object；若模型／閘道不支援再退回普通輸出
        for use_json_format in (True, False):
            payload = dict(base_payload)
            if use_json_format:
                payload["response_format"] = {"type": "json_object"}
            try:
                with httpx.Client(timeout=120.0) as client:
                    resp = client.post(self.nlp.base_url, headers=headers, json=payload)
                    if resp.status_code >= 400:
                        detail = (resp.text or "")[:400]
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}: {detail}",
                            request=resp.request,
                            response=resp,
                        )
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                return parse_llm_json(content)
            except Exception as e:  # noqa: BLE001
                last_error = e
                continue
        raise ValueError(f"呼叫 LLM 失敗：{last_error}")

    def generate_social_copy(
        self,
        copy_data: Dict[str, Any],
        *,
        custom_prompt: str = "",
        tone: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.is_ready():
            raise ValueError("尚未設定 OPENAI_API_KEY")

        n_cand = count_candidate_races(copy_data)
        if n_cand <= 0:
            raise ValueError(
                "copy.json 沒有可用推介場次。請先完成預測快照／重新生成廣告輸出，再試 AI 文案。"
            )

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
                        "注意：文末固定聲明由系統附加，請不要在 title／comment 重複寫免責或 j18.hk 宣傳段。\n"
                        + custom_prompt.strip()
                    ),
                }
            )
        messages.append({"role": "user", "content": user_payload})

        temperature = {
            TONE_PROFESSIONAL: 0.35,
            TONE_PASSIONATE: 0.55,
            TONE_HIGH_INTERACTION: 0.65,
        }.get(tone_key, 0.5)

        source = "llm"
        try:
            parsed = self._chat_json(messages, temperature=temperature)
        except Exception as llm_err:
            # LLM 失敗時仍可用本地推介出稿，避免整頁失敗
            fb = self.build_fallback_featured(copy_data, limit=3)
            if len(fb) < min(3, n_cand):
                raise ValueError(f"生成失敗：{llm_err}") from llm_err
            parsed = {
                "title": "",
                "subtitle": "（LLM 暫時未能完成，已用推介自動補齊精選）",
                "featured": fb,
                "hashtags": ["#J18", "#賽馬", "#賽馬貼士", "#J18HK"],
            }
            source = f"fallback:{llm_err}"

        normalized = self._normalize_result(
            parsed,
            custom_prompt,
            tone=tone_key,
            copy_data=copy_data,
            source=source,
        )
        if not normalized["featured"]:
            raise ValueError("未能產生精選場次，請確認 copy.json 有模型／AI 推介後重試")
        return normalized
