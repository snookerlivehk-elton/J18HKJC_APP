"""
api_jjjc export 共用工具（speedguide／formguide／text-reports／racecard／results／sectionals／catalog）。

契約語意（api_jjjc → J18 正式回覆）：
  - waiting：HTTP 200 且空列表／空字／placeholder／status∈unpublished|suspicious|date_mismatch|partial|empty
  - failed：5xx、連線失敗、status=unavailable
  - 內容更新：看 content_updated_at（勿用 generated_at）
  - Join：race_id（YYYYMMDD+ST|HV+兩位場次）+ horse_no
  - meeting_id：YYYY-MM-DD_ST|HV（例 2026-09-16_HV）
  - venue_code：只得大階 ST|HV
  - 禁止用 horse_name 做主鍵；排位 DB 可能叫 runner_no＝horse_no
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Set

import httpx

WAITING_STATUSES: Set[str] = {
    "unpublished",
    "suspicious",
    "date_mismatch",
    "partial",
    "empty",
    "waiting",
    "obtained",  # obtained 但 races=[] 仍可能是空殼；由呼叫端再判空
}
FAILED_STATUSES: Set[str] = {"unavailable"}

VENUE_ALIASES = {
    "ST": "ST",
    "HV": "HV",
    "SHA TIN": "ST",
    "SHATIN": "ST",
    "沙田": "ST",
    "HAPPY VALLEY": "HV",
    "HAPPYVALLEY": "HV",
    "跑馬地": "HV",
}

# 香港馬場法定／慣例最大出馬數（馬號上限＝場額）
# HV 跑馬地 ≤12；ST 沙田 ≤14。超過即屬幽靈污染（例如 ST 賽果誤寫入 HV race_id）。
VENUE_MAX_HORSE_NO = {"ST": 14, "HV": 12}


def api_base(explicit: Optional[str] = None) -> str:
    return (
        explicit
        or os.getenv("JJJC_API_BASE")
        or os.getenv("JJJC_RESULTS_API_BASE")
        # 與 ad_push_prod／手冊預設一致；未設 env 時仍可拉 R2 分段
        or "https://apicc.up.railway.app"
    ).strip().rstrip("/")


def normalize_date(d: str) -> str:
    s = str(d or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def normalize_venue(v: Any) -> Optional[str]:
    """只回 ST|HV；禁止用 Sha Tin／沙田／st。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    key = s.upper().replace("_", " ")
    if key in ("ST", "HV"):
        return key
    mapped = VENUE_ALIASES.get(key) or VENUE_ALIASES.get(s)
    if mapped:
        return mapped
    m = re.search(r"(ST|HV)", key)
    return m.group(1) if m else None


def meeting_id(race_date: str, venue: str) -> str:
    """穩定會議鍵：YYYY-MM-DD_ST|HV。"""
    d = normalize_date(race_date)
    v = normalize_venue(venue) or str(venue or "").strip().upper()
    return f"{d}_{v}"


def make_race_id(race_date: str, venue: str, race_no: int) -> str:
    d = normalize_date(race_date).replace("-", "")[:8]
    v = normalize_venue(venue) or "ST"
    return f"{d}{v}{int(race_no):02d}"


def venue_from_race_id(race_id: Any) -> Optional[str]:
    """從 race_id（YYYYMMDDST|HV##）抽出場地。"""
    s = str(race_id or "").strip().upper()
    if len(s) < 10:
        return None
    return normalize_venue(s[8:10])


def max_horse_no_for_venue(venue: Any) -> Optional[int]:
    """場地最大馬號；未知場地回 None。"""
    v = normalize_venue(venue)
    if not v:
        return None
    return VENUE_MAX_HORSE_NO.get(v)


def horse_no_allowed_for_venue(horse_no: Any, venue: Any) -> bool:
    """馬號是否符合場地上限（HV≤12、ST≤14）。"""
    hn = safe_int(horse_no)
    if hn is None or hn < 1:
        return False
    cap = max_horse_no_for_venue(venue)
    if cap is None:
        return True
    return hn <= cap


