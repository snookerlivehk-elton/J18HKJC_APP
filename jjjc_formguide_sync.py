"""
從 api_jjjc `GET /api/export/formguide` 同步賽事指引短評 → upcoming_formguide。

schema：jjjc.formguide.v1
映射：form_text（可選 form_text_en 進 raw_json）

CLI：
  python jjjc_formguide_sync.py --date 2026-09-09 --course HV
  python jjjc_formguide_sync.py --from-file fixtures/jjjc_formguide_HV_20260909_R1.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import create_engine, text

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE, resolve_database_url
from jjjc_export_common import (
    api_base,
    classify_payload_status,
    content_meta,
    effective_text,
    fetch_export_get,
    load_payload_file,
    normalize_date,
    safe_int,
    text_nonempty,
)

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

DATABASE_URL_SYNC = resolve_database_url()

SCHEMA_NAME = "jjjc.formguide.v1"
EXPORT_PATH = "/api/export/formguide"


def fetch_export(
    race_date: str,
    venue: str,
    race_no: Optional[int] = None,
    base_url: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    return fetch_export_get(
        EXPORT_PATH,
        race_date=race_date,
        venue=venue,
        race_no=race_no,
        base_url=base_url,
        timeout=timeout,
    )


def _formguide_fetch_timeout() -> float:
    try:
        return float(os.getenv("JJJC_FORMGUIDE_FETCH_TIMEOUT", "120") or 120)
    except (TypeError, ValueError):
        return 120.0


def _form_text_coverage(payload: Dict[str, Any]) -> tuple[int, int]:
    with_t = 0
    total = 0
    for race in payload.get("races") or []:
        for ru in race.get("runners") or []:
            total += 1
            if text_nonempty(effective_text(ru, "form_text")):
                with_t += 1
    return with_t, total


def export_needs_formguide_refresh(payload: Dict[str, Any]) -> bool:
    races = list(payload.get("races") or [])
    if not races:
        return True
    st = str(payload.get("status") or "").strip().lower()
    if st in {"partial", "empty", "suspicious", "unpublished", "waiting", "date_mismatch"}:
        return True
    with_t, total = _form_text_coverage(payload)
    if total <= 0:
        return True
    return (with_t / float(total)) < 0.80


def trigger_formguide_fetch(
    race_date: str,
    venue: str,
    *,
    base_url: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """上游主動抓賽績指引：POST {base}/api/formguide/fetch?date=&venue=."""
    base = api_base(base_url)
    if not base:
        return {"ok": False, "error": "未設定 JJJC_API_BASE"}
    v = str(venue or "").strip().upper()
    if v not in {"ST", "HV"}:
        return {"ok": False, "error": f"venue 必須係 ST|HV，收到：{venue!r}"}
    params = {"date": normalize_date(race_date), "venue": v}
    url = f"{base}/api/formguide/fetch"
    to = float(timeout if timeout is not None else _formguide_fetch_timeout())
    try:
        with httpx.Client(timeout=to, follow_redirects=True) as client:
            r = client.post(url, params=params)
        try:
            parsed = r.json()
            body = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            body = {"raw_text": (r.text or "")[:300]}
        if r.status_code >= 400:
            return {
                "ok": False,
                "status_code": r.status_code,
                "error": f"HTTP {r.status_code}",
                "url": url,
                "response": body,
            }
        return {
            "ok": bool(body.get("ok", True)),
            "status_code": r.status_code,
            "url": url,
            "race_date": body.get("race_date") or params["date"],
            "venue_code": body.get("venue_code") or v,
            "race_count": safe_int(body.get("race_count")),
            "runner_count": safe_int(body.get("runner_count")),
            "status": body.get("status"),
            "response": body,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "url": url}


def _ensure_table() -> None:
    if USE_SQLITE:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS upcoming_formguide (
                    runner_id TEXT PRIMARY KEY,
                    race_id TEXT,
                    horse_no INTEGER,
                    form_text TEXT,
                    raw_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()
        return

    engine = create_engine(DATABASE_URL_SYNC)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS upcoming_formguide (
                        runner_id VARCHAR(50) PRIMARY KEY,
                        race_id VARCHAR(50),
                        horse_no INT,
                        form_text TEXT,
                        raw_json JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
            )
    finally:
        engine.dispose()


def upsert_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    schema = payload.get("schema")
    if schema and schema != SCHEMA_NAME:
        raise ValueError(f"不支援的 schema：{schema}")

    races: List[Dict[str, Any]] = list(payload.get("races") or [])
    empty = not races
    phase = classify_payload_status(payload, empty=empty)
    if empty:
        return {
            "ok": True,
            "waiting": True,
            "phase": phase,
            "race_count": 0,
            "runner_upserted": 0,
            "detail": "export races=[]（waiting）",
            "content_updated_at": payload.get("content_updated_at"),
            "status": payload.get("status"),
        }
    if phase == "failed":
        return {
            "ok": False,
            "waiting": False,
            "phase": "failed",
            "error": f"status={payload.get('status')}",
        }

    _ensure_table()
    engine = create_engine(DATABASE_URL_SYNC)
    runner_n = 0
    with_text = 0
    race_ids: List[str] = []

    try:
        with engine.begin() as conn:
            for race in races:
                race_id = str(race.get("race_id") or "").strip()
                if not race_id:
                    continue
                race_ids.append(race_id)
                for ru in race.get("runners") or []:
                    horse_no = safe_int(ru.get("horse_no"))
                    if horse_no is None:
                        continue
                    form_text = effective_text(ru, "form_text")
                    form_en = effective_text(ru, "form_text_en")
                    # 空字／placeholder → 仍 upsert NULL，讓覆蓋檢查視為未齊（waiting）
                    if text_nonempty(form_text):
                        with_text += 1

                    runner_id = f"{race_id}_{horse_no}"
                    meta = content_meta(payload, race if isinstance(race, dict) else None)
                    raw_obj = {
                        **meta,
                        "horse_name": ru.get("horse_name"),
                        "form_text": form_text,
                        "form_text_en": form_en,
                        "runner": ru,
                    }
                    raw_s = json.dumps(raw_obj, ensure_ascii=False)
                    params = {
                        "runner_id": runner_id,
                        "race_id": race_id,
                        "horse_no": horse_no,
                        "form_text": form_text,
                        "raw_json": raw_s,
                    }
                    if USE_SQLITE:
                        conn.execute(
                            text(
                                """
                                INSERT INTO upcoming_formguide
                                  (runner_id, race_id, horse_no, form_text, raw_json)
                                VALUES
                                  (:runner_id, :race_id, :horse_no, :form_text, :raw_json)
                                ON CONFLICT(runner_id) DO UPDATE SET
                                  form_text=excluded.form_text,
                                  raw_json=excluded.raw_json,
                                  created_at=CURRENT_TIMESTAMP
                                """
                            ),
                            params,
                        )
                    else:
                        conn.execute(
                            text(
                                """
                                INSERT INTO upcoming_formguide
                                  (runner_id, race_id, horse_no, form_text, raw_json)
                                VALUES
                                  (:runner_id, :race_id, :horse_no, :form_text,
                                   CAST(:raw_json AS jsonb))
                                ON CONFLICT (runner_id) DO UPDATE SET
                                  form_text = EXCLUDED.form_text,
                                  raw_json = EXCLUDED.raw_json,
                                  created_at = NOW()
                                """
                            ),
                            params,
                        )
                    runner_n += 1
    finally:
        engine.dispose()

    waiting = with_text == 0
    return {
        "ok": True,
        "waiting": waiting,
        "phase": "waiting" if waiting else "ready",
        "schema": schema or SCHEMA_NAME,
        "race_date": payload.get("race_date"),
        "venue_code": payload.get("venue_code"),
        "content_updated_at": payload.get("content_updated_at"),
        "status": payload.get("status"),
        "race_count": len(race_ids),
        "race_ids": race_ids,
        "runner_upserted": runner_n,
        "runners_with_text": with_text,
        "detail": "全部 form_text 空／placeholder（waiting）" if waiting else None,
    }


def sync_meeting(
    racing_date: str,
    course: str,
    race_no: Optional[int] = None,
    from_file: Optional[str] = None,
    base_url: Optional[str] = None,
    *,
    auto_fetch: bool = True,
) -> Dict[str, Any]:
    """拉取後 upsert；export 空／partial／覆蓋不足時預設先 POST formguide/fetch。"""
    upstream_fetch: Optional[Dict[str, Any]] = None
    try:
        if from_file:
            payload = load_payload_file(from_file)
        else:
            payload = fetch_export(
                race_date=racing_date,
                venue=course,
                race_no=race_no,
                base_url=base_url,
            )
            if auto_fetch and export_needs_formguide_refresh(payload):
                upstream_fetch = trigger_formguide_fetch(
                    racing_date, course, base_url=base_url
                )
                try:
                    payload = fetch_export(
                        race_date=racing_date,
                        venue=course,
                        race_no=race_no,
                        base_url=base_url,
                    )
                except Exception as e:
                    return {
                        "ok": False,
                        "waiting": False,
                        "phase": "failed",
                        "error": f"formguide fetch 後 re-export 失敗：{e}",
                        "upstream_fetch": upstream_fetch,
                        "auto_fetched": True,
                        "racing_date": normalize_date(racing_date),
                        "course": course.upper(),
                    }
    except Exception as e:
        return {
            "ok": False,
            "waiting": False,
            "phase": "failed",
            "error": str(e),
            "upstream_fetch": upstream_fetch,
            "racing_date": normalize_date(racing_date),
            "course": course.upper(),
        }

    if str(payload.get("status") or "").strip().lower() == "unavailable":
        return {
            "ok": False,
            "waiting": False,
            "phase": "failed",
            "error": "status=unavailable",
            "status": payload.get("status"),
            "upstream_fetch": upstream_fetch,
            "auto_fetched": upstream_fetch is not None,
            "racing_date": normalize_date(racing_date),
            "course": course.upper(),
        }

    out = upsert_payload(payload)
    out["racing_date"] = normalize_date(racing_date)
    out["course"] = course.upper()
    if upstream_fetch is not None:
        out["auto_fetched"] = True
        out["upstream_fetch"] = upstream_fetch
        with_t, total = _form_text_coverage(payload)
        if total > 0 and (with_t / float(total)) < 0.80:
            out["waiting"] = True
            out["phase"] = "waiting"
            out["detail"] = (
                out.get("detail")
                or f"自動 formguide fetch 後短評仍不足 {with_t}/{total}"
            )
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sync api_jjjc formguide → upcoming_formguide")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--course", "--venue", dest="course", help="ST or HV")
    p.add_argument("--raceNo", type=int, default=None)
    p.add_argument("--from-file", dest="from_file")
    p.add_argument("--base-url", dest="base_url", default=None)
    args = p.parse_args(argv)

    if not args.from_file and (not args.date or not args.course):
        p.error("需要 --date 與 --course，或改用 --from-file")

    result = sync_meeting(
        racing_date=args.date or "",
        course=(args.course or "ST").upper(),
        race_no=args.raceNo,
        from_file=args.from_file,
        base_url=args.base_url,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
