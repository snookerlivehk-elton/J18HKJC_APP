"""
從 api_jjjc `GET /api/export/results` 同步官方賽果到 J18 historical 表。

Join key（與 api_jjjc 契約一致）：
  - race_id = YYYYMMDD + ST|HV + 場次兩位（如 20260906ST01）
  - horse_no
  - runner_id = {race_id}{horse_code}（無 code 時用 H{horse_no:02d}）

環境變數：
  - JJJC_API_BASE 或 JJJC_RESULTS_API_BASE：api_jjjc 根網址（勿尾斜線）
  - DATABASE_URL 或 DATABASE_URL_SYNC
  - USE_SQLITE=true 時寫入本地 j18_local.db

CLI：
  python jjjc_results_sync.py --date 2026-09-06 --course ST
  python jjjc_results_sync.py --from-file fixtures/jjjc_results_ST_20260906_R1.json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
    return (
        explicit
        or os.getenv("JJJC_API_BASE")
        or os.getenv("JJJC_RESULTS_API_BASE")
        or ""
    ).strip().rstrip("/")


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


def _runner_ids(race_id: str, horse_no: int, horse_code: Optional[str], race_date: str) -> Tuple[str, str, str]:
    brand = (horse_code or "").strip().upper() or None
    if brand:
        runner_id = f"{race_id}{brand}"
        year = race_date[:4] if race_date else "0000"
        horse_id = f"HK_{year}_{brand}"
    else:
        runner_id = f"{race_id}H{int(horse_no):02d}"
        horse_id = f"UNK_{race_id}_{int(horse_no):02d}"
        brand = f"H{int(horse_no):02d}"
    return runner_id, horse_id, brand


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
    url = f"{base}/api/export/results"
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


def _ensure_sqlite_schema() -> None:
    """本地測試：沿用 etl schema 初始化。"""
    if not USE_SQLITE:
        return
    from etl_pipeline import J18ETLPipeline

    J18ETLPipeline()  # triggers _init_sqlite_db


def upsert_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    寫入 race_meetings / races / runners（及可選 payouts）。
    以 official_hkjc 為準覆寫名次欄；raw_json 保留完整 runner 列。
    """
    schema = payload.get("schema")
    if schema and schema != "jjjc.results.v1":
        raise ValueError(f"不支援的 schema：{schema}")

    races: List[Dict[str, Any]] = list(payload.get("races") or [])
    if not races:
        return {
            "ok": True,
            "race_count": 0,
            "runner_upserted": 0,
            "payout_upserted": 0,
            "detail": "export 無 races",
        }

    _ensure_sqlite_schema()
    engine = create_engine(DATABASE_URL_SYNC)

    # meeting：J18 慣例 meeting_id = YYYY-MM-DD（etl_pipeline）
    race_dates = {_normalize_date(r.get("race_date") or payload.get("race_date") or "") for r in races}
    race_dates.discard("")

    runner_n = 0
    payout_n = 0
    race_ids: List[str] = []

    try:
        with engine.begin() as conn:
            for d in sorted(race_dates):
                day_races = [r for r in races if _normalize_date(r.get("race_date") or "") == d]
                conn.execute(
                    text(
                        """
                        INSERT INTO race_meetings (meeting_id, racing_date, race_count, raw_json)
                        VALUES (:mid, :rd, :rc, :raw)
                        ON CONFLICT (meeting_id) DO UPDATE SET
                          race_count = EXCLUDED.race_count,
                          raw_json = EXCLUDED.raw_json
                        """
                    ),
                    {
                        "mid": d,
                        "rd": d,
                        "rc": len(day_races),
                        "raw": json.dumps(
                            {
                                "source": "jjjc_results_sync",
                                "schema": schema,
                                "venue_codes": sorted(
                                    {str(x.get("venue_code") or "") for x in day_races}
                                ),
                                "generated_at": payload.get("generated_at"),
                            },
                            ensure_ascii=False,
                        ),
                    },
                )

            for race in races:
                race_id = str(race.get("race_id") or "").strip()
                if not race_id:
                    continue
                race_date = _normalize_date(race.get("race_date") or payload.get("race_date") or "")
                meeting_id = race_date
                race_num = _safe_int(race.get("race_no")) or 0
                distance_m = _safe_int(race.get("distance_m"))
                going = race.get("going")
                course_text = race.get("course")  # 草地／泥地等，非 ST/HV
                race_ids.append(race_id)

                conn.execute(
                    text(
                        """
                        INSERT INTO races (
                          race_id, meeting_id, race_num, title, race_name, class,
                          distance_text, distance_m, course, ground, raw_detail_json
                        ) VALUES (
                          :race_id, :meeting_id, :race_num, :title, :race_name, :klass,
                          :distance_text, :distance_m, :course, :ground, :raw
                        )
                        ON CONFLICT (race_id) DO UPDATE SET
                          race_name = COALESCE(EXCLUDED.race_name, races.race_name),
                          class = COALESCE(EXCLUDED.class, races.class),
                          distance_m = COALESCE(EXCLUDED.distance_m, races.distance_m),
                          distance_text = COALESCE(EXCLUDED.distance_text, races.distance_text),
                          course = COALESCE(EXCLUDED.course, races.course),
                          ground = COALESCE(EXCLUDED.ground, races.ground),
                          raw_detail_json = EXCLUDED.raw_detail_json
                        """
                    ),
                    {
                        "race_id": race_id,
                        "meeting_id": meeting_id,
                        "race_num": race_num,
                        "title": f"R{race_num}" if race_num else None,
                        "race_name": race.get("race_name"),
                        "klass": race.get("race_class"),
                        "distance_text": f"{distance_m}米" if distance_m else None,
                        "distance_m": distance_m,
                        "course": course_text,
                        "ground": going,
                        "raw": json.dumps(race, ensure_ascii=False),
                    },
                )

                for ru in race.get("runners") or []:
                    horse_no = _safe_int(ru.get("horse_no"))
                    if horse_no is None:
                        continue
                    horse_code = ru.get("horse_code")
                    runner_id, horse_id, brand = _runner_ids(
                        race_id, horse_no, horse_code, race_date
                    )
                    fin_num = _safe_int(ru.get("finish_order_num"))
                    if fin_num is None:
                        fin_num = _safe_int(ru.get("finishing_position"))
                    fin_raw = ru.get("finishing_position_raw")
                    if fin_raw is None and fin_num is not None:
                        fin_raw = str(fin_num)
                    win_odds = _safe_float(ru.get("win_odds"))
                    raw_meta = {
                        **ru,
                        "source": race.get("source") or "official_hkjc",
                        "synced_via": "jjjc_results_sync",
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    }

                    conn.execute(
                        text(
                            """
                            INSERT INTO runners (
                              runner_id, race_id, horse_id, horse_no, brand_num, horse_name,
                              finish_order_raw, finish_order_num, final_time,
                              jockey_name, trainer_name, handicap_weight, bar_draw,
                              horse_body_weight, scratched, win_probability_raw, raw_json
                            ) VALUES (
                              :runner_id, :race_id, :horse_id, :horse_no, :brand_num, :horse_name,
                              :finish_order_raw, :finish_order_num, :final_time,
                              :jockey_name, :trainer_name, :handicap_weight, :bar_draw,
                              :horse_body_weight, :scratched, :win_odds, :raw_json
                            )
                            ON CONFLICT (runner_id) DO UPDATE SET
                              horse_name = COALESCE(EXCLUDED.horse_name, runners.horse_name),
                              finish_order_raw = EXCLUDED.finish_order_raw,
                              finish_order_num = EXCLUDED.finish_order_num,
                              final_time = COALESCE(EXCLUDED.final_time, runners.final_time),
                              jockey_name = COALESCE(EXCLUDED.jockey_name, runners.jockey_name),
                              trainer_name = COALESCE(EXCLUDED.trainer_name, runners.trainer_name),
                              handicap_weight = COALESCE(EXCLUDED.handicap_weight, runners.handicap_weight),
                              bar_draw = COALESCE(EXCLUDED.bar_draw, runners.bar_draw),
                              horse_body_weight = COALESCE(EXCLUDED.horse_body_weight, runners.horse_body_weight),
                              win_probability_raw = COALESCE(EXCLUDED.win_probability_raw, runners.win_probability_raw),
                              raw_json = EXCLUDED.raw_json
                            """
                        ),
                        {
                            "runner_id": runner_id,
                            "race_id": race_id,
                            "horse_id": horse_id,
                            "horse_no": horse_no,
                            "brand_num": brand,
                            "horse_name": ru.get("horse_name"),
                            "finish_order_raw": str(fin_raw) if fin_raw is not None else None,
                            "finish_order_num": fin_num,
                            "final_time": ru.get("finish_time"),
                            "jockey_name": ru.get("jockey_name"),
                            "trainer_name": ru.get("trainer_name"),
                            "handicap_weight": _safe_float(ru.get("actual_weight")),
                            "bar_draw": _safe_int(ru.get("draw")),
                            "horse_body_weight": _safe_float(ru.get("declared_horse_weight")),
                            "scratched": False,
                            "win_odds": str(win_odds) if win_odds is not None else None,
                            "raw_json": json.dumps(raw_meta, ensure_ascii=False),
                        },
                    )
                    runner_n += 1

                for div in race.get("dividends") or []:
                    amount = _safe_float(div.get("amount"))
                    if amount is None:
                        continue
                    pool = str(div.get("pool") or "").strip() or "UNKNOWN"
                    combo = str(div.get("combination") or "").strip() or "-"
                    # 避免重複：先刪同 race+type+combo 再插（兩庫相容）
                    conn.execute(
                        text(
                            """
                            DELETE FROM payouts
                            WHERE race_id = :race_id AND bet_type = :bt AND combination = :combo
                            """
                        ),
                        {"race_id": race_id, "bt": pool, "combo": combo},
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO payouts (race_id, bet_type, combination, payout_amount, raw_json)
                            VALUES (:race_id, :bt, :combo, :amt, :raw)
                            """
                        ),
                        {
                            "race_id": race_id,
                            "bt": pool,
                            "combo": combo,
                            "amt": amount,
                            "raw": json.dumps(div, ensure_ascii=False),
                        },
                    )
                    payout_n += 1
    finally:
        engine.dispose()

    return {
        "ok": True,
        "schema": schema,
        "race_date": payload.get("race_date"),
        "venue_code": payload.get("venue_code"),
        "race_count": len(race_ids),
        "race_ids": race_ids,
        "runner_upserted": runner_n,
        "payout_upserted": payout_n,
        "source_preference": payload.get("source_preference"),
    }


def sync_meeting(
    racing_date: str,
    course: str,
    race_no: Optional[int] = None,
    from_file: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """拉取（或讀檔）後 upsert；供 CLI 與 meeting_pipeline 呼叫。"""
    if from_file:
        payload = load_payload_file(from_file)
    else:
        payload = fetch_export(
            race_date=racing_date,
            venue=course,
            race_no=race_no,
            base_url=base_url,
        )
    # 若 API 尚無資料，允許空 races
    if not payload.get("races") and not from_file:
        return {
            "ok": False,
            "error": "export 無賽果（api_jjjc 可能尚未 fetch）。請先對該日跑 results fetch。",
            "payload_keys": list(payload.keys()),
        }
    out = upsert_payload(payload)
    out["racing_date"] = _normalize_date(racing_date)
    out["course"] = course.upper()
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sync api_jjjc results export → J18 runners")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--course", "--venue", dest="course", help="ST or HV")
    p.add_argument("--raceNo", type=int, default=None)
    p.add_argument("--from-file", dest="from_file", help="本機 jjjc.results.v1 JSON")
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
