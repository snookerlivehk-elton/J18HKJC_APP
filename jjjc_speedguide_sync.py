"""
從 api_jjjc `GET /api/export/speedguide` 同步速勢能量 → upcoming_speedguide。

schema：jjjc.speedguide.v1
映射：
  energy           → speed_energy
  energy_delta     → speed_energy_delta
  fitness_rating   → form_rating
  energy_required  → raw_json.energy_required

CLI：
  python jjjc_speedguide_sync.py --date 2026-09-09 --course HV
  python jjjc_speedguide_sync.py --from-file fixtures/jjjc_speedguide_HV_20260909_R1.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE
from jjjc_export_common import (
    classify_payload_status,
    content_meta,
    database_url_sync,
    fetch_export_get,
    load_payload_file,
    normalize_date,
    safe_float,
    safe_int,
)

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

DATABASE_URL_SYNC = database_url_sync(USE_SQLITE, SQLITE_DB_PATH)

SCHEMA_NAME = "jjjc.speedguide.v1"
EXPORT_PATH = "/api/export/speedguide"


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


def _ensure_table() -> None:
    if USE_SQLITE:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS upcoming_speedguide (
                    runner_id TEXT PRIMARY KEY,
                    race_id TEXT,
                    horse_no INTEGER,
                    form_rating TEXT,
                    speed_energy NUMERIC,
                    speed_energy_delta NUMERIC,
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
                    CREATE TABLE IF NOT EXISTS upcoming_speedguide (
                        runner_id VARCHAR(50) PRIMARY KEY,
                        race_id VARCHAR(50),
                        horse_no INT,
                        form_rating VARCHAR(20),
                        speed_energy NUMERIC,
                        speed_energy_delta NUMERIC,
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
            "content_updated_at": payload.get("content_updated_at"),
        }

    _ensure_table()
    engine = create_engine(DATABASE_URL_SYNC)
    runner_n = 0
    race_ids: List[str] = []
    skipped_empty = 0

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
                    energy = safe_float(ru.get("energy"))
                    delta = safe_float(
                        ru.get("energy_delta")
                        if ru.get("energy_delta") is not None
                        else ru.get("delta")
                    )
                    fitness = ru.get("fitness_rating")
                    form_rating = (
                        None if fitness is None or str(fitness).strip() == "" else str(fitness).strip()
                    )
                    # 全空殼列：仍可 upsert 但視為未齊（不擋寫）
                    if energy is None and delta is None and form_rating is None:
                        skipped_empty += 1

                    runner_id = f"{race_id}_{horse_no}"
                    meta = content_meta(payload, race if isinstance(race, dict) else None)
                    raw_obj = {
                        **meta,
                        "horse_name": ru.get("horse_name"),
                        "energy": energy,
                        "energy_delta": delta,
                        "energy_required": safe_float(ru.get("energy_required")),
                        "fitness_rating": form_rating,
                        "runner": ru,
                    }
                    raw_s = json.dumps(raw_obj, ensure_ascii=False)
                    if USE_SQLITE:
                        conn.execute(
                            text(
                                """
                                INSERT INTO upcoming_speedguide
                                  (runner_id, race_id, horse_no, form_rating,
                                   speed_energy, speed_energy_delta, raw_json)
                                VALUES
                                  (:runner_id, :race_id, :horse_no, :form_rating,
                                   :speed_energy, :speed_energy_delta, :raw_json)
                                ON CONFLICT(runner_id) DO UPDATE SET
                                  form_rating=excluded.form_rating,
                                  speed_energy=excluded.speed_energy,
                                  speed_energy_delta=excluded.speed_energy_delta,
                                  raw_json=excluded.raw_json,
                                  created_at=CURRENT_TIMESTAMP
                                """
                            ),
                            {
                                "runner_id": runner_id,
                                "race_id": race_id,
                                "horse_no": horse_no,
                                "form_rating": form_rating,
                                "speed_energy": energy,
                                "speed_energy_delta": delta,
                                "raw_json": raw_s,
                            },
                        )
                    else:
                        conn.execute(
                            text(
                                """
                                INSERT INTO upcoming_speedguide
                                  (runner_id, race_id, horse_no, form_rating,
                                   speed_energy, speed_energy_delta, raw_json)
                                VALUES
                                  (:runner_id, :race_id, :horse_no, :form_rating,
                                   :speed_energy, :speed_energy_delta, CAST(:raw_json AS jsonb))
                                ON CONFLICT (runner_id) DO UPDATE SET
                                  form_rating = EXCLUDED.form_rating,
                                  speed_energy = EXCLUDED.speed_energy,
                                  speed_energy_delta = EXCLUDED.speed_energy_delta,
                                  raw_json = EXCLUDED.raw_json,
                                  created_at = NOW()
                                """
                            ),
                            {
                                "runner_id": runner_id,
                                "race_id": race_id,
                                "horse_no": horse_no,
                                "form_rating": form_rating,
                                "speed_energy": energy,
                                "speed_energy_delta": delta,
                                "raw_json": raw_s,
                            },
                        )
                    runner_n += 1
    finally:
        engine.dispose()

    return {
        "ok": True,
        "waiting": False,
        "phase": "ready",
        "schema": schema or SCHEMA_NAME,
        "race_date": payload.get("race_date"),
        "venue_code": payload.get("venue_code"),
        "content_updated_at": payload.get("content_updated_at"),
        "status": payload.get("status"),
        "race_count": len(race_ids),
        "race_ids": race_ids,
        "runner_upserted": runner_n,
        "runners_all_empty_fields": skipped_empty,
    }


def sync_meeting(
    racing_date: str,
    course: str,
    race_no: Optional[int] = None,
    from_file: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
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
    except Exception as e:
        return {
            "ok": False,
            "waiting": False,
            "phase": "failed",
            "error": str(e),
            "racing_date": normalize_date(racing_date),
            "course": course.upper(),
        }

    st = str(payload.get("status") or "").strip().lower()
    if st == "unavailable":
        return {
            "ok": False,
            "waiting": False,
            "phase": "failed",
            "error": "status=unavailable",
            "status": payload.get("status"),
            "racing_date": normalize_date(racing_date),
            "course": course.upper(),
        }

    out = upsert_payload(payload)
    out["racing_date"] = normalize_date(racing_date)
    out["course"] = course.upper()
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sync api_jjjc speedguide → upcoming_speedguide")
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
