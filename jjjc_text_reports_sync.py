"""
從 api_jjjc `GET /api/export/text-reports` 同步沿途走勢／事故報告 → text_reports。

schema：jjjc.text_reports.v1
report_type：running_comment | incident_report
可選 query：&report_type=…

映射：
  reports[].runners[].text → text_reports.report_text
  is_placeholder=true／空字 → 略過（視為 waiting，不寫假內容）
  entity_type=runner；entity_id 優先對歷史 runners.runner_id（race_id+horse_no），
    其次 upcoming_runners，最後 {race_id}_{horse_no}

CLI：
  python jjjc_text_reports_sync.py --date 2026-09-06 --course ST
  python jjjc_text_reports_sync.py --from-file fixtures/jjjc_text_reports_ST_20260906_R1.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE
from jjjc_export_common import (
    classify_payload_status,
    content_meta,
    database_url_sync,
    effective_text,
    fetch_export_get,
    is_placeholder,
    load_payload_file,
    normalize_date,
    safe_int,
)

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

DATABASE_URL_SYNC = database_url_sync(USE_SQLITE, SQLITE_DB_PATH)

SCHEMA_NAME = "jjjc.text_reports.v1"
EXPORT_PATH = "/api/export/text-reports"
ALLOWED_TYPES = frozenset({"running_comment", "incident_report"})


def fetch_export(
    race_date: str,
    venue: str,
    race_no: Optional[int] = None,
    report_type: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    extra = {}
    if report_type:
        extra["report_type"] = report_type
    return fetch_export_get(
        EXPORT_PATH,
        race_date=race_date,
        venue=venue,
        race_no=race_no,
        extra_params=extra or None,
        base_url=base_url,
        timeout=timeout,
    )


def _ensure_table() -> None:
    if USE_SQLITE:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS text_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    report_text TEXT NOT NULL,
                    report_text_clean TEXT,
                    source_api TEXT,
                    language TEXT DEFAULT 'zh-HK',
                    raw_json TEXT,
                    nlp_result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_text_reports_entity
                ON text_reports(entity_type, entity_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_text_reports_lookup
                ON text_reports(entity_type, entity_id, report_type)
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
                    CREATE TABLE IF NOT EXISTS text_reports (
                        id SERIAL PRIMARY KEY,
                        entity_type VARCHAR(20) NOT NULL,
                        entity_id VARCHAR(50) NOT NULL,
                        report_type VARCHAR(50) NOT NULL,
                        report_text TEXT NOT NULL,
                        report_text_clean TEXT,
                        source_api VARCHAR(100),
                        language VARCHAR(20) DEFAULT 'zh-HK',
                        raw_json JSONB,
                        nlp_result TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_text_reports_entity
                    ON text_reports(entity_type, entity_id)
                    """
                )
            )
    finally:
        engine.dispose()


def _resolve_entity_id(conn, race_id: str, horse_no: int) -> str:
    """優先歷史 runners，其次 upcoming，最後 race_id_horse_no。"""
    for sql in (
        """
        SELECT runner_id FROM runners
        WHERE race_id = :race_id AND horse_no = :horse_no
        LIMIT 1
        """,
        """
        SELECT runner_id FROM upcoming_runners
        WHERE race_id = :race_id AND horse_no = :horse_no
        LIMIT 1
        """,
    ):
        nested = conn.begin_nested()
        try:
            row = conn.execute(
                text(sql),
                {"race_id": race_id, "horse_no": horse_no},
            ).first()
            nested.commit()
            if row and row[0]:
                return str(row[0])
        except Exception:
            nested.rollback()

    return f"{race_id}_{horse_no}"


