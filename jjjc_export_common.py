"""
api_jjjc export 共用工具（speedguide／formguide／text-reports／racecard／results）。

契約語意（api_jjjc → J18 正式回覆）：
  - waiting：HTTP 200 且空列表／空字／placeholder／status∈unpublished|suspicious|date_mismatch|partial|empty
  - failed：5xx、連線失敗、status=unavailable
  - 內容更新：看 content_updated_at（勿用 generated_at）
  - Join：race_id（YYYYMMDD+ST|HV+兩位場次）+ horse_no
"""
from __future__ import annotations

import json
import os
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


def api_base(explicit: Optional[str] = None) -> str:
    return (
        explicit
        or os.getenv("JJJC_API_BASE")
        or os.getenv("JJJC_RESULTS_API_BASE")
        or ""
    ).strip().rstrip("/")


def normalize_date(d: str) -> str:
    s = str(d or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


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
        # partial／empty 等：若已有列仍可 upsert，但標 waiting 讓 tick 再探
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
    404／5xx／連線錯誤 → 拋 httpx.HTTPStatusError 或 httpx.RequestError（呼叫端視為 failed→備援）。
    """
    base = api_base(base_url)
    if not base:
        raise ValueError(
            "未設定 JJJC_API_BASE（或 JJJC_RESULTS_API_BASE）。"
            "或改用 --from-file 讀取本機 export JSON。"
        )
    params: Dict[str, Any] = {
        "date": normalize_date(race_date),
        "venue": str(venue).upper(),
    }
    if race_no is not None:
        params["raceNo"] = int(race_no)
    if extra_params:
        params.update(extra_params)
    url = f"{base}{path}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        payload = r.json()
    if not isinstance(payload, dict):
        raise ValueError("export 回應非 JSON object")
    return payload


def text_nonempty(v: Any) -> bool:
    return bool(str(v or "").strip())


def is_placeholder(runner: Dict[str, Any]) -> bool:
    flag = runner.get("is_placeholder")
    if flag in (True, 1, "1", "true", "True", "yes", "YES"):
        return True
    return False


def effective_text(runner: Dict[str, Any], *keys: str) -> Optional[str]:
    """取第一個非空文字；placeholder 視為無內容。"""
    if is_placeholder(runner):
        return None
    for k in keys:
        t = runner.get(k)
        if text_nonempty(t):
            return str(t).strip()
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
