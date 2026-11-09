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

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE, resolve_database_url
from nlp_processor import NLPProcessor

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = resolve_database_url()

SOCIAL_COPY_FILE = "social_copy.json"

# 精選評述字數上限（繁體字元）；需容納「近績事實 + 形勢論點」兩句
COMMENT_MAX_CHARS = 90
FORM_TEXT_PAYLOAD_MAX = 360

# 精選馬只准綜合（fused）頭 N 名，減少「tip 第3但文案當焦點」落差
def featured_fused_top_n() -> int:
    try:
        n = int(os.getenv("AD_FEATURED_FUSED_TOP_N", "2") or 2)
    except (TypeError, ValueError):
        n = 2
    return max(1, min(int(n), 4))


# 三場精選必須用唔同觀察角度（只作標籤／標題；唔再硬塞同一罐頭收尾）
OBSERVATION_ANGLES: List[Tuple[str, str, str]] = [
    ("pace", "步速", "步速"),
    ("position", "走位", "走位"),
    ("recovery", "恢復", "恢復"),
    ("distance", "路程", "路程"),
]
_ANGLE_BY_LABEL = {label: (key, label, hint) for key, label, hint in OBSERVATION_ANGLES}
# 清走舊版／模型抄寫嘅罐頭收尾（可重複出現）
_CANNED_TAIL_RE = re.compile(
    r"(?:[，,；;。.!！]|\s)*(?:"
    r"賽前可對照[^。\n]{0,40}"
    r"|值得留意其是否能夠挑戰領放馬"
    r"|值得留意其走勢是否會有改變。?"
    r")$"
)
# 兼容舊測試／呼叫名
_ANGLE_TAIL_RE = _CANNED_TAIL_RE

# UI / API 用的語氣預設鍵值（預設高互動型；選項順序以預設為先）
TONE_HIGH_INTERACTION = "high_interaction"
TONE_PROFESSIONAL = "professional"
TONE_PASSIONATE = "passionate"
DEFAULT_TONE = TONE_HIGH_INTERACTION

TONE_PRESETS: Dict[str, Dict[str, str]] = {
    TONE_HIGH_INTERACTION: {
        "label": "高互動型",
        "hint": "像資深練馬師同馬迷傾偈：易讚、易留言；用提問討論形勢。（預設）",
        "style_block": """語氣：高互動型（預設）
- 寫成資深練馬師喺 FB／IG 同馬迷傾賽前形勢，易讚、易留言、易分享。
- 標題最好帶提問（例如「今晚邊場步速同走位最值得一齊睇？」）。
- comment 短而有鉤，論點要講得出近績／步速／走位／路程，可留半句俾人回覆。
- 適量用香港口語助詞（啦／喎／囉／呀），唔好整篇口語到難讀。
- 禁止投注誘導：唔好寫心水、貼士、跟注、回報、必中。
- 禁止公開講「模型／AI／雙軌／份額」等黑箱字眼。""",
    },
    TONE_PROFESSIONAL: {
        "label": "專業型",
        "hint": "冷靜、事實導向，像資深練馬師賽前筆記；少用感嘆，重點講走勢論據。",
        "style_block": """語氣：專業型
- 口吻冷靜、乾淨，像資深練馬師寫賽前形勢短評，唔好煽情。
- 標題可用疑問或焦點句，但保持克制。
- comment 以近績跑法、步速、走位、路程適性為論據，少用感嘆號同口語助詞。
- 禁止投注誘導：唔好寫心水、貼士、跟注、回報、必中。
- 禁止公開講「模型／AI／雙軌／份額」等黑箱字眼。""",
    },
    TONE_PASSIONATE: {
        "label": "熱情型",
        "hint": "有氣勢、帶期待感，像練馬師賽前講評旁白（研究向）。",
        "style_block": """語氣：熱情型
- 有氣勢、帶期待，像資深練馬師賽前講評，但唔好誇大成「必中」或投注保證。
- 標題可以有節奏感同感染力，仍要鎖定「形勢觀察」。
- comment 可稍為有力，但仍要忠於近績／公開數據事實。
- 禁止投注誘導：唔好寫心水、貼士、跟注、回報、必中。
- 禁止公開講「模型／AI／雙軌／份額」等黑箱字眼。""",
    },
}

# 社交貼文固定骨架（方便一次複製發佈；唔依賴 LLM）
POST_GREETING = (
    "J18.hk 賽前形勢筆記：跟足公開近績同走勢對照，整理三場值得細睇嘅觀察，供各位參考。"
)
POST_CTA = "即刻打開手機瀏覽器登入 j18.hk 查看即時賽事數據。"
POST_DISCLAIMER = (
    "⚠️ 內容只供資料研究及參考，不構成投注建議；未滿18歲切勿參與賭博。"
)
POST_FOOTER_LINES: List[str] = [POST_CTA, POST_DISCLAIMER]

# 發佈用 hashtag（固定尾段；與正文研究向用語分開）
PUBLISH_HASHTAGS: List[str] = [
    "#香港賽馬",
    "#賽馬",
    "#賽馬貼士",
    "#賽馬心水",
    "#四重彩",
    "#賽馬會",
    "#賽事分析",
    "#賽馬預測",
    "#馬龍",
    "#賽馬賠率",
    "#賽馬直播",
    "#HKJC",
    "#獨贏",
    "#過關",
    "#J18賽馬",
    "#HorseRacingTips",
]

_WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
_VENUE_ZH = {"ST": "沙田", "HV": "跑馬地"}


def post_footer_text() -> str:
    return "\n\n".join(POST_FOOTER_LINES)


def post_greeting_text() -> str:
    return POST_GREETING


