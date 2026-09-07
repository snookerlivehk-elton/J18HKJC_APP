"""
從 api_jjjc `GET /api/export/racecard` 同步賽前排位到 J18 upcoming_* 表。

Join key（與 api_jjjc 契約一致）：
  - race_id = YYYYMMDD + ST|HV + 場次兩位（如 20260909HV01）
  - horse_no
  - runner_id = {race_id}_{horse_no}（與既有 racecard_crawler 一致）

環境變數：
  - JJJC_API_BASE 或 JJJC_RESULTS_API_BASE：api_jjjc 根網址（勿尾斜線）
  - DATABASE_URL 或 DATABASE_URL_SYNC
  - USE_SQLITE=true 時寫入本地 j18_local.db

CLI：
  python jjjc_racecard_sync.py --date 2026-09-09 --course HV
  python jjjc_racecard_sync.py --from-file fixtures/jjjc_racecard_HV_20260909_R1.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import create_engine, text

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv("DATABASE_URL") or os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )
    if DATABASE_URL_SYNC.startswith("postgres://"):
        DATABASE_URL_SYNC = DATABASE_URL_SYNC.replace("postgres://", "postgresql://", 1)


def _api_base(explicit: Optional[str] = None) -> str:
    base = (
        explicit
        or os.getenv("JJJC_API_BASE")
        or os.getenv("JJJC_RESULTS_API_BASE")
        or ""
    ).strip().rstrip("/")
    return base


def _normalize_date(d: str) -> str:
    s = str(d or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def _safe_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def fetch_export(
    race_date: str,
    venue: str,
    race_no: Optional[int] = None,
    base_url: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    base = _api_base(base_url)
    if not base:
        raise ValueError(
            "未設定 JJJC_API_BASE（或 JJJC_RESULTS_API_BASE）。"
            "或改用 --from-file 讀取本機 export JSON。"
        )
    params: Dict[str, Any] = {"date": _normalize_date(race_date), "venue": venue.upper()}
    if race_no is not None:
        params["raceNo"] = int(race_no)
    url = f"{base}/api/export/racecard"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        payload = r.json()
    if not isinstance(payload, dict):
        raise ValueError("export 回應非 JSON object")
    return payload


def load_payload_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("file payload 非 JSON object")
    return payload


def _ensure_upcoming_tables() -> None:
    """確保 upcoming_* 存在（與 racecard_crawler.init_db 對齊）。"""
    if USE_SQLITE:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        try:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS upcoming_races (
                    race_id TEXT PRIMARY KEY,
                    racing_date DATE,
                    race_num INTEGER,
                    course TEXT,
                    race_name TEXT,
                    class TEXT,
                    distance_m INTEGER,
                    track TEXT,
                    ground TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS upcoming_runners (
                    runner_id TEXT PRIMARY KEY,
                    race_id TEXT,
                    horse_no INTEGER,
                    horse_name TEXT,
                    horse_code TEXT,
                    draw INTEGER,
                    jockey_name TEXT,
                    trainer_name TEXT,
                    handicap_weight NUMERIC,
                    horse_weight NUMERIC,
                    rating INTEGER,
                    rating_delta INTEGER,
                    gear TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (race_id) REFERENCES upcoming_races(race_id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()
        finally:
            conn.close()
        return

    engine = create_engine(DATABASE_URL_SYNC)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS upcoming_races (
                    race_id VARCHAR(50) PRIMARY KEY,
                    racing_date DATE,
                    race_num INT,
                    course VARCHAR(10),
                    race_name VARCHAR(100),
                    class VARCHAR(50),
                    distance_m INT,
                    track VARCHAR(50),
                    ground VARCHAR(50),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS upcoming_runners (
                    runner_id VARCHAR(50) PRIMARY KEY,
                    race_id VARCHAR(50) REFERENCES upcoming_races(race_id) ON DELETE CASCADE,
                    horse_no INT,
                    horse_name VARCHAR(100),
                    horse_code VARCHAR(20),
                    draw INT,
                    jockey_name VARCHAR(50),
                    trainer_name VARCHAR(50),
                    handicap_weight NUMERIC,
                    horse_weight NUMERIC,
                    rating INT,
                    rating_delta INT,
                    gear VARCHAR(50),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )


def upsert_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    schema = payload.get("schema")
    if schema and schema != "jjjc.racecard.v1":
        raise ValueError(f"不支援的 schema：{schema}")

    races: List[Dict[str, Any]] = list(payload.get("races") or [])
    if not races:
        return {
            "ok": True,
            "race_count": 0,
            "runner_upserted": 0,
            "detail": "export 無 races",
        }

    _ensure_upcoming_tables()
    engine = create_engine(DATABASE_URL_SYNC)

    runner_n = 0
    race_ids: List[str] = []

    try:
        with engine.begin() as conn:
            for race in races:
                race_id = str(race.get("race_id") or "").strip()
                if not race_id:
                    continue
                race_date = _normalize_date(
                    race.get("race_date") or payload.get("race_date") or ""
                )
                venue = str(
                    race.get("venue_code") or payload.get("venue_code") or ""
                ).upper()
                race_num = _safe_int(race.get("race_no")) or 0
                race_ids.append(race_id)

                conn.execute(
                    text(
                        """
                        INSERT INTO upcoming_races
                          (race_id, racing_date, race_num, course, race_name, class,
                           distance_m, track, ground)
                        VALUES
                          (:race_id, :racing_date, :race_num, :course, :race_name, :klass,
                           :distance_m, :track, :ground)
                        ON CONFLICT (race_id) DO UPDATE SET
                          racing_date = EXCLUDED.racing_date,
                          race_num = EXCLUDED.race_num,
                          course = EXCLUDED.course,
                          race_name = COALESCE(EXCLUDED.race_name, upcoming_races.race_name),
                          class = COALESCE(EXCLUDED.class, upcoming_races.class),
                          distance_m = COALESCE(EXCLUDED.distance_m, upcoming_races.distance_m),
                          track = COALESCE(EXCLUDED.track, upcoming_races.track),
                          ground = COALESCE(EXCLUDED.ground, upcoming_races.ground)
                        """
                    ),
                    {
                        "race_id": race_id,
                        "racing_date": race_date,
                        "race_num": race_num,
                        "course": venue,
                        "race_name": race.get("race_name"),
                        "klass": race.get("race_class"),
                        "distance_m": _safe_int(race.get("distance_m")),
                        "track": race.get("track") or race.get("surface"),
                        "ground": race.get("ground") or race.get("go_ch") or race.get("go_en"),
                    },
                )

                for ru in race.get("runners") or []:
                    horse_no = _safe_int(ru.get("horse_no"))
                    if horse_no is None:
                        continue
                    runner_id = str(ru.get("runner_id") or "").strip() or f"{race_id}_{horse_no}"
                    conn.execute(
                        text(
                            """
                            INSERT INTO upcoming_runners
                              (runner_id, race_id, horse_no, horse_name, horse_code, draw,
                               jockey_name, trainer_name, handicap_weight, horse_weight,
                               rating, rating_delta, gear)
                            VALUES
                              (:runner_id, :race_id, :horse_no, :horse_name, :horse_code, :draw,
                               :jockey_name, :trainer_name, :handicap_weight, :horse_weight,
                               :rating, :rating_delta, :gear)
                            ON CONFLICT (runner_id) DO UPDATE SET
                              horse_name = COALESCE(EXCLUDED.horse_name, upcoming_runners.horse_name),
                              horse_code = COALESCE(EXCLUDED.horse_code, upcoming_runners.horse_code),
                              draw = COALESCE(EXCLUDED.draw, upcoming_runners.draw),
                              jockey_name = COALESCE(EXCLUDED.jockey_name, upcoming_runners.jockey_name),
                              trainer_name = COALESCE(EXCLUDED.trainer_name, upcoming_runners.trainer_name),
                              handicap_weight = COALESCE(EXCLUDED.handicap_weight, upcoming_runners.handicap_weight),
                              horse_weight = COALESCE(EXCLUDED.horse_weight, upcoming_runners.horse_weight),
                              rating = COALESCE(EXCLUDED.rating, upcoming_runners.rating),
                              rating_delta = COALESCE(EXCLUDED.rating_delta, upcoming_runners.rating_delta),
                              gear = COALESCE(EXCLUDED.gear, upcoming_runners.gear)
                            """
                        ),
                        {
                            "runner_id": runner_id,
                            "race_id": race_id,
                            "horse_no": horse_no,
                            "horse_name": ru.get("horse_name")
                            or ru.get("horse_name_ch")
                            or ru.get("horse_name_en"),
                            "horse_code": ru.get("horse_code"),
                            "draw": _safe_int(ru.get("draw")),
                            "jockey_name": ru.get("jockey_name")
                            or ru.get("jockey_name_ch")
                            or ru.get("jockey_name_en"),
                            "trainer_name": ru.get("trainer_name")
                            or ru.get("trainer_name_ch")
                            or ru.get("trainer_name_en"),
                            "handicap_weight": _safe_float(ru.get("handicap_weight")),
                            "horse_weight": _safe_float(ru.get("horse_weight")),
                            "rating": _safe_int(ru.get("rating")),
                            "rating_delta": _safe_int(ru.get("rating_delta")),
                            "gear": ru.get("gear"),
                        },
                    )
                    runner_n += 1
    finally:
        engine.dispose()

    return {
        "ok": True,
        "schema": schema,
        "race_date": payload.get("race_date"),
        "venue_code": payload.get("venue_code"),
        "source": payload.get("source"),
        "race_count": len(race_ids),
        "race_ids": race_ids,
        "runner_upserted": runner_n,
    }


def sync_meeting(
    racing_date: str,
    course: str,
    race_no: Optional[int] = None,
    from_file: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    if from_file:
        payload = load_payload_file(from_file)
    else:
        payload = fetch_export(
            race_date=racing_date,
            venue=course,
            race_no=race_no,
            base_url=base_url,
        )
    if not payload.get("races") and not from_file:
        return {
            "ok": False,
            "error": "export 無排位（請先對該日跑 jjjc racecard fetch）。",
            "payload_keys": list(payload.keys()),
        }
    out = upsert_payload(payload)
    out["racing_date"] = _normalize_date(racing_date)
    out["course"] = course.upper()
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sync api_jjjc racecard export → J18 upcoming_*")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--course", "--venue", dest="course", help="ST or HV")
    p.add_argument("--raceNo", type=int, default=None)
    p.add_argument("--from-file", dest="from_file", help="本機 jjjc.racecard.v1 JSON")
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