def field_size_issues(
    venue: Any,
    horse_nos: Any,
    *,
    race_id: Any = None,
) -> List[str]:
    """
    回傳場額異常說明（空＝OK）。
    用於 sync 拒寫／ops 警告：場地馬數／馬號超過上限。
    """
    v = normalize_venue(venue) or venue_from_race_id(race_id)
    cap = max_horse_no_for_venue(v)
    if cap is None:
        return []
    nos: List[int] = []
    for x in horse_nos or []:
        n = safe_int(x)
        if n is not None:
            nos.append(n)
    if not nos:
        return []
    issues: List[str] = []
    over = sorted({n for n in nos if n > cap})
    if over:
        issues.append(
            f"{v} 場額上限 {cap}，出現非法馬號 {over}（疑 ST 賽果誤寫入 HV race_id）"
            if v == "HV"
            else f"{v} 場額上限 {cap}，出現非法馬號 {over}"
        )
    if len(nos) > cap:
        issues.append(f"{v} 本場 {len(nos)} 匹超過場額上限 {cap}")
    return issues


def safe_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    s = str(v).replace(",", "").strip()
    if s.startswith("+"):
        s = s[1:]
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def horse_no_of(row: Dict[str, Any]) -> Optional[int]:
    """
    Join 用檔號：export 叫 horse_no；排位 DB 可能叫 runner_no。
    禁止用 horse_name。
    """
    for k in ("horse_no", "runner_no", "horseNo", "runnerNo", "no"):
        n = safe_int(row.get(k))
        if n is not None:
            return n
    return None


