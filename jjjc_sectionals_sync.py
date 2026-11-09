"""
從 api_jjjc 同步 R2 分段時間 → runner_sections / race_sectionals。

上游合約（已落地）：
  - GET /api/export/sectionals?date=&venue=ST|HV（可選 &raceNo=）
  - 別名：/api/sectionals、/api/export/sectional
  - schema：jjjc.sectionals.v1
  - 來源：race_cards WHERE kind='sectional'
  - Join：race_id + horse_no（runner_no 別名）
  - catalog product id：sectional

CLI：
  python jjjc_sectionals_sync.py --date 2026-09-16 --course HV
  python jjjc_sectionals_sync.py --from-file fixtures/jjjc_sectionals_HV_20260916_R1.json
  python jjjc_sectionals_sync.py --catalog
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import create_engine, text

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE, resolve_database_url
from jjjc_export_common import (
    classify_payload_status,
    content_meta,
    display_horse_name,
    fetch_catalog,
    fetch_export_get,
    horse_no_of,
    load_payload_file,
    looks_latin_name,
    make_race_id,
    meeting_id as make_meeting_id,
    normalize_date,
    normalize_venue,
    prefer_zh_text,
    safe_int,
)
from sectionals_store import (
    stages_from_race_times,
    stages_from_runner_payload,
    upsert_race_sectionals,
    upsert_runner_sections,
)

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

DATABASE_URL_SYNC = resolve_database_url()
SCHEMA_NAME = "jjjc.sectionals.v1"
EXPORT_PATH = "/api/export/sectionals"
EXPORT_PATH_CANDIDATES = (
    "/api/export/sectionals",
    "/api/export/sectional",
    "/api/sectionals",
)


def _ensure_sqlite() -> None:
    if not USE_SQLITE:
        return
    from etl_pipeline import J18ETLPipeline

    J18ETLPipeline()


def _runner_id(race_id: str, horse_no: int, horse_code: Optional[str] = None) -> Tuple[str, str]:
    brand = (horse_code or "").strip().upper() or None
    if brand:
        return f"{race_id}{brand}", brand
    return f"{race_id}H{int(horse_no):02d}", f"H{int(horse_no):02d}"


def _lookup_runner_id(conn, race_id: str, horse_no: int) -> Optional[str]:
    row = conn.execute(
        text(
            """
            SELECT runner_id FROM runners
            WHERE race_id = :rid AND horse_no = :hn
            LIMIT 1
            """
        ),
        {"rid": race_id, "hn": int(horse_no)},
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def _normalize_card_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    統一成 races[] 結構：
      {race_id, race_no, race_date, venue_code, race_sectionals?, runners:[{horse_no, sections|running_position|...}]}
    接受：
      - jjjc.sectionals.v1 {races:[...]}
      - race_cards dump {kind:sectional, card:{...}} 或 {cards:[...]}
      - {races:[{card:{...}}]}
    """
    schema = str(payload.get("schema") or "")
    if schema and schema not in (SCHEMA_NAME, "jjjc.race_cards.v1", ""):
        # 仍嘗試解析；唔即刻 fail
        pass

    # 已是 races[]
    races = list(payload.get("races") or [])
    if races:
        return [_expand_race_row(r, payload) for r in races]

    # cards[] dump
    cards = list(payload.get("cards") or [])
    if not cards and str(payload.get("kind") or "").lower() == "sectional":
        cards = [payload]
    out = []
    for c in cards:
        if str(c.get("kind") or "sectional").lower() not in ("sectional", "sectionals", ""):
            continue
        out.append(_expand_race_row(c, payload))
    return out