HK_WRITING_RULES = """文筆必須像「香港資深練馬師」寫畀馬迷睇嘅賽前形勢筆記，唔好似國語翻譯腔，亦唔好似賭波／貼士廣告：
1) 用香港繁體書面語／港式社交文；對外定位係「跟足公開近績同走勢嘅形勢分析」，不是投注服務。
2) 禁止國語翻譯腔同內地用語，例如：很不错、值得关注、本场赛事、实力强劲、不容小觑、
   表现亮眼、稳操胜券、各位粉丝、今天推荐、比较看好、值得一看、选手、赛况、干货。
3) 改用港式練馬師說法，例如：今晚、有睇頭、值得留意、形勢／走勢、望空、沿欄、步速、
   走位、路程適性、末段恢復、唔錯、有得傾、邊場、點睇、留意下。
4) 標題、subtitle、comment、basis 全部用繁體；可自然夾少少英文 hashtag，但正文唔好夾雜簡體。
5) 唔好寫到好似機械翻譯：避免「進行分析」「進行關注」「進行分享」呢類書面官腔。
6) 唔好自行加入免責／宣傳結尾；系統會在文末自動附加固定聲明。
7) 禁用／高風險語意（出現即改寫）：貼士、心水、推介注項、必中、穩贏、穩賺、回報率承諾、
   跟注、跟車、注碼、投注建議、買邊、賭、賠率比較、派彩、獎金、翻本、保證、內幕、
   「照住買」「跟住落」。只可寫成「形勢觀察／走勢對照／賽前筆記」。
8) 對外禁止黑箱用語：模型、AI、演算法、雙軌、綜合第N、份額、勝率％、系統推演、機器學習。
   揀馬可以靠內部 ranking 欄位，但寫出嚟必須翻譯成可核對嘅賽事論據（近績、步速、走位、路程）。
9) 優先用語：近績、上仗、步速、領放、走位、望空、沿欄、路程適性、末段、恢復、形勢、對照。
10) 正文唔好發明 hashtag；系統會在貼文最尾附加固定發佈標籤。"""


