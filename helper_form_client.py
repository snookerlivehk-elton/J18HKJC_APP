"""
J18 Helper 戰績表 API 客戶端。

來源：GET {J18_API_BASE}/calculate/v1/tool/helper?all=1
注意：URL 本身無日期參數，必須以 title 解析日期後，對照系統最新賽馬日。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

_DEFAULT_J18_ORIGIN = "https://api.j18.hk"
_HELPER_PATH = "/calculate/v1/tool/helper"

# 例：2026年10月1日 13:00 沙田 草地 第一場 1200米
# 亦容忍：跑馬地草地（場地與表面黏在一起）
_TITLE_RE = re.compile(
    r"(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日"
    r"(?:\s+(?P<time>\d{1,2}:\d{2}))?"
    r"(?:\s+(?P<venue>沙田|跑馬地))?"
    r"(?:\s*(?P<surface>草地|泥地|全天候|膠地))?"
    r"(?:\s+第(?P<race_zh>[一二三四五六七八九十百零〇两兩\d]+)場)?"
    r"(?:\s+(?P<dist>\d+)\s*米)?"
)

_VENUE_TO_COURSE = {"沙田": "ST", "跑馬地": "HV"}
_COURSE_TO_VENUE = {"ST": "沙田", "HV": "跑馬地"}

# header key → horse 欄位（API header 名與 horse 實際欄位不完全一致）
_HORSE_FIELD_ALIASES = {
    "match_work": "jockeyToWork",
    "match_discount": "discount",
    "match_gear": "changeGear",
}

# 顯示用修正（API 偶有錯字）
_HEADER_DISPLAY_FIX = {
    "負榜": "負磅",
    "马龄/性别": "馬齡/性別",
    "馬齡/性别": "馬齡/性別",
    "更变装备": "更變裝備",
}

_COLUMN_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "馬匹資料",
        ("name", "sexorage", "handicapWeight", "runnerRating"),
    ),
    (
        "馬匹統計數字",
        (
            "match_all",
            "match_current",
            "match_shift",
            "match_place",
            "match_mud",
            "match_road",
            "match_placeRoad",
            "match_distanceRange",
            "match_jockey",
            "match_work",
            "match_well",
            "match_sticky",
            "match_mushy",
        ),
    ),
    (
        "備註",
        ("match_discount", "match_odds", "match_gear"),
    ),
)


@dataclass
class ParsedTitle:
    racing_date: str  # YYYY-MM-DD
    post_time: str = ""
    venue_label: str = ""
    course: str = ""
    surface: str = ""
    race_num: Optional[int] = None
    distance_m: Optional[int] = None
    raw: str = ""


@dataclass
class HelperFormGuardResult:
    ok: bool
    status: str  # ok | stale | inconsistent | parse_error | empty | no_expected
    message: str
    api_dates: List[str] = field(default_factory=list)
    expected_date: Optional[str] = None
    api_courses: List[str] = field(default_factory=list)
    expected_course: Optional[str] = None


def get_helper_form_url() -> str:
    raw = (os.getenv("J18_API_BASE_URL") or _DEFAULT_J18_ORIGIN).strip().rstrip("/")
    if raw.lower().endswith("helper"):
        return raw
    if "historyresult" in raw.lower():
        # 若環境變數指到 historyResult，退回同源 origin
        origin = raw.split("/calculate/")[0].rstrip("/")
        return f"{origin}{_HELPER_PATH}"
    return f"{raw}{_HELPER_PATH}"


def fetch_helper_form(
    *,
    all_races: bool = True,
    timeout: float = 30.0,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """抓取 helper API 原始 JSON。"""
    url = get_helper_form_url()
    params = {"all": "1"} if all_races else None
    owns = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns:
            http.close()
    if not isinstance(data, dict):
        raise ValueError("helper API 回傳非物件")
    return data


def parse_race_title(title: str) -> Optional[ParsedTitle]:
    text = str(title or "").strip()
    if not text:
        return None
    m = _TITLE_RE.search(text)
    if not m:
        return None
    y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
    try:
        racing_date = date(y, mo, d).isoformat()
    except ValueError:
        return None
    venue = m.group("venue") or ""
    course = _VENUE_TO_COURSE.get(venue, "")
    race_num = _zh_or_digit_to_int(m.group("race_zh") or "")
    dist_raw = m.group("dist")
    return ParsedTitle(
        racing_date=racing_date,
        post_time=m.group("time") or "",
        venue_label=venue,
        course=course,
        surface=m.group("surface") or "",
        race_num=race_num,
        distance_m=int(dist_raw) if dist_raw else None,
        raw=text,
    )


def _zh_or_digit_to_int(s: str) -> Optional[int]:
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    table = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "十一": 11,
        "十二": 12,
        "十三": 13,
        "十四": 14,
    }
    if s in table:
        return table[s]
    if s.startswith("十") and len(s) == 2:
        ones = table.get(s[1])
        return 10 + ones if ones else None
    return None


def resolve_latest_meeting(
    racing_date: Optional[str] = None,
    course: Optional[str] = None,
) -> Dict[str, Any]:
    """
    從系統 upcoming_races 取最新賽馬日（可選指定日期／場地）。
    回傳 {ok, racing_date, course, n_races, error?}
    """
    try:
        from prediction_export import list_upcoming_meeting
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"無法載入 upcoming：{exc}"}

    listed = list_upcoming_meeting(racing_date, course)
    meetings = list(listed.get("meetings") or [])
    if not meetings:
        return {"ok": False, "error": "系統尚無 upcoming 賽馬日", "meetings": []}
    meetings_sorted = sorted(
        meetings,
        key=lambda m: (str(m.get("racing_date") or ""), str(m.get("course") or "")),
    )
    # 「最新」：日期最大；同日多場地則取第一個（可由呼叫端再傳 course）
    latest_date = max(str(m.get("racing_date") or "")[:10] for m in meetings_sorted)
    same_day = [m for m in meetings_sorted if str(m.get("racing_date") or "")[:10] == latest_date]
    chosen = same_day[0]
    if course:
        for m in same_day:
            if str(m.get("course") or "").upper() == course.upper():
                chosen = m
                break
    return {
        "ok": True,
        "racing_date": str(chosen.get("racing_date") or "")[:10],
        "course": str(chosen.get("course") or "").upper(),
        "n_races": int(chosen.get("n_races") or 0),
        "meetings": meetings_sorted,
    }


def guard_helper_against_latest(
    raw: Dict[str, Any],
    *,
    expected_date: Optional[str] = None,
    expected_course: Optional[str] = None,
    require_course: bool = False,
) -> HelperFormGuardResult:
    """核對 helper 各場 title 日期是否匹配最新／指定賽馬日。"""
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict) or not data:
        return HelperFormGuardResult(
            ok=False,
            status="empty",
            message="helper API 無場次資料",
        )

    parsed_dates: List[str] = []
    parsed_courses: List[str] = []
    parse_failures = 0
    for key in sorted(data.keys(), key=lambda x: int(x) if str(x).isdigit() else 999):
        race = data[key]
        if not isinstance(race, dict):
            parse_failures += 1
            continue
        pt = parse_race_title(str(race.get("title") or ""))
        if not pt:
            parse_failures += 1
            continue
        parsed_dates.append(pt.racing_date)
        if pt.course:
            parsed_courses.append(pt.course)

    if not parsed_dates:
        return HelperFormGuardResult(
            ok=False,
            status="parse_error",
            message="無法從 helper title 解析任何賽日",
            api_dates=[],
        )

    unique_dates = sorted(set(parsed_dates))
    unique_courses = sorted(set(parsed_courses))
    if len(unique_dates) > 1:
        return HelperFormGuardResult(
            ok=False,
            status="inconsistent",
            message=f"helper 各場日期不一致：{', '.join(unique_dates)}",
            api_dates=unique_dates,
            api_courses=unique_courses,
            expected_date=expected_date,
            expected_course=expected_course,
        )

    api_date = unique_dates[0]
    exp = (expected_date or "").strip()[:10] or None
    if not exp:
        latest = resolve_latest_meeting(course=expected_course)
        if not latest.get("ok"):
            return HelperFormGuardResult(
                ok=False,
                status="no_expected",
                message=str(latest.get("error") or "無法取得系統最新賽馬日"),
                api_dates=unique_dates,
                api_courses=unique_courses,
            )
        exp = str(latest["racing_date"])[:10]
        if not expected_course and latest.get("course"):
            expected_course = str(latest["course"]).upper()

    if api_date != exp:
        return HelperFormGuardResult(
            ok=False,
            status="stale",
            message=f"helper 賽日 {api_date} 與最新賽馬日 {exp} 不符",
            api_dates=unique_dates,
            expected_date=exp,
            api_courses=unique_courses,
            expected_course=expected_course,
        )

    if require_course and expected_course:
        exp_c = expected_course.upper()
        if unique_courses and exp_c not in unique_courses:
            return HelperFormGuardResult(
                ok=False,
                status="stale",
                message=(
                    f"helper 場地 {','.join(unique_courses)} "
                    f"與最新賽馬日場地 {exp_c} 不符"
                ),
                api_dates=unique_dates,
                expected_date=exp,
                api_courses=unique_courses,
                expected_course=exp_c,
            )

    return HelperFormGuardResult(
        ok=True,
        status="ok",
        message=f"已核對賽日 {api_date}",
        api_dates=unique_dates,
        expected_date=exp,
        api_courses=unique_courses,
        expected_course=expected_course,
    )


def _fix_header_label(raw: str) -> str:
    s = str(raw or "").strip()
    return _HEADER_DISPLAY_FIX.get(s, s)


def _cell_display(key: str, horse: Dict[str, Any], header: Dict[str, Any]) -> str:
    """將 horse 欄位轉成表格顯示字串。"""
    alias = _HORSE_FIELD_ALIASES.get(key, key)
    if key == "match_work":
        raw = horse.get("jockeyToWork", horse.get("match_work"))
        if raw in (1, "1", True, "是", "Y", "y"):
            return "是"
        if raw in (0, "0", False, "否", "N", "n", None, ""):
            return "否"
        return str(raw)
    if key == "match_gear":
        raw = horse.get("changeGear", horse.get("match_gear", ""))
        return str(raw if raw not in (None, "") else "否")
    if key == "match_discount":
        raw = horse.get("discount", horse.get("match_discount", ""))
        return "" if raw in (None, "") else str(raw)
    val = horse.get(alias, horse.get(key, ""))
    if val is None:
        return ""
    return str(val)


def normalize_helper_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    正規化 helper 回傳為渲染友好結構（全中文欄名）。
    """
    data = raw.get("data") if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        data = {}

    races: List[Dict[str, Any]] = []
    for key in sorted(data.keys(), key=lambda x: int(x) if str(x).isdigit() else 999):
        race = data[key]
        if not isinstance(race, dict):
            continue
        title = str(race.get("title") or "")
        parsed = parse_race_title(title)
        header_raw = race.get("header") if isinstance(race.get("header"), dict) else {}
        horses_in = race.get("horse") if isinstance(race.get("horse"), list) else []

        # 欄位順序：固定分組；缺的 key 略過
        columns: List[Dict[str, str]] = []
        groups_out: List[Dict[str, Any]] = []
        for group_name, keys in _COLUMN_GROUPS:
            group_cols = []
            for k in keys:
                if k not in header_raw and k not in (
                    "name",
                    "sexorage",
                    "handicapWeight",
                    "runnerRating",
                    "match_odds",
                ):
                    # 仍保留已知結構欄，即使 header 缺 key
                    pass
                label = _fix_header_label(str(header_raw.get(k) or _fallback_label(k)))
                col = {"key": k, "label": label}
                columns.append(col)
                group_cols.append(col)
            groups_out.append({"name": group_name, "columns": group_cols})

        rows = []
        for h in horses_in:
            if not isinstance(h, dict):
                continue
            cells = {c["key"]: _cell_display(c["key"], h, header_raw) for c in columns}
            rows.append(
                {
                    "num": str(h.get("num") or ""),
                    "horse_code": str(h.get("no") or ""),
                    "name": str(h.get("name") or ""),
                    "jockey": str(h.get("jockey") or ""),
                    "trainer": str(h.get("trainer") or ""),
                    "cells": cells,
                }
            )

        races.append(
            {
                "race_key": str(key),
                "race_num": (parsed.race_num if parsed else None) or (
                    int(key) if str(key).isdigit() else None
                ),
                "title": title,
                "parsed": {
                    "racing_date": parsed.racing_date if parsed else None,
                    "post_time": parsed.post_time if parsed else "",
                    "venue_label": parsed.venue_label if parsed else "",
                    "course": parsed.course if parsed else "",
                    "surface": parsed.surface if parsed else "",
                    "distance_m": parsed.distance_m if parsed else None,
                },
                "distance_range_label": str(race.get("test") or ""),
                "groups": groups_out,
                "columns": columns,
                "rows": rows,
            }
        )

    return {
        "ok": True,
        "code": raw.get("code"),
        "message": raw.get("message"),
        "races": races,
        "n_races": len(races),
    }