def _expand_race_row(row: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Any]:
    card = row.get("card") if isinstance(row.get("card"), dict) else {}
    race_date = normalize_date(
        row.get("race_date") or card.get("race_date") or root.get("race_date") or ""
    )
    venue = normalize_venue(
        row.get("venue_code") or card.get("venue_code") or root.get("venue_code")
    ) or ""
    race_no = safe_int(row.get("race_no") or card.get("race_no") or row.get("raceNo"))
    race_id = str(row.get("race_id") or card.get("race_id") or "").strip()
    if not race_id and race_date and venue and race_no:
        race_id = make_race_id(race_date, venue, int(race_no))

    runners_src = (
        row.get("runners")
        or card.get("runners")
        or card.get("horses")
        or []
    )
    runners = []
    for ru in runners_src:
        if not isinstance(ru, dict):
            continue
        hn = horse_no_of(ru)
        if hn is None:
            continue
        # 合併 card 內 sections／running_position 等到同一 dict 畀 stages_from_runner_payload
        merged = dict(ru)
        if "sections" not in merged and isinstance(card.get("sections"), dict):
            # 罕見：賽事級 sections 唔套去馬
            pass
        runners.append(
            {
                "horse_no": hn,
                "runner_no": ru.get("runner_no") or hn,
                "horse_code": ru.get("horse_code") or ru.get("brand_num"),
                "horse_name": ru.get("horse_name"),
                "running_position": ru.get("running_position")
                or ru.get("runningPosition"),
                "positions": ru.get("positions")
                if isinstance(ru.get("positions"), list)
                else None,
                "sectional_times": ru.get("sectional_times")
                or ru.get("section_times"),
                "sections": ru.get("sections") or ru.get("sectionals"),
                "raw": ru,
            }
        )

    race_times = (
        row.get("sectional_times")
        or row.get("race_sectional_times")
        or row.get("sectionals")
        or row.get("times")
        or card.get("sectional_times")
        or card.get("sectionals")
        or card.get("times")
    )
    # 累積時間另存；若無 split 秒數可用 cumulative 作備援顯示
    race_cumulative = (
        row.get("race_cumulative_times")
        or card.get("race_cumulative_times")
        or row.get("cumulative_times")
    )
    return {
        "race_id": race_id,
        "race_no": race_no,
        "race_date": race_date,
        "venue_code": venue,
        "meeting_id": row.get("meeting_id")
        or (make_meeting_id(race_date, venue) if race_date and venue else None),
        "runners": runners,
        "race_sectionals": race_times or race_cumulative,
        "race_cumulative_times": race_cumulative,
        "card": card or None,
        "raw": row,
    }


def discover_sectionals_path(base_url: Optional[str] = None) -> Optional[str]:
    """讀 catalog；若有 sectionals product 回 path。"""
    try:
        cat = fetch_catalog(base_url=base_url)
    except Exception:
        return None
    products = cat.get("products") or cat.get("exports") or cat.get("endpoints") or []
    if isinstance(products, dict):
        products = [
            {"id": k, **(v if isinstance(v, dict) else {"path": v})}
            for k, v in products.items()
        ]
    for p in products:
        if not isinstance(p, dict):
            continue
        blob = json.dumps(p, ensure_ascii=False).lower()
        if "sectional" in blob:
            path = p.get("path") or p.get("url") or p.get("href")
            if path:
                return str(path)
            pid = str(p.get("id") or p.get("name") or "")
            if pid:
                return f"/api/export/{pid}"
    return None