DEFAULT_SOCIAL_SYSTEM_PROMPT = (
    "你是一位香港資深練馬師，替 J18.hk 寫賽前形勢筆記畀馬迷睇。\n"
    "你內部會參考 candidates 的 ranking／共識欄位嚟揀場揀馬，但對外文案絕不可寫出「模型／AI／雙軌／份額」等字眼；\n"
    "馬迷要見到嘅係清晰、可核對嘅分析論點（近績跑法、步速、走位、路程適性、末段恢復）。\n"
    "不提供投注、賠率、注碼、跟注或任何賭博服務。\n"
    "\n"
    "固定貼文結構取向（系統會另加日期頭／開場白／CTA／免責／hashtag，你唔好重複寫免責全文）：\n"
    "A) 標題｜優先「三場形勢觀察：…」串起三個角度（步速／走位／路程／恢復）\n"
    "B) 副題｜一句說明跟足近績同走勢對照嘅賽前抽樣\n"
    "C) 本體｜三場形勢短評（有論據；禁止叫人下注）\n"
    "\n"
    "你必須遵守：\n"
    "1) 精選馬必須來自各場 candidates；不可另選名單外的馬。\n"
    "1b) candidates 已限頭名（fused top-N）；只能從中揀。\n"
    "2) comment 必須係「練馬師論點短評」，結構建議兩句：\n"
    "   (a) 近績／上仗具體跑法（只可改寫 form_text，不可虛構）；\n"
    "   (b) 一句今日形勢判斷：點解值得跟——用步速／走位／路程／恢復講清楚；\n"
    "   內部可用 dual_track、share_pct、fused_rank 幫助你判斷「共識強唔強」，但寫出嚟要翻譯成論據，\n"
    "   例如「近績兩仗同程領放穩定」「末段恢復有落差，路程對照值得跟」；\n"
    "   禁止寫：模型、AI、雙軌、綜合第N、份額X、勝率％。\n"
    "2b) 這是「賽前」筆記：近績跑法必須標明「近績／上仗／過往」；\n"
    "   禁止用「本場」指未跑場次；禁止寫到似已開跑或完賽。\n"
    "2c) 三場 featured 必須用唔同觀察角度：步速／走位／恢復／路程；每場 JSON 加 "
    '"angle"（四選一）。收尾要自然對應該角度，三場句式唔好雷同；\n'
    "   禁止罐頭句「賽前可對照…會否延續／重現／改善／發揮」。\n"
    "2d) basis 用練馬師語言寫核對點（例如「1400米近績兩連勝均領放｜步速控制清楚」），\n"
    "   禁止「綜合頭位／雙軌／份額／模型與AI支持」呢類內部術語。\n"
    "3) 標題要吸引，但不可偏離事實，不可誇大成「穩膽」「必中」，亦不可出現貼士／心水口吻；"
    "優先格式：「三場形勢觀察：步速、走位與路程適應」（按實際 angle 改寫）。\n"
    f"4) 每匹馬的 comment 必須是繁體中文，{COMMENT_MAX_CHARS} 字內。\n"
    "5) 優先挑選：近績痕跡清晰、多方數據共識較強（內部 dual_track／高 share）、或路程／班次有對照價值。\n"
    "6) 唔好輸出大量 hashtag（系統會附加固定發佈標籤）；JSON hashtags 可留空或少寫。\n"
    "7) " + HK_WRITING_RULES + "\n"
    "\n"
    "嚴格輸出 JSON（不要 markdown 代碼塊）：\n"
    "{\n"
    '  "title": "三場形勢觀察：步速、走位與路程適應",\n'
    '  "subtitle": "跟足近績跑法、步速同路程適性，抽出三組值得跟進嘅賽前觀察。",\n'
    '  "featured": [\n'
    "    {\n"
    '      "race_no": 1,\n'
    '      "race_id": "20260909HV01",\n'
    '      "horse_no": 3,\n'
    '      "horse_name": "馬名",\n'
    f'      "comment": "{COMMENT_MAX_CHARS}字內：近績事實 + 形勢論點（唔好提模型）",\n'
    '      "angle": "步速",\n'
    '      "basis": "例如：1400米近績兩連勝均領放｜步速控制清楚"\n'
    "    }\n"
    "  ],\n"
    '  "hashtags": []\n'
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


_PUBLIC_SYSTEM_MARKERS = (
    "LLM 暫時未能",
    "已用推介自動補齊",
    "自動補齊精選",
    "自動補齊：",
)


def _is_system_subtitle(text: str) -> bool:
    s = str(text or "")
    return any(m in s for m in _PUBLIC_SYSTEM_MARKERS)


# 近績跑法用詞：出現時若無「近績／上仗」前綴，易被讀成今晚已經開跑
_RACE_RUNNING_MARKERS = (
    "出閘",
    "直路上",
    "直路",
    "領放",
    "二疊",
    "沿欄",
    "仍居第",
    "居最後",
    "保持同速",
    "進一步落後",
    "進展不大",
    "走二疊",
)
_PAST_FORM_PREFIX_RE = re.compile(r"^(近績|上仗|往績|過往|歷史)")
_GENERIC_CHALLENGE_TAIL = "值得留意其是否能夠挑戰領放馬"


def _needs_prerace_form_frame(text: str) -> bool:
    s = str(text or "").strip()
    if not s or _PAST_FORM_PREFIX_RE.match(s):
        return False
    return any(m in s for m in _RACE_RUNNING_MARKERS)


def _strip_canned_endings(text: str) -> str:
    """重複清走「賽前可對照…」等罐頭收尾，避免 LLM＋後處理疊句。"""
    s = str(text or "").strip()
    for _ in range(6):
        nxt, n = _CANNED_TAIL_RE.subn("", s)
        if n == 0:
            break
        s = nxt.rstrip("，,；;。.!！ ")
    return s


def _frame_as_prerace_form_comment(text: str) -> str:
    """把易被誤讀成「本場賽況」的近績句，改成明確賽前／近績語氣。"""
    s = _strip_canned_endings(text)
    if not s:
        return s
    # 弱化重複罐頭收尾（唔再改寫成另一句罐頭）
    if s.endswith(_GENERIC_CHALLENGE_TAIL):
        s = s[: -len(_GENERIC_CHALLENGE_TAIL)].rstrip("，,；; ")
        if not s:
            s = "近績步速走位值得跟進"
    if not _needs_prerace_form_frame(s):
        return s
    if s.startswith("本場"):
        s = "近績顯示" + s[2:]
    elif not _PAST_FORM_PREFIX_RE.match(s):
        s = "近績：" + s
    return s


def _detect_observation_angle(text: str, preferred: Optional[str] = None) -> str:
    if preferred and preferred in _ANGLE_BY_LABEL:
        return preferred
    s = str(text or "")
    if any(k in s for k in ("出閘", "步速", "快步", "中等步")):
        return "步速"
    if any(k in s for k in ("走位", "二疊", "沿欄", "領放", "直路")):
        return "走位"
    if any(k in s for k in ("恢復", "追回", "續進", "末段")):
        return "恢復"
    if any(k in s for k in ("路程", "適性", "距離", "米")):
        return "路程"
    return preferred or "步速"


def _truncate_comment(text: str, *, limit: int = COMMENT_MAX_CHARS) -> str:
    """超長時優先喺標點切斷，避免「走」「恢復節奏值得」呢類半截句。"""
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    # 由後向前找句讀斷點
    for i in range(len(cut) - 1, max(12, len(cut) // 2), -1):
        if cut[i] in "。！？；;，,":
            return cut[:i].rstrip("，,；; ")
    return cut.rstrip("，,；;。.!！ ")


def _apply_angle_ending(comment: str, angle_label: str) -> str:
    """清走罐頭收尾並截斷字數；不再硬塞相同「賽前可對照」尾句。"""
    s = _strip_canned_endings(comment)
    # angle_label 只作元數據；保留參數以兼容舊呼叫
    _ = angle_label
    return _truncate_comment(s, limit=COMMENT_MAX_CHARS)


def _assign_distinct_angles(rows: List[Dict[str, Any]]) -> None:
    """就地為 featured 分配互唔重複嘅觀察角度，並清走罐頭收尾。"""
    used: set[str] = set()
    for i, row in enumerate(rows):
        preferred = str(row.get("angle") or "").strip()
        if preferred not in _ANGLE_BY_LABEL:
            preferred = _detect_observation_angle(str(row.get("comment") or ""), None)
        if preferred in used:
            preferred = ""
            for _key, label, _hint in OBSERVATION_ANGLES:
                if label not in used:
                    preferred = label
                    break
            if not preferred:
                preferred = OBSERVATION_ANGLES[i % len(OBSERVATION_ANGLES)][1]
        used.add(preferred)
        row["angle"] = preferred
        row["comment"] = _apply_angle_ending(str(row.get("comment") or ""), preferred)


def _primary_picks_for_race(race: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    fused = list(race.get("fused_picks") or [])
    model = list(race.get("model_picks") or [])
    ai = list(race.get("ai_picks") or [])
    if fused:
        return fused, "fused"
    if model:
        return model, "model"
    return ai, "ai"


def _race_pick_index(copy_data: Optional[Dict[str, Any]]) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """race_id → horse_no → meta（fused_rank / dual_track / score…），只含 top-N。"""
    top_n = featured_fused_top_n()
    out: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for race in list((copy_data or {}).get("races") or []):
        race_id = str(race.get("race_id") or "").strip()
        if not race_id:
            continue
        primary, pool = _primary_picks_for_race(race)
        model_hnos = {
            int(p.get("horse_no"))
            for p in list(race.get("model_picks") or [])
            if p.get("horse_no") is not None
        }
        ai_hnos = {
            int(p.get("horse_no"))
            for p in list(race.get("ai_picks") or [])
            if p.get("horse_no") is not None
        }
        fused_list = list(race.get("fused_picks") or [])
        fused_rank_map = {}
        for idx, p in enumerate(fused_list):
            try:
                fused_rank_map[int(p.get("horse_no"))] = idx + 1
            except Exception:
                continue
        bucket: Dict[int, Dict[str, Any]] = {}
        for idx, p in enumerate(primary[:top_n]):
            try:
                horse_no = int(p.get("horse_no"))
            except Exception:
                continue
            sources = {pool}
            if pool == "fused":
                if horse_no in model_hnos:
                    sources.add("model")
                if horse_no in ai_hnos:
                    sources.add("ai")
            dual = "model" in sources and "ai" in sources
            try:
                share = float(p.get("share_pct") or 0.0)
            except Exception:
                share = 0.0
            in_fused = 1 if pool == "fused" or horse_no in fused_rank_map else 0
            score = (in_fused, 1 if dual else 0, 1, share)
            bucket[horse_no] = {
                "horse_no": horse_no,
                "horse_name": str(p.get("horse_name") or "").strip(),
                "tag": str(p.get("tag") or ""),
                "share_pct": p.get("share_pct"),
                "pool": pool,
                "sources": sorted(sources),
                "dual_track": dual,
                "fused_rank": fused_rank_map.get(horse_no),
                "pool_rank": idx + 1,
                "score": list(score),
            }
        out[race_id] = bucket
    return out


def _format_pick_reason_label(reason: Dict[str, Any]) -> str:
    parts: List[str] = []
    fr = reason.get("fused_rank")
    if fr:
        parts.append(f"綜合第{fr}")
    else:
        parts.append(f"{reason.get('pool') or '名單'}第{reason.get('pool_rank') or '?'}")
    if reason.get("dual_track"):
        parts.append("雙軌")
    score = reason.get("score")
    if isinstance(score, (list, tuple)) and score:
        parts.append(f"score={tuple(score)}")
    by = str(reason.get("selected_by") or "")
    if by.startswith("fallback"):
        parts.append("Fallback揀")
    elif by == "remapped":
        parts.append("已校正至頭N")
    else:
        parts.append("LLM揀")
    angle = reason.get("angle")
    if angle:
        parts.append(f"角度:{angle}")
    return "｜".join(parts)


def _build_pick_reason(
    *,
    meta: Optional[Dict[str, Any]],
    selected_by: str,
    angle: str = "",
) -> Dict[str, Any]:
    meta = dict(meta or {})
    reason = {
        "selected_by": selected_by,
        "pool": meta.get("pool"),
        "fused_rank": meta.get("fused_rank"),
        "pool_rank": meta.get("pool_rank"),
        "dual_track": bool(meta.get("dual_track")),
        "score": list(meta.get("score") or []),
        "share_pct": meta.get("share_pct"),
        "sources": list(meta.get("sources") or []),
        "angle": angle or "",
    }
    reason["label"] = _format_pick_reason_label(reason)
    return reason


def _compress_form_snippet(form_text: str, *, max_chars: int = 70) -> str:
    """從官方近績抽出一句可讀摘要，去掉馬名行／技術碼。"""
    raw = str(form_text or "").strip()
    if not raw:
        return ""
    # 取第一段有內容的近績（通常是最近一仗）
    parts = [p.strip() for p in re.split(r"[\n；;]+", raw) if p.strip()]
    body = ""
    for p in parts:
        if p.startswith("馬名"):
            continue
        body = p
        break
    if not body:
        body = parts[0] if parts else raw
    body = re.sub(r"^\[[^\]]+\]\s*", "", body)
    body = re.sub(r"能量\s*\d+%?", "", body)
    body = re.sub(r"\([^)]*\dW[^)]*\)", "", body)
    body = re.sub(r"[ \t]{2,}", " ", body).strip(" ，,;；")
    if len(body) > max_chars:
        body = body[:max_chars].rstrip("，,；;。.!！ ")
    return body


def _analysis_basis_line(
    *,
    pool_source: str,
    dual: bool,
    fused_rank: Optional[int] = None,
    share_pct: Any = None,
    distance: Any = None,
    tag: str = "",
    form_hint: str = "",
    auto: bool = False,
) -> str:
    """對外 basis：練馬師可核對論點；唔暴露模型／雙軌／份額。"""
    bits: List[str] = []
    hint = _strip_public_jargon(_compress_form_snippet(form_hint, max_chars=28))
    if hint:
        bits.append(hint)
    if distance:
        bits.append(f"{distance}米路程對照")
    if dual:
        bits.append("多方數據走勢一致")
    elif fused_rank == 1 or (pool_source == "fused" and fused_rank):
        bits.append("近績同走勢對照突出")
    tag_s = str(tag or "").strip()
    if tag_s and tag_s not in {"推介", "觀察", "爭勝"}:
        bits.append(tag_s)
    if auto and not bits:
        bits.append("近績走勢補齊")
    # share_pct／pool 只作內部判斷，唔寫入對外 basis
    _ = share_pct
    return "｜".join(bits) if bits else "近績走勢對照"


# 公開貼文禁用黑箱用語（揀馬仍可用內部欄位）
_PUBLIC_JARGON_RE = re.compile(
    r"(?:"
    r"模型(?:綜合|推演|觀察|分析|支持)?"
    r"|AI"
    r"|雙軌(?:共識|支持)?"
    r"|綜合第\s*\d+"
    r"|綜合／雙軌"
    r"|綜合份額(?:約)?"
    r"|份額\s*(?:約)?\s*\d+(?:\.\d+)?"
    r"|勝率\s*\d+(?:\.\d+)?%?"
    r"|演算法"
    r"|機器學習"
    r"|fused"
    r"|dual[_\s-]?track"
    r"|share[_\s-]?pct"
    r")",
    flags=re.IGNORECASE,
)


def _strip_public_jargon(text: str) -> str:
    """清走公開文案入面嘅模型／雙軌／份額等黑箱字眼。"""
    s = str(text or "").strip()
    if not s:
        return s
    s = _PUBLIC_JARGON_RE.sub("", s)
    s = re.sub(r"[；;]{2,}", "；", s)
    s = re.sub(r"[，,]{2,}", "，", s)
    s = re.sub(r"（\s*）|\(\s*\)", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\s*[，,；;]\s*$", "", s)
    s = re.sub(r"^[，,；;]\s*", "", s)
    s = re.sub(r"([，,；;])\s*([，,；;])+", r"\1", s)
    return s.strip(" ，,;；")


def _humanize_comment(text: str, *, daypart: str = "今日") -> str:
    """精選評述轉人話：去掉能量／走位技術字串，日馬唔用今晚，並標明近績時間線。"""
    body = str(text or "").strip().replace("\n", " ")
    body = re.sub(r"能量\s*[：:]\s*[\d.]+%?", "", body)
    body = re.sub(r"\b\d+W\d+P\d+S\b", "", body, flags=re.I)
    body = re.sub(r"\b\d+W\d+W\b", "", body, flags=re.I)
    body = re.sub(r"share[_\s-]?pct\s*[：:=]?\s*[\d.]+", "", body, flags=re.I)
    body = re.sub(r"[ \t]{2,}", " ", body).strip(" ，,;；")
    if daypart in {"今日", "聽日"}:
        body = body.replace("今晚", daypart).replace("今夜", daypart)
        if daypart == "聽日":
            body = body.replace("今日", "聽日")
    if not body or len(body) < 4:
        return f"{daypart}近績走勢值得留意，有得傾"
    body = _frame_as_prerace_form_comment(body)
    body = _strip_public_jargon(_strip_canned_endings(body))
    if not body or len(body) < 4:
        return f"{daypart}近績走勢值得留意，有得傾"
    return _truncate_comment(body, limit=COMMENT_MAX_CHARS)


def _meeting_daypart_from_copy(copy_data: Optional[Dict[str, Any]]) -> str:
    from datetime import datetime, timedelta, timezone

    meeting = (copy_data or {}).get("meeting") or {}
    if _meeting_is_night(meeting):
        return "今晚"
    race_date = str(meeting.get("racing_date") or meeting.get("date") or "")[:10]
    if race_date:
        try:
            hk = timezone(timedelta(hours=8))
            rd = datetime.strptime(race_date, "%Y-%m-%d").date()
            if rd > datetime.now(hk).date():
                return "聽日"
        except Exception:
            pass
    return "今日"


def _meeting_blob(
    copy_data: Optional[Dict[str, Any]] = None,
    social_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """合併 meeting；social 空白欄位唔好覆蓋 copy／package 已有值。"""
    meeting: Dict[str, Any] = {}
    meeting.update(dict((copy_data or {}).get("meeting") or {}))
    for key, value in dict((social_data or {}).get("meeting") or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        meeting[key] = value
    # social 常只帶 course／racing_date；保留 copy 的 session／start_time／theme
    return meeting


def _venue_zh_from_meeting(meeting: Dict[str, Any]) -> str:
    raw = str(
        meeting.get("venue")
        or meeting.get("venue_name")
        or meeting.get("course")
        or meeting.get("venue_code")
        or ""
    ).strip()
    up = raw.upper()
    if up in _VENUE_ZH:
        return _VENUE_ZH[up]
    if "沙田" in raw or up == "ST":
        return "沙田"
    if "跑馬地" in raw or "谷" in raw or up == "HV":
        return "跑馬地"
    return raw or "沙田"


def _weekday_zh_from_meeting(meeting: Dict[str, Any]) -> str:
    wd = str(meeting.get("weekday") or "").strip()
    if wd:
        return wd
    race_date = str(meeting.get("racing_date") or meeting.get("date") or "")[:10]
    try:
        from datetime import datetime

        return _WEEKDAY_ZH[datetime.strptime(race_date, "%Y-%m-%d").weekday()]
    except Exception:
        return ""


def _date_zh_from_meeting(meeting: Dict[str, Any]) -> str:
    race_date = str(meeting.get("racing_date") or meeting.get("date") or "")[:10]
    try:
        from datetime import datetime

        dt = datetime.strptime(race_date, "%Y-%m-%d")
        return f"{dt.year}年{dt.month}月{dt.day}日"
    except Exception:
        return race_date


def _clock_hhmm_from_meeting(meeting: Dict[str, Any], *, is_night: bool) -> str:
    """開跑時間顯示成 HH:MM（例 18:45）。"""
    # 優先 package 的 start_time（約下午1時）；post_time 常係舊推斷值
    candidates = [
        meeting.get("start_time"),
        meeting.get("first_post_time"),
        meeting.get("race_time"),
        meeting.get("post_time"),
    ]
    for raw in candidates:
        s = str(raw or "").strip()
        if not s:
            continue
        # ISO / datetime
        m = re.search(r"T(\d{2}):(\d{2})", s)
        if m:
            return f"{m.group(1)}:{m.group(2)}"
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
        # 約晚上7時15分／下午1時
        m = re.search(r"(晚上|下午|上午)?\s*(\d{1,2})\s*時\s*(\d{1,2})?\s*分?", s)
        if m:
            hh = int(m.group(2))
            mm = int(m.group(3) or 0)
            period = m.group(1) or ""
            if period == "晚上" and hh < 12:
                hh += 12
            elif period == "下午" and hh < 12:
                hh += 12
            elif period == "上午" and hh == 12:
                hh = 0
            return f"{hh:02d}:{mm:02d}"
    return "18:45" if is_night else "13:00"


def _meeting_is_night(meeting: Dict[str, Any]) -> bool:
    session = str(
        meeting.get("session") or meeting.get("theme") or meeting.get("day_night") or ""
    ).strip()
    course = str(meeting.get("course") or meeting.get("venue_code") or "").upper()
    low = session.lower()
    if (
        "夜" in session
        or low in {"night", "eve", "evening"}
        or "night" in low
    ):
        return True
    if (
        "日" in session
        or low in {"day", "daytime", "afternoon"}
        or "day" in low
    ):
        return False
    # 跑馬地缺 session 時多數夜賽；沙田缺省當日賽
    return course == "HV"


def format_meeting_header_line(
    copy_data: Optional[Dict[str, Any]] = None,
    social_data: Optional[Dict[str, Any]] = None,
) -> str:
    """例：2026年10月28日, 星期三, 沙田, 18:45"""
    meeting = _meeting_blob(copy_data, social_data)
    date_zh = _date_zh_from_meeting(meeting)
    weekday = _weekday_zh_from_meeting(meeting)
    venue = _venue_zh_from_meeting(meeting)
    clock = _clock_hhmm_from_meeting(meeting, is_night=_meeting_is_night(meeting))
    parts = [p for p in (date_zh, weekday, venue, clock) if p]
    return ", ".join(parts)


def _publish_hashtags_for_copy(
    copy_data: Optional[Dict[str, Any]] = None, extra: Optional[List[str]] = None
) -> List[str]:
    """發佈 hashtag 用固定清單；extra 只作相容，唔再改研究向短標籤。"""
    tags = list(PUBLISH_HASHTAGS)
    seen = set(tags)
    for t in list(extra or []):
        s = str(t or "").strip().replace("＃", "#")
        if not s:
            continue
        if not s.startswith("#"):
            s = "#" + s.lstrip("#")
        if s in seen:
            continue
        # 避免舊研究向短標籤污染發佈清單
        if s in {"#J18", "#賽事數據", "#模型分析", "#公開數據", "#日馬", "#夜馬", "#沙田", "#跑馬地"}:
            continue
        tags.append(s)
        seen.add(s)
    return tags


def _correct_hashtags_in_text(body: str, copy_data: Optional[Dict[str, Any]]) -> str:
    """兼容舊貼文：若正文仍有日夜／場地短標籤，按賽日校正。"""
    text = str(body or "").replace("＃", "#")
    meeting = (copy_data or {}).get("meeting") or {}
    course = str(meeting.get("course") or meeting.get("venue_code") or "").upper()
    session = str(meeting.get("session") or "")
    is_night = (
        "夜" in session
        or session.lower() == "night"
        or (course == "HV" and "日" not in session)
    )
    if is_night:
        text = text.replace("#日馬", "#夜馬")
    else:
        text = text.replace("#夜馬", "#日馬")
    if course in {"ST", "沙田"} or "沙田" in session:
        text = text.replace("#跑馬地", "#沙田")
    elif course in {"HV", "跑馬地", "谷"} or "跑馬地" in session or "谷" in session:
        text = text.replace("#沙田", "#跑馬地")
    return text


def _race_no_sort_key(item: Dict[str, Any]) -> tuple:
    """場次號升序；缺號排後。"""
    raw = (item or {}).get("race_no")
    try:
        return (0, int(raw))
    except (TypeError, ValueError):
        return (1, str(raw or ""))


def sort_featured_by_race_no(
    featured: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """精選按場次號排列（貼文閱讀順序：第7→第8→第9）。"""
    rows = [dict(x) for x in list(featured or []) if isinstance(x, dict)]
    rows.sort(key=_race_no_sort_key)
    return rows


def default_focus_title(featured: Optional[List[Dict[str, Any]]] = None) -> str:
    """按三場 angle 組成「三場焦點數據觀察：…」標題（先按場次排序）。"""
    angles: List[str] = []
    seen = set()
    for item in sort_featured_by_race_no(featured):
        angle = str(
            (item or {}).get("angle")
            or ((item or {}).get("pick_reason") or {}).get("angle")
            or ""
        ).strip()
        if not angle or angle in seen:
            continue
        seen.add(angle)
        angles.append(angle)
    if len(angles) >= 3:
        return f"三場形勢觀察：{angles[0]}、{angles[1]}與{angles[2]}"
    if len(angles) == 2:
        return f"三場形勢觀察：{angles[0]}與{angles[1]}"
    if len(angles) == 1:
        return f"三場形勢觀察：{angles[0]}"
    return "三場形勢觀察：步速、走位與路程適應"


DEFAULT_FOCUS_SUBTITLE = "跟足近績跑法、步速同路程適性，抽出三組值得跟進嘅賽前觀察。"


def format_social_post_text(
    social_data: Dict[str, Any], *, copy_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Facebook / IG 一次複製發佈格式：

    日期頭
    開場白
    標題／副題
    三場精選
    CTA + 免責
    hashtags
    """
    merged_copy = dict(copy_data or {})
    if "meeting" not in merged_copy:
        merged_copy["meeting"] = {}
    # 用 _meeting_blob 合併，避免 social 空白欄位沖掉 session／start_time
    merged_copy["meeting"] = _meeting_blob(merged_copy, social_data)
    daypart = _meeting_daypart_from_copy(merged_copy)
    lines: List[str] = []

    header = format_meeting_header_line(merged_copy, social_data)
    if header:
        lines.append(header)
        lines.append("")

    lines.append(post_greeting_text())
    lines.append("")

    # 貼文一律按場次號升序，唔跟模型分數揀選順序
    featured = sort_featured_by_race_no((social_data or {}).get("featured") or [])
    title = str((social_data or {}).get("title") or "").strip()
    # 舊標題統一成練馬師口吻「三場形勢觀察」
    rewrite_focus = (
        (not title)
        or title.startswith("三場數據焦點")
        or title.startswith("三場焦點數據觀察")
        or ("模型" in title)
    )
    if rewrite_focus:
        title = default_focus_title(featured)
    if daypart in {"今日", "聽日"}:
        title = title.replace("今晚", daypart).replace("今夜", daypart)
        if daypart == "聽日":
            title = title.replace("今日", "聽日")
    lines.append(title)

    subtitle = str((social_data or {}).get("subtitle") or "").strip()
    if (
        rewrite_focus
        or (not subtitle)
        or _is_system_subtitle(subtitle)
        or subtitle.startswith("綜合分析名單")
        or subtitle.startswith("綜合模型")
        or ("模型" in subtitle)
    ):
        subtitle = DEFAULT_FOCUS_SUBTITLE
    else:
        subtitle = _strip_public_jargon(subtitle) or DEFAULT_FOCUS_SUBTITLE
    if daypart in {"今日", "聽日"}:
        subtitle = subtitle.replace("今晚", daypart).replace("今夜", daypart)
        if daypart == "聽日":
            subtitle = subtitle.replace("今日", "聽日")
    lines.append(subtitle)
    lines.append("")

    for item in featured:
        race_no = item.get("race_no") or "?"
        horse_no = item.get("horse_no") or "?"
        horse_name = item.get("horse_name") or ""
        comment = _humanize_comment(item.get("comment") or "", daypart=daypart)
        lines.append(f"第{race_no}場｜{horse_no} {horse_name}".rstrip())
        if comment:
            lines.append(str(comment))
        lines.append("")

    # 發佈模板固定 CTA／免責；忽略舊 social 長 footer，方便一次複製
    lines.append(post_footer_text())
    lines.append("")

    hashtags = _publish_hashtags_for_copy(merged_copy, extra=None)
    if hashtags:
        lines.append(" ".join(str(t) for t in hashtags))

    text = "\n".join(lines).strip() + "\n"
    return _correct_hashtags_in_text(text, merged_copy)


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
        top_n = featured_fused_top_n()

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

            # 主池：綜合；無綜合時退回模型 → AI（與海報對齊）；一律只取頭 N
            primary, pool_source = _primary_picks_for_race(race)
            fused_rank_map: Dict[int, int] = {}
            for idx, p in enumerate(fused_picks):
                try:
                    fused_rank_map[int(p.get("horse_no"))] = idx + 1
                except Exception:
                    continue
            model_rank_map: Dict[int, int] = {}
            for idx, p in enumerate(model_picks):
                try:
                    model_rank_map[int(p.get("horse_no"))] = idx + 1
                except Exception:
                    continue
            ai_rank_map: Dict[int, int] = {}
            for idx, p in enumerate(ai_picks):
                try:
                    ai_rank_map[int(p.get("horse_no"))] = idx + 1
                except Exception:
                    continue

            candidates: List[Dict[str, Any]] = []
            seen: set[int] = set()
            for pool_rank, p in enumerate(primary[:top_n], start=1):
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
                if len(form_text) > FORM_TEXT_PAYLOAD_MAX:
                    form_text = form_text[:FORM_TEXT_PAYLOAD_MAX] + "…"
                candidates.append(
                    {
                        "pool": pool_source,
                        "sources": sources,
                        "dual_track": (
                            pool_source == "fused"
                            and horse_no in model_hnos
                            and horse_no in ai_hnos
                        ),
                        "fused_rank": fused_rank_map.get(horse_no),
                        "model_rank": model_rank_map.get(horse_no),
                        "ai_rank": ai_rank_map.get(horse_no),
                        "pool_rank": pool_rank,
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
                "featured_fused_top_n": top_n,
                "comment_source": "form_text_plus_analysis_meta",
                "comment_max_chars": COMMENT_MAX_CHARS,
                "must_be_factual": True,
                "prerace_copy": True,
                "public_voice": "senior_trainer",
                "form_comments_must_mark_past_runs": True,
                "forbid_benchang_for_tonight": True,
                "forbid_canned_saiqian_duizhao_endings": True,
                "forbid_public_jargon": [
                    "模型",
                    "AI",
                    "雙軌",
                    "綜合第",
                    "份額",
                    "勝率",
                ],
                "vary_featured_endings": True,
                "distinct_observation_angles": ["步速", "走位", "恢復", "路程"],
                "writing_locale": "hong_kong_trainer_social",
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
        """優先：綜合池 → 雙軌共識 → 有近績 → 份額。"""
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
        """當 LLM 失敗／不足 3 場時，用綜合推介（退回模型／AI）+ 近績自動補齊。"""
        top_n = featured_fused_top_n()
        race_rows: List[Dict[str, Any]] = []
        pick_index = _race_pick_index(copy_data)
        for race in list((copy_data or {}).get("races") or []):
            race_id = str(race.get("race_id") or "").strip()
            if not race_id:
                continue
            primary, pool_source = _primary_picks_for_race(race)
            model_hnos = {
                int(p.get("horse_no"))
                for p in list(race.get("model_picks") or [])
                if p.get("horse_no") is not None
            }
            ai_hnos = {
                int(p.get("horse_no"))
                for p in list(race.get("ai_picks") or [])
                if p.get("horse_no") is not None
            }

            by_horse: Dict[int, Dict[str, Any]] = {}
            sources_map: Dict[int, set[str]] = {}
            for p in primary[:top_n]:
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
            daypart = _meeting_daypart_from_copy(copy_data)
            dual = "model" in sources_map.get(int(best["horse_no"]), set()) and "ai" in sources_map.get(
                int(best["horse_no"]), set()
            )
            meta = (pick_index.get(race_id) or {}).get(int(best["horse_no"]))
            share = best.get("share_pct")
            dist = race.get("distance")
            snippet = _compress_form_snippet(form, max_chars=58)
            if snippet:
                model_bit = ""
                try:
                    share_f = float(share or 0)
                except Exception:
                    share_f = 0.0
                if dual:
                    angle_bit = "多方數據走勢一致，形勢值得跟"
                elif share_f >= 18:
                    angle_bit = "近績同走勢對照突出"
                elif dist:
                    angle_bit = f"{dist}米路程對照值得留意"
                else:
                    angle_bit = "近績走勢值得跟進"
                comment = _humanize_comment(
                    f"近績：{snippet}；{angle_bit}",
                    daypart=daypart,
                )
            else:
                tag = str(best.get("tag") or "推介").strip() or "推介"
                comment = f"{tag}走勢值得留意，有得傾"[:COMMENT_MAX_CHARS]

            basis = _analysis_basis_line(
                pool_source=pool_source,
                dual=dual,
                fused_rank=(meta or {}).get("fused_rank"),
                share_pct=share,
                distance=dist,
                tag=str(best.get("tag") or ""),
                form_hint=form,
                auto=True,
            )
            reason = _build_pick_reason(meta=meta, selected_by="fallback", angle="")
            race_rows.append(
                {
                    "race_no": race.get("race_no"),
                    "race_id": race_id,
                    "horse_no": best.get("horse_no"),
                    "horse_name": best.get("horse_name"),
                    "comment": comment,
                    "basis": basis,
                    "pick_reason": reason,
                    "_score": best_score,
                }
            )

        race_rows.sort(key=lambda x: x.get("_score") or (0, 0, 0, 0), reverse=True)
        out = []
        for row in race_rows[:limit]:
            row = dict(row)
            row.pop("_score", None)
            out.append(row)
        _assign_distinct_angles(out)
        for row in out:
            pr = dict(row.get("pick_reason") or {})
            pr["angle"] = row.get("angle") or pr.get("angle") or ""
            pr["label"] = _format_pick_reason_label(pr)
            row["pick_reason"] = pr
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
        clean_rows: List[Dict[str, Any]] = []
        seen_races: set[str] = set()
        pick_index = _race_pick_index(copy_data)
        form_maps: Dict[str, Dict[int, str]] = {}
        selected_by_default = (
            "fallback" if str(source or "").startswith("fallback") else "llm"
        )

        for item in featured:
            if not isinstance(item, dict):
                continue
            race_id = str(item.get("race_id") or "").strip()
            if not race_id or race_id in seen_races:
                continue
            daypart = _meeting_daypart_from_copy(copy_data)
            comment = _humanize_comment(str(item.get("comment") or "").strip(), daypart=daypart)
            try:
                horse_no = int(item.get("horse_no"))
            except Exception:
                horse_no = None
            horse_name = str(item.get("horse_name") or "").strip()
            allowed = pick_index.get(race_id) or {}
            selected_by = selected_by_default
            meta = allowed.get(horse_no) if horse_no is not None else None

            # P1-6：精選馬必須喺 fused top-N；否則校正去頭名並重寫近績 comment
            if allowed and (horse_no is None or horse_no not in allowed):
                # 優先揀 dual_track，否則 pool_rank 最小
                replacement = sorted(
                    allowed.values(),
                    key=lambda m: (
                        0 if m.get("dual_track") else 1,
                        int(m.get("pool_rank") or 99),
                    ),
                )[0]
                horse_no = int(replacement["horse_no"])
                horse_name = str(replacement.get("horse_name") or horse_name)
                meta = replacement
                selected_by = "remapped"
                if race_id not in form_maps:
                    form_maps[race_id] = self.load_formguide_map([race_id]).get(race_id, {})
                form = str(form_maps[race_id].get(horse_no) or "").strip()
                if form:
                    comment = _humanize_comment(form, daypart=daypart)
                else:
                    comment = _humanize_comment(
                        f"{replacement.get('tag') or '推介'}走勢值得留意",
                        daypart=daypart,
                    )

            if horse_no is None:
                continue
            seen_races.add(race_id)
            angle_hint = str(item.get("angle") or "").strip()
            basis = _strip_public_jargon(str(item.get("basis") or "").strip())
            # 空泛／黑箱 basis 改寫成練馬師可核對論點
            vague = (
                not basis
                or "綜合頭位" in basis
                or "雙軌" in basis
                or "份額" in basis
                or "模型" in basis
                or "AI" in basis.upper()
                or basis in {"模型與AI支持", "綜合推介", "雙邊支持"}
            )
            if vague and meta:
                dist = None
                for race in list((copy_data or {}).get("races") or []):
                    if str(race.get("race_id") or "") == race_id:
                        dist = race.get("distance")
                        break
                if race_id not in form_maps:
                    form_maps[race_id] = self.load_formguide_map([race_id]).get(race_id, {})
                basis = _analysis_basis_line(
                    pool_source=str(meta.get("pool") or "fused"),
                    dual=bool(meta.get("dual_track")),
                    fused_rank=meta.get("fused_rank"),
                    share_pct=meta.get("share_pct"),
                    distance=dist,
                    tag=str(meta.get("tag") or ""),
                    form_hint=str(form_maps[race_id].get(horse_no) or ""),
                )
            row = {
                "race_no": item.get("race_no"),
                "race_id": race_id,
                "horse_no": horse_no,
                "horse_name": horse_name,
                "comment": _truncate_comment(comment, limit=COMMENT_MAX_CHARS),
                "basis": basis,
                "angle": angle_hint if angle_hint in _ANGLE_BY_LABEL else "",
                "pick_reason": _build_pick_reason(
                    meta=meta, selected_by=selected_by, angle=angle_hint
                ),
            }
            clean_rows.append(row)

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

        _assign_distinct_angles(clean_rows[:3] if len(clean_rows) >= 3 else clean_rows)
        for row in clean_rows:
            pr = dict(row.get("pick_reason") or {})
            pr["angle"] = row.get("angle") or pr.get("angle") or ""
            pr["selected_by"] = pr.get("selected_by") or selected_by_default
            pr["label"] = _format_pick_reason_label(pr)
            row["pick_reason"] = pr

        tone_key = normalize_tone(tone)
        daypart = _meeting_daypart_from_copy(copy_data)
        title = _strip_public_jargon(str(raw.get("title") or "").strip())
        subtitle = _strip_public_jargon(str(raw.get("subtitle") or "").strip())
        if _is_system_subtitle(subtitle):
            subtitle = ""
        if daypart in {"今日", "聽日"}:
            title = title.replace("今晚", daypart).replace("今夜", daypart)
            subtitle = subtitle.replace("今晚", daypart).replace("今夜", daypart)
            if daypart == "聽日":
                title = title.replace("今日", "聽日")
                subtitle = subtitle.replace("今日", "聽日")
        featured_sorted = sort_featured_by_race_no(clean_rows[:3])
        if (
            not title
            or title.startswith("三場數據焦點")
            or title.startswith("三場焦點數據觀察")
            or "模型" in title
        ):
            title = default_focus_title(featured_sorted)
        if (
            not subtitle
            or subtitle.startswith("綜合模型")
            or "模型" in subtitle
            or "雙軌" in subtitle
        ):
            subtitle = DEFAULT_FOCUS_SUBTITLE

        footer = post_footer_text()
        result = {
            "title": title,
            "subtitle": subtitle,
            "featured": featured_sorted,
            "hashtags": _publish_hashtags_for_copy(copy_data, extra=None),
            "footer": footer,
            "footer_lines": list(POST_FOOTER_LINES),
            "post_text": "",
            "tone": tone_key,
            "tone_label": tone_label(tone_key),
            "custom_prompt": str(custom_prompt or "").strip(),
            "source": source,
            "featured_fused_top_n": featured_fused_top_n(),
            "raw": raw,
            "meeting": _meeting_blob(copy_data, None),
        }
        result["post_text"] = format_social_post_text(result, copy_data=copy_data)
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
                        "注意：文末固定合規聲明由系統附加；請保持研究向用詞，禁止心水／貼士／投注誘導；唔好在 title／comment 重複寫免責全文。\n"
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
                "subtitle": "",  # 唔寫入對外文案；UI 用 source=fallback:* 顯示提示
                "featured": fb,
                "hashtags": _publish_hashtags_for_copy(copy_data),
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