def _fallback_label(key: str) -> str:
    return {
        "name": "馬名",
        "sexorage": "馬齡/性別",
        "handicapWeight": "負磅",
        "runnerRating": "評分",
        "match_all": "出道至今",
        "match_current": "今季",
        "match_shift": "班次",
        "match_place": "場地",
        "match_mud": "泥/膠地",
        "match_road": "同程",
        "match_placeRoad": "同場同程",
        "match_distanceRange": "距離帶",
        "match_jockey": "騎師",
        "match_work": "參與操練",
        "match_well": "好地",
        "match_sticky": "黏地",
        "match_mushy": "軟/爛地",
        "match_discount": "上仗水位",
        "match_odds": "贏馬賠率",
        "match_gear": "更變裝備",
    }.get(key, key)


def load_helper_form_for_display(
    *,
    expected_date: Optional[str] = None,
    expected_course: Optional[str] = None,
    require_course: bool = False,
    raw: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    抓取（或使用传入 raw）→ 日期核對 → 正規化。
    核對失敗時仍回傳 normalize 結果供除錯，但 ok=False。
    """
    payload = raw if raw is not None else fetch_helper_form(timeout=timeout)
    guard = guard_helper_against_latest(
        payload,
        expected_date=expected_date,
        expected_course=expected_course,
        require_course=require_course,
    )
    normalized = normalize_helper_payload(payload)
    return {
        "ok": bool(guard.ok),
        "guard": {
            "ok": guard.ok,
            "status": guard.status,
            "message": guard.message,
            "api_dates": guard.api_dates,
            "expected_date": guard.expected_date,
            "api_courses": guard.api_courses,
            "expected_course": guard.expected_course,
        },
        "races": normalized.get("races") or [],
        "n_races": normalized.get("n_races") or 0,
        "raw_code": payload.get("code") if isinstance(payload, dict) else None,
    }


def course_label(course: str) -> str:
    return _COURSE_TO_VENUE.get(str(course or "").upper(), str(course or ""))