def looks_latin_name(s: Any) -> bool:
    """純英文／拉丁顯示名（官方 results 常見）；有中日韓字則否。"""
    t = str(s or "").strip()
    if not t:
        return False
    if re.search(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", t):
        return False
    return bool(re.search(r"[A-Za-z]", t))


def prefer_zh_text(*candidates: Any, fallback: Any = None) -> Optional[str]:
    """
    顯示名優先中文：先搵有中日韓字嘅候選，再非空，再 fallback。
    用於 horse／jockey／trainer（results 常係英文；racecard／sectionals 有中文）。
    """
    nonempty: List[str] = []
    for c in candidates:
        if c is None:
            continue
        t = str(c).strip()
        if not t or t.lower() in ("none", "null", "-"):
            continue
        nonempty.append(t)
        if not looks_latin_name(t):
            return t
    if nonempty:
        # 全係拉丁：仍回第一個非空（總好過空）
        return nonempty[0]
    if fallback is None:
        return None
    fb = str(fallback).strip()
    return fb or None


def display_horse_name(row: Dict[str, Any], *extra: Any) -> Optional[str]:
    return prefer_zh_text(
        row.get("horse_name_ch"),
        row.get("horse_name"),
        row.get("horseNameCh"),
        row.get("horse_name_en"),
        *extra,
    )


def display_jockey_name(row: Dict[str, Any], *extra: Any) -> Optional[str]:
    return prefer_zh_text(
        row.get("jockey_name_ch"),
        row.get("jockey_name"),
        row.get("jockeyNameCh"),
        row.get("jockey_name_en"),
        *extra,
    )


def display_trainer_name(row: Dict[str, Any], *extra: Any) -> Optional[str]:
    return prefer_zh_text(
        row.get("trainer_name_ch"),
        row.get("trainer_name"),
        row.get("trainerNameCh"),
        row.get("trainer_name_en"),
        *extra,
    )


def merge_prefer_zh(new: Any, existing: Any) -> Optional[str]:
    """UPDATE 時：新值係英文、庫內已係中文 → 保留中文。"""
    return prefer_zh_text(new, existing)


_REAL_HORSE_CODE_RE = re.compile(r"^[A-Z]\d{3,}$")
_SYNTHETIC_BRAND_RE = re.compile(r"^H\d{2}$")  # results 無 code 時 H01–H14


def is_real_horse_code(code: Any) -> bool:
    """
    真馬碼（如 J446／H349／K037）；排除 results 無 code 時合成嘅 H{horse_no:02d}。
    """
    s = str(code or "").strip().upper()
    if not s or s in ("NONE", "NAN", "NULL", "-"):
        return False
    if _SYNTHETIC_BRAND_RE.match(s):
        return False
    return bool(_REAL_HORSE_CODE_RE.match(s))


def horse_identity_key(
    brand_num: Any = None,
    horse_name: Any = None,
    *,
    horse_code: Any = None,
    horse_id: Any = None,
) -> str:
    """
    統計／因子用穩定馬身份：真馬碼 > 非 UNK horse_id > 正規化馬名。
    禁止用馬名做主鍵嘅情境請優先呢個 key（避免中英拆散近績）。
    """
    for c in (brand_num, horse_code):
        if is_real_horse_code(c):
            return str(c).strip().upper()
    hid = str(horse_id or "").strip()
    if hid and not hid.startswith("UNK_") and "_" in hid:
        # HK_2026_J446 → J446
        tail = hid.rsplit("_", 1)[-1].upper()
        if is_real_horse_code(tail):
            return tail
    from bucket_utils import normalize_person_name

    name = normalize_person_name(horse_name)
    return name or ""


def canonical_horse_label(horse_key: str, *names: Any) -> str:
    """顯示用：有中文名 →「將義」；否則馬碼／英文名。"""
    zh = prefer_zh_text(*names)
    key = str(horse_key or "").strip()
    if zh and not looks_latin_name(zh):
        return zh
    if zh:
        return zh
    return key


def load_payload_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("file payload 非 JSON object")
    return payload


def classify_payload_status(payload: Dict[str, Any], *, empty: bool) -> str:
    """回傳 waiting | failed | ready（有內容可 upsert）。"""
    st = str(payload.get("status") or "").strip().lower()
    if st in FAILED_STATUSES:
        return "failed"
    if empty:
        return "waiting"
    if st in WAITING_STATUSES - {"obtained"}:
        if st in ("empty", "unpublished"):
            return "waiting"
    return "ready"


def fetch_export_get(
    path: str,
    *,
    race_date: str,
    venue: str,
    race_no: Optional[int] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    base_url: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """
    GET {base}{path}?date=&venue=[&raceNo=…]
    404／5xx／連線錯誤 → 拋 httpx.HTTPStatusError 或 httpx.RequestError。
    """
    base = api_base(base_url)
    if not base:
        raise ValueError(
            "未設定 JJJC_API_BASE（或 JJJC_RESULTS_API_BASE）。"
            "或改用 --from-file 讀取本機 export JSON。"
        )
    v = normalize_venue(venue)
    if not v:
        raise ValueError(f"venue 必須係 ST|HV，收到：{venue!r}")
    params: Dict[str, Any] = {
        "date": normalize_date(race_date),
        "venue": v,
    }
    if race_no is not None:
        params["raceNo"] = int(race_no)
    if extra_params:
        params.update(extra_params)
    url = f"{base}{path}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, params=params)
        if r.status_code >= 400:
            detail = (r.text or "")[:300]
            raise httpx.HTTPStatusError(
                f"HTTP {r.status_code} for {url}: {detail}",
                request=r.request,
                response=r,
            )
        payload = r.json()
    if not isinstance(payload, dict):
        raise ValueError("export 回應非 JSON object")
    return payload


def fetch_catalog(
    base_url: Optional[str] = None, timeout: float = 30.0
) -> Dict[str, Any]:
    """GET /api/export/catalog → jjjc.downstream_catalog.v1"""
    base = api_base(base_url)
    if not base:
        raise ValueError("未設定 JJJC_API_BASE")
    url = f"{base}/api/export/catalog"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        payload = r.json()
    if not isinstance(payload, dict):
        raise ValueError("catalog 回應非 JSON object")
    return payload


def text_nonempty(v: Any) -> bool:
    return bool(str(v or "").strip())


def is_placeholder(runner: Dict[str, Any]) -> bool:
    flag = runner.get("is_placeholder")
    if flag in (True, 1, "1", "true", "True", "yes", "YES"):
        return True
    return False


def energy_is_placeholder(row: Dict[str, Any]) -> bool:
    flag = row.get("energy_is_placeholder")
    return flag in (True, 1, "1", "true", "True", "yes", "YES")


def effective_text(runner: Dict[str, Any], *keys: str) -> Optional[str]:
    """取第一個非空文字；placeholder 視為無內容；解碼常見 HTML 實體。"""
    import html

    if is_placeholder(runner):
        return None
    for k in keys:
        t = runner.get(k)
        if text_nonempty(t):
            return html.unescape(str(t)).strip()
    return None


def database_url_sync(use_sqlite: bool, sqlite_path: str) -> str:
    if use_sqlite:
        return f"sqlite:///{sqlite_path}"
    url = os.getenv("DATABASE_URL") or os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def content_meta(payload: Dict[str, Any], row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """寫入 raw_json 的內容指紋欄（content_updated_at 優先）。"""
    row = row or {}
    return {
        "content_updated_at": row.get("content_updated_at")
        or payload.get("content_updated_at"),
        "fetched_at": row.get("fetched_at") or payload.get("fetched_at"),
        "generated_at": payload.get("generated_at"),
        "status": payload.get("status"),
        "schema": payload.get("schema"),
        "source": "jjjc_export",
    }