def fetch_export(
    race_date: str,
    venue: str,
    race_no: Optional[int] = None,
    base_url: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """
    優先 catalog 發現嘅 path，再試 EXPORT_PATH_CANDIDATES。
    全部 404 → 回傳 waiting 空殼（唔當 failed，方便 tick）。
    """
    paths: List[str] = []
    discovered = discover_sectionals_path(base_url=base_url)
    if discovered:
        paths.append(discovered)
    for p in EXPORT_PATH_CANDIDATES:
        if p not in paths:
            paths.append(p)

    last_err: Optional[Exception] = None
    for path in paths:
        # race-cards?kind= 要拆 query
        extra = None
        pure = path
        if "?" in path:
            pure, qs = path.split("?", 1)
            extra = {}
            for part in qs.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    extra[k] = v
        try:
            return fetch_export_get(
                pure,
                race_date=race_date,
                venue=venue,
                race_no=race_no,
                extra_params=extra,
                base_url=base_url,
                timeout=timeout,
            )
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response is not None and e.response.status_code == 404:
                continue
            raise
        except httpx.RequestError as e:
            last_err = e
            raise
    return {
        "schema": SCHEMA_NAME,
        "status": "waiting",
        "race_date": normalize_date(race_date),
        "venue_code": normalize_venue(venue),
        "races": [],
        "detail": "sectionals export 404（確認上游已部署／catalog product=sectional）",
        "last_error": str(last_err)[:200] if last_err else None,
    }


def upsert_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    races = _normalize_card_rows(payload)
    empty = not races or all(not r.get("runners") and not r.get("race_sectionals") for r in races)
    status = classify_payload_status(payload, empty=empty)
    if empty:
        return {
            "ok": status != "failed",
            "waiting": True,
            "schema": payload.get("schema") or SCHEMA_NAME,
            "race_count": 0,
            "runner_sections_upserted": 0,
            "race_sectionals_upserted": 0,
            "detail": payload.get("detail") or "無分段內容",
            "status": status,
        }

    _ensure_sqlite()
    engine = create_engine(DATABASE_URL_SYNC)
    section_n = 0
    race_sec_n = 0
    runner_touch = 0
    race_ids: List[str] = []
    missing_runner = 0

    try:
        with engine.begin() as conn:
            for race in races:
                race_id = str(race.get("race_id") or "").strip()
                if not race_id:
                    continue
                race_ids.append(race_id)
                race_sec_n += upsert_race_sectionals(
                    conn, race_id, stages_from_race_times(race.get("race_sectionals"))
                )
                for ru in race.get("runners") or []:
                    hn = horse_no_of(ru) if isinstance(ru, dict) else None
                    if hn is None:
                        hn = safe_int(ru.get("horse_no")) if isinstance(ru, dict) else None
                    if hn is None:
                        continue
                    rid = _lookup_runner_id(conn, race_id, int(hn))
                    if not rid:
                        # 未有 results runners：仍可用推斷 id（之後 results sync 會對上 horse_no）
                        rid, _ = _runner_id(
                            race_id, int(hn), (ru.get("horse_code") if isinstance(ru, dict) else None)
                        )
                        missing_runner += 1
                    # R2 常有中文馬名：補返 results 寫入嘅英文名（統計／UI 用）
                    if isinstance(ru, dict):
                        zh = display_horse_name(ru)
                        code = (ru.get("horse_code") or "").strip().upper() or None
                        if zh and not looks_latin_name(zh):
                            try:
                                row = conn.execute(
                                    text(
                                        "SELECT horse_name, brand_num FROM runners WHERE runner_id = :rid"
                                    ),
                                    {"rid": rid},
                                ).mappings().first()
                                if row:
                                    new_name = prefer_zh_text(zh, row.get("horse_name"))
                                    updates = {"rid": rid, "name": new_name}
                                    set_sql = "horse_name = :name"
                                    if code and not (row.get("brand_num") or "").strip():
                                        set_sql += ", brand_num = :brand"
                                        updates["brand"] = code
                                    if new_name and new_name != row.get("horse_name"):
                                        conn.execute(
                                            text(
                                                f"UPDATE runners SET {set_sql} WHERE runner_id = :rid"
                                            ),
                                            updates,
                                        )
                            except Exception:
                                pass
                    stages = stages_from_runner_payload(ru if isinstance(ru, dict) else {})
                    if not stages:
                        continue
                    # 附 content meta
                    for st in stages:
                        raw = dict(st.get("raw_json") or {})
                        raw.update(content_meta(payload, ru if isinstance(ru, dict) else {}))
                        st["raw_json"] = raw
                    n = upsert_runner_sections(conn, rid, stages)
                    section_n += n
                    if n:
                        runner_touch += 1
    finally:
        engine.dispose()

    return {
        "ok": True,
        "waiting": False,
        "schema": payload.get("schema") or SCHEMA_NAME,
        "race_date": payload.get("race_date"),
        "venue_code": payload.get("venue_code"),
        "meeting_id": payload.get("meeting_id"),
        "race_count": len(race_ids),
        "race_ids": race_ids,
        "runners_with_sections": runner_touch,
        "runner_sections_upserted": section_n,
        "race_sectionals_upserted": race_sec_n,
        "runners_without_results_row": missing_runner,
        "status": "ready",
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def _api_base(explicit: Optional[str] = None) -> str:
    from jjjc_export_common import api_base

    return api_base(explicit)


def _sectionals_payload_empty(payload: Dict[str, Any]) -> bool:
    races = list(payload.get("races") or [])
    if not races:
        return True
    status = str(payload.get("status") or "").lower()
    if status in {"empty", "unpublished", "waiting"}:
        return True
    with_time = payload.get("runners_with_sectional_time")
    if with_time is not None and int(with_time or 0) <= 0:
        return True
    return False


def trigger_sectionals_upstream_refresh(
    race_date: str,
    venue: str,
    *,
    base_url: Optional[str] = None,
    timeout: float = 300.0,
) -> Dict[str, Any]:
    """
    上游 export 空時，觸發 api_jjjc POST phase 補采分段。

    實測 2026-10-25／10-28／11-01／11-04：export status=empty，
    但 POST /api/phases/target + /api/phases/post/run 後即可 obtained。
    （無獨立 /api/sectionals/fetch。）
    """
    base = _api_base(base_url)
    if not base:
        return {"ok": False, "error": "未設定 JJJC_API_BASE"}
    v = str(venue or "").strip().upper()
    if v not in {"ST", "HV"}:
        return {"ok": False, "error": f"venue 必須係 ST|HV，收到：{venue!r}"}
    d = normalize_date(race_date)
    body = {"date": d, "venue": v}
    out: Dict[str, Any] = {"ok": True, "race_date": d, "venue_code": v}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            t = client.post(f"{base}/api/phases/target", json=body)
            try:
                parsed_t = t.json()
                t_body = parsed_t if isinstance(parsed_t, dict) else {"raw": parsed_t}
            except Exception:
                t_body = {"raw_text": (t.text or "")[:300]}
            out["target"] = {
                "ok": t.status_code < 400 and bool(t_body.get("ok", True)),
                "status_code": t.status_code,
                "response": t_body,
            }
            if t.status_code >= 400:
                out["ok"] = False
                out["error"] = f"phases/target HTTP {t.status_code}"
                return out

            r = client.post(f"{base}/api/phases/post/run", json=body)
            try:
                parsed_r = r.json()
                r_body = parsed_r if isinstance(parsed_r, dict) else {"raw": parsed_r}
            except Exception:
                r_body = {"raw_text": (r.text or "")[:300]}
            out["post_run"] = {
                "ok": r.status_code < 400 and bool(r_body.get("ok", True)),
                "status_code": r.status_code,
                "race_date": r_body.get("race_date"),
                "venue_code": r_body.get("venue_code"),
                "race_count": r_body.get("race_count"),
                "sectional_race_count": r_body.get("sectional_race_count"),
                "response": r_body,
            }
            if r.status_code >= 400 or not r_body.get("ok", True):
                out["ok"] = False
                out["error"] = (
                    f"phases/post/run HTTP {r.status_code}"
                    if r.status_code >= 400
                    else str(r_body.get("error") or r_body.get("detail") or "post/run failed")
                )
            return out
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "race_date": d, "venue_code": v}


def sync_meeting(
    racing_date: str,
    course: str,
    race_no: Optional[int] = None,
    from_file: Optional[str] = None,
    base_url: Optional[str] = None,
    *,
    auto_refresh: bool = True,
) -> Dict[str, Any]:
    """
    拉 sectionals export → upsert。

    export 空（預設）會先觸發上游 POST phase（target+post/run）再重試 export，
    避免作戰室長掛「只有走位、無分段秒數」而上游其實只差一槍補采。
    """
    upstream_refresh: Optional[Dict[str, Any]] = None
    if from_file:
        payload = load_payload_file(from_file)
    else:
        payload = fetch_export(
            race_date=racing_date,
            venue=course,
            race_no=race_no,
            base_url=base_url,
        )
        if auto_refresh and _sectionals_payload_empty(payload):
            upstream_refresh = trigger_sectionals_upstream_refresh(
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
                    "error": f"sectionals refresh 後 re-export 失敗：{e}",
                    "upstream_refresh": upstream_refresh,
                    "racing_date": normalize_date(racing_date),
                    "course": (normalize_venue(course) or course).upper(),
                }

    out = upsert_payload(payload)
    out["racing_date"] = normalize_date(racing_date)
    out["course"] = (normalize_venue(course) or course).upper()
    out["meeting_id"] = make_meeting_id(racing_date, course)
    if upstream_refresh is not None:
        out["upstream_refresh"] = upstream_refresh
        out["auto_refreshed"] = True
        if _sectionals_payload_empty(payload) and out.get("waiting"):
            detail = str(out.get("detail") or "無分段內容")
            if upstream_refresh.get("ok"):
                detail = (
                    f"{detail}（已自動 phases/post/run；"
                    f"sectional_race_count="
                    f"{(upstream_refresh.get('post_run') or {}).get('sectional_race_count')}"
                    "；上游可能仍未齊）"
                )
            else:
                detail = (
                    f"{detail}（自動 upstream refresh 失敗："
                    f"{upstream_refresh.get('error')}）"
                )
            out["detail"] = detail
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sync jjjc sectionals → runner_sections")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--course", "--venue", dest="course", help="ST or HV")
    p.add_argument("--raceNo", type=int, default=None)
    p.add_argument("--from-file", dest="from_file")
    p.add_argument("--base-url", dest="base_url")
    p.add_argument("--catalog", action="store_true", help="只印 /api/export/catalog")
    p.add_argument(
        "--no-auto-refresh",
        action="store_true",
        help="唔自動觸發上游 phases/post/run（即使 export 空）",
    )
    args = p.parse_args(argv)
    if args.catalog:
        print(json.dumps(fetch_catalog(base_url=args.base_url), ensure_ascii=False, indent=2))
        return 0
    if not args.from_file and (not args.date or not args.course):
        p.error("需要 --date/--course 或 --from-file")
    out = sync_meeting(
        racing_date=args.date or "",
        course=args.course or "",
        race_no=args.raceNo,
        from_file=args.from_file,
        base_url=args.base_url,
        auto_refresh=not bool(args.no_auto_refresh),
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