def _existing_fingerprint(conn, entity_id: str, report_type: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    row = conn.execute(
        text(
            """
            SELECT id, report_text, raw_json FROM text_reports
            WHERE entity_type = 'runner'
              AND entity_id = :eid
              AND report_type = :rtype
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"eid": entity_id, "rtype": report_type},
    ).mappings().first()
    if not row:
        return None, None, None
    raw = row.get("raw_json")
    cua = None
    if raw:
        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(obj, dict):
                cua = obj.get("content_updated_at")
        except (TypeError, json.JSONDecodeError):
            pass
    return int(row["id"]), str(row["report_text"] or ""), cua


def upsert_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    schema = payload.get("schema")
    if schema and schema != SCHEMA_NAME:
        raise ValueError(f"不支援的 schema：{schema}")

    reports: List[Dict[str, Any]] = list(payload.get("reports") or [])
    empty = not reports
    phase = classify_payload_status(payload, empty=empty)
    if empty:
        return {
            "ok": True,
            "waiting": True,
            "phase": phase,
            "report_count": 0,
            "runner_upserted": 0,
            "detail": "export reports=[]（waiting）",
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
    engine: Engine = create_engine(DATABASE_URL_SYNC)
    upserted = 0
    skipped_placeholder = 0
    skipped_unchanged = 0
    cleared_nlp = 0
    report_ids: List[str] = []

    try:
        with engine.begin() as conn:
            for rep in reports:
                rtype = str(rep.get("report_type") or "").strip()
                if rtype not in ALLOWED_TYPES:
                    continue
                race_id = str(rep.get("race_id") or "").strip()
                if not race_id:
                    continue
                report_ids.append(f"{rtype}:{race_id}")
                meta = content_meta(payload, rep if isinstance(rep, dict) else None)
                cua = meta.get("content_updated_at")

                for ru in rep.get("runners") or []:
                    horse_no = safe_int(ru.get("horse_no"))
                    if horse_no is None:
                        continue
                    if is_placeholder(ru):
                        skipped_placeholder += 1
                        continue
                    body = effective_text(ru, "text", "report_text")
                    if not body:
                        skipped_placeholder += 1
                        continue

                    entity_id = _resolve_entity_id(conn, race_id, horse_no)
                    eid_row, old_text, old_cua = _existing_fingerprint(conn, entity_id, rtype)

                    # 幂等：content_updated_at 未變且正文相同 → 跳過（保留 nlp_result）
                    if (
                        eid_row is not None
                        and old_text == body
                        and cua
                        and old_cua
                        and str(cua) == str(old_cua)
                    ):
                        skipped_unchanged += 1
                        continue

                    raw_obj = {
                        **meta,
                        "race_id": race_id,
                        "horse_no": horse_no,
                        "report_type": rtype,
                        "is_placeholder": False,
                        "runner": ru,
                    }
                    raw_s = json.dumps(raw_obj, ensure_ascii=False)
                    source_api = f"jjjc{EXPORT_PATH}"

                    if eid_row is not None:
                        # 正文變更 → 清 nlp_result 待重跑
                        if old_text != body:
                            cleared_nlp += 1
                        if USE_SQLITE:
                            conn.execute(
                                text(
                                    """
                                    UPDATE text_reports SET
                                      report_text = :txt,
                                      raw_json = :raw,
                                      source_api = :src,
                                      nlp_result = CASE
                                        WHEN report_text = :txt THEN nlp_result ELSE NULL
                                      END,
                                      updated_at = CURRENT_TIMESTAMP
                                    WHERE id = :id
                                    """
                                ),
                                {
                                    "txt": body,
                                    "raw": raw_s,
                                    "src": source_api,
                                    "id": eid_row,
                                },
                            )
                        else:
                            conn.execute(
                                text(
                                    """
                                    UPDATE text_reports SET
                                      report_text = :txt,
                                      raw_json = CAST(:raw AS jsonb),
                                      source_api = :src,
                                      nlp_result = CASE
                                        WHEN report_text = :txt THEN nlp_result ELSE NULL
                                      END,
                                      updated_at = NOW()
                                    WHERE id = :id
                                    """
                                ),
                                {
                                    "txt": body,
                                    "raw": raw_s,
                                    "src": source_api,
                                    "id": eid_row,
                                },
                            )
                    else:
                        if USE_SQLITE:
                            conn.execute(
                                text(
                                    """
                                    INSERT INTO text_reports
                                      (entity_type, entity_id, report_type, report_text,
                                       source_api, language, raw_json)
                                    VALUES
                                      ('runner', :eid, :rtype, :txt, :src, 'zh-HK', :raw)
                                    """
                                ),
                                {
                                    "eid": entity_id,
                                    "rtype": rtype,
                                    "txt": body,
                                    "src": source_api,
                                    "raw": raw_s,
                                },
                            )
                        else:
                            conn.execute(
                                text(
                                    """
                                    INSERT INTO text_reports
                                      (entity_type, entity_id, report_type, report_text,
                                       source_api, language, raw_json)
                                    VALUES
                                      ('runner', :eid, :rtype, :txt, :src, 'zh-HK',
                                       CAST(:raw AS jsonb))
                                    """
                                ),
                                {
                                    "eid": entity_id,
                                    "rtype": rtype,
                                    "txt": body,
                                    "src": source_api,
                                    "raw": raw_s,
                                },
                            )
                    upserted += 1
    finally:
        engine.dispose()

    waiting = upserted == 0 and skipped_placeholder > 0
    return {
        "ok": True,
        "waiting": waiting,
        "phase": "waiting" if waiting else "ready",
        "schema": schema or SCHEMA_NAME,
        "race_date": payload.get("race_date"),
        "venue_code": payload.get("venue_code"),
        "content_updated_at": payload.get("content_updated_at"),
        "status": payload.get("status"),
        "report_count": len(report_ids),
        "report_keys": report_ids,
        "runner_upserted": upserted,
        "skipped_placeholder_or_empty": skipped_placeholder,
        "skipped_unchanged": skipped_unchanged,
        "nlp_cleared_on_change": cleared_nlp,
        "detail": "僅 placeholder／空字（waiting）" if waiting else None,
    }


def sync_meeting(
    racing_date: str,
    course: str,
    race_no: Optional[int] = None,
    report_type: Optional[str] = None,
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
                report_type=report_type,
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

    if str(payload.get("status") or "").strip().lower() == "unavailable":
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
    if report_type:
        out["report_type_filter"] = report_type
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sync api_jjjc text-reports → text_reports")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--course", "--venue", dest="course", help="ST or HV")
    p.add_argument("--raceNo", type=int, default=None)
    p.add_argument(
        "--report-type",
        dest="report_type",
        choices=sorted(ALLOWED_TYPES),
        default=None,
    )
    p.add_argument("--from-file", dest="from_file")
    p.add_argument("--base-url", dest="base_url", default=None)
    args = p.parse_args(argv)

    if not args.from_file and (not args.date or not args.course):
        p.error("需要 --date 與 --course，或改用 --from-file")

    result = sync_meeting(
        racing_date=args.date or "",
        course=(args.course or "ST").upper(),
        race_no=args.raceNo,
        report_type=args.report_type,
        from_file=args.from_file,
        base_url=args.base_url,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
