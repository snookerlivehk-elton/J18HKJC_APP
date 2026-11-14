"""从马会 GraphQL 拉同一秒的独赢、位置、连赢、二重彩，并记下每次快照。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

import httpx
from sqlalchemy import create_engine, text

from etl_pipeline import resolve_database_url
from index_selection import (
    STRATEGY_SPECS,
    all_picks,
    finish_marks,
    hit_rate,
    placed_count,
)

HKJC_URL = "https://info.cld.hkjc.com/graphql/base-get/"
HK_TZ = timezone(timedelta(hours=8))
POOL_QUERY = """
query sp4e_racing_pmPool($date: String, $venueCode: String, $oddsTypes: [OddsType], $raceNo: Int) {
  raceMeetings(date: $date, venueCode: $venueCode) {
    pmPools(oddsTypes: $oddsTypes, raceNo: $raceNo) {
      id
      status
      sellStatus
      oddsType
      lastUpdateTime
      leg { number races }
      oddsNodes { combString oddsValue hotFavourite oddsDropValue }
    }
  }
}
"""
ODDS_TYPES = ["WIN", "PLA", "QIN", "QPL", "FCT"]
STALE_SECONDS = 25


def _engine():
    url = resolve_database_url(sqlite_fallback=os.getenv("USE_SQLITE", "true").lower() == "true")
    return create_engine(url)


def ensure_schema(engine=None) -> None:
    engine = engine or _engine()
    serial = "INTEGER PRIMARY KEY AUTOINCREMENT" if engine.dialect.name == "sqlite" else "BIGSERIAL PRIMARY KEY"
    ts = "TEXT" if engine.dialect.name == "sqlite" else "TIMESTAMPTZ DEFAULT NOW()"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS index_sel_snapshots (
                    id {serial},
                    race_id VARCHAR(50) NOT NULL,
                    captured_at {ts},
                    sell_status VARCHAR(30),
                    payload_json TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS index_sel_scores (
                    race_id VARCHAR(50) NOT NULL,
                    strategy_id VARCHAR(40) NOT NULL,
                    picks_json TEXT NOT NULL,
                    placed_n INT NOT NULL,
                    pick_n INT NOT NULL,
                    source VARCHAR(30) NOT NULL,
                    PRIMARY KEY (race_id, strategy_id)
                )
                """
            )
        )
    engine.dispose()


def _parse_odds(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    text_v = str(raw).strip().upper()
    if text_v in {"", "SCR", "---", "NULL"}:
        return None
    try:
        value = float(text_v)
    except ValueError:
        return None
    if value <= 1.0:
        return None
    return value


def _horse_no(comb: str) -> Optional[int]:
    try:
        return int(str(comb).strip())
    except ValueError:
        return None


def _pair(comb: str) -> Optional[Tuple[int, int]]:
    parts = [p for p in str(comb).replace("-", ",").split(",") if p.strip()]
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def parse_pools(pools: List[Mapping[str, Any]]) -> Dict[str, Any]:
    by_type = {str(pool.get("oddsType") or ""): pool for pool in pools}
    win_pool = by_type.get("WIN") or {}
    horses: Dict[int, Dict[str, Any]] = {}

    def ensure(no: int) -> Dict[str, Any]:
        row = horses.get(no)
        if row is None:
            row = {
                "no": no,
                "scratched": False,
                "win_odds": None,
                "place_odds": None,
                "win_drop": None,
            }
            horses[no] = row
        return row

    for node in win_pool.get("oddsNodes") or []:
        no = _horse_no(node.get("combString"))
        if no is None:
            continue
        row = ensure(no)
        odds = _parse_odds(node.get("oddsValue"))
        if odds is None and str(node.get("oddsValue") or "").upper() == "SCR":
            row["scratched"] = True
        row["win_odds"] = odds
        try:
            row["win_drop"] = float(node.get("oddsDropValue") or 0)
        except (TypeError, ValueError):
            row["win_drop"] = 0.0
    pla = by_type.get("PLA") or {}
    for node in pla.get("oddsNodes") or []:
        no = _horse_no(node.get("combString"))
        if no is None:
            continue
        row = ensure(no)
        odds = _parse_odds(node.get("oddsValue"))
        if odds is None and str(node.get("oddsValue") or "").upper() == "SCR":
            row["scratched"] = True
        row["place_odds"] = odds
    qin: Dict[str, float] = {}
    for node in (by_type.get("QIN") or {}).get("oddsNodes") or []:
        pair = _pair(node.get("combString"))
        odds = _parse_odds(node.get("oddsValue"))
        if pair and odds:
            a, b = sorted(pair)
            qin[f"{a},{b}"] = odds
    fct: Dict[str, float] = {}
    for node in (by_type.get("FCT") or {}).get("oddsNodes") or []:
        pair = _pair(node.get("combString"))
        odds = _parse_odds(node.get("oddsValue"))
        if pair and odds:
            fct[f"{pair[0]},{pair[1]}"] = odds
    pool_id = str(win_pool.get("id") or (pools[0].get("id") if pools else "") or "")
    meeting_date = ""
    if pool_id.startswith("MTG_") and len(pool_id) >= 12:
        meeting_date = pool_id[4:12]
    leg = (win_pool.get("leg") or (pools[0].get("leg") if pools else {}) or {})
    races = leg.get("races") or []
    race_no = int(races[0]) if races else None
    return {
        "meeting_date": meeting_date,
        "race_no": race_no,
        "sell_status": str(win_pool.get("sellStatus") or (pools[0].get("sellStatus") if pools else "") or ""),
        "pool_status": str(win_pool.get("status") or ""),
        "horses": [horses[k] for k in sorted(horses)],
        "qin": qin,
        "fct": fct,
    }


def fetch_race_pools(race_no: int, *, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    own = client is None
    client = client or httpx.Client(timeout=25.0)
    try:
        response = client.get(
            HKJC_URL,
            params={
                "query": POOL_QUERY,
                "variables": json.dumps(
                    {"raceNo": int(race_no), "oddsTypes": ODDS_TYPES},
                    separators=(",", ":"),
                ),
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://bet.hkjc.com/",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        meetings = ((payload.get("data") or {}).get("raceMeetings")) or []
        pools = (meetings[0].get("pmPools") if meetings else None) or []
        parsed = parse_pools(pools)
        parsed["race_no"] = parsed.get("race_no") or int(race_no)
        return parsed
    finally:
        if own:
            client.close()


def _venue_for_date(conn, yyyymmdd: str) -> str:
    rows = conn.execute(
        text("SELECT race_id FROM runners WHERE race_id LIKE :p LIMIT 30"),
        {"p": f"{yyyymmdd}%"},
    ).fetchall()
    codes = []
    for row in rows:
        rid = str(row[0] or "")
        if len(rid) >= 10:
            codes.append(rid[8:10])
    if not codes:
        try:
            upcoming = conn.execute(
                text(
                    """
                    SELECT race_id FROM upcoming_races
                    WHERE REPLACE(CAST(racing_date AS TEXT), '-', '') = :d
                    LIMIT 5
                    """
                ),
                {"d": yyyymmdd},
            ).fetchall()
        except Exception:
            upcoming = []
        for row in upcoming:
            rid = str(row[0] or "")
            if len(rid) >= 10:
                codes.append(rid[8:10])
    return codes[0] if codes else "ST"


def _attach_model(conn, race_id: str, horses: List[Dict[str, Any]]) -> None:
    try:
        rows = conn.execute(
        text(
            """
            SELECT s.horse_no, s.model_win_prob, s.fused_share
            FROM prediction_snapshots s
            JOIN prediction_snapshot_batches b ON b.batch_id = s.batch_id
            WHERE s.race_id = :race_id
              AND b.created_at = (
                SELECT MAX(b2.created_at)
                FROM prediction_snapshots s2
                JOIN prediction_snapshot_batches b2 ON b2.batch_id = s2.batch_id
                WHERE s2.race_id = :race_id
              )
            """
        ),
            {"race_id": race_id},
        ).fetchall()
    except Exception:
        return
    by_no = {int(r[0]): r for r in rows}
    for horse in horses:
        row = by_no.get(int(horse["no"]))
        horse["model_share"] = float(row[1]) if row and row[1] is not None else None
        horse["fused_share"] = float(row[2]) if row and row[2] is not None else None


def _finishes(conn, race_id: str) -> Dict[int, int]:
    rows = conn.execute(
        text(
            """
            SELECT horse_no, finish_order_num
            FROM runners
            WHERE race_id = :race_id AND finish_order_num IS NOT NULL
            """
        ),
        {"race_id": race_id},
    ).fetchall()
    out = {}
    for horse_no, finish in rows:
        try:
            out[int(horse_no)] = int(finish)
        except (TypeError, ValueError):
            continue
    return out


def _post_time(conn, race_id: str) -> Optional[datetime]:
    try:
        row = conn.execute(
            text("SELECT post_time, race_time FROM upcoming_races WHERE race_id = :r"),
            {"r": race_id},
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    raw = row[0] or row[1]
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=HK_TZ)
    text_v = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(text_v, fmt)
            break
        except ValueError:
            parsed = None
    if parsed is None:
        return None
    if parsed.year < 2000 and len(race_id) >= 8:
        day = datetime.strptime(race_id[:8], "%Y%m%d")
        parsed = parsed.replace(year=day.year, month=day.month, day=day.day)
    return parsed.replace(tzinfo=HK_TZ)


def _minutes_to_post(conn, race_id: str, sell_status: str) -> Optional[float]:
    if str(sell_status).upper() in {"STOP_SELL", "PAYOUT", "REFUND"}:
        return 0.0
    post = _post_time(conn, race_id)
    if post is None:
        return None
    return (post - datetime.now(HK_TZ)).total_seconds() / 60.0


def _qin_map(raw: Mapping[str, Any]) -> Dict[Tuple[int, int], float]:
    out = {}
    for key, odds in (raw or {}).items():
        pair = _pair(key)
        if pair and odds:
            a, b = sorted(pair)
            out[(a, b)] = float(odds)
    return out


def _fct_map(raw: Mapping[str, Any]) -> Dict[Tuple[int, int], float]:
    out = {}
    for key, odds in (raw or {}).items():
        pair = _pair(key)
        if pair and odds:
            out[pair] = float(odds)
    return out


def _history_from_rows(rows: List[Mapping[str, Any]]) -> Dict[int, List[float]]:
    history: Dict[int, List[float]] = {}
    for row in rows:
        for horse in row.get("horses") or []:
            try:
                no = int(horse.get("no"))
                odds = float(horse.get("win_odds"))
            except (TypeError, ValueError):
                continue
            if odds <= 1.0:
                continue
            history.setdefault(no, []).append(odds)
    return history


def _save_snapshot(conn, race_id: str, sell_status: str, payload: Mapping[str, Any]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO index_sel_snapshots (race_id, captured_at, sell_status, payload_json)
            VALUES (:race_id, :captured_at, :sell_status, :payload)
            """
        ),
        {
            "race_id": race_id,
            "captured_at": datetime.now(HK_TZ).isoformat(),
            "sell_status": sell_status,
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )
    ids = [
        int(row[0])
        for row in conn.execute(
            text(
                """
                SELECT id FROM index_sel_snapshots
                WHERE race_id = :race_id
                ORDER BY id DESC
                """
            ),
            {"race_id": race_id},
        ).fetchall()
    ]
    for old_id in ids[30:]:
        conn.execute(
            text("DELETE FROM index_sel_snapshots WHERE id = :id"),
            {"id": old_id},
        )


def _score_race(conn, race_id: str, snapshots: List[Mapping[str, Any]], finishes: Mapping[int, int]) -> None:
    if not finishes or not snapshots:
        return
    chosen = None
    for snap in reversed(snapshots):
        if str(snap.get("sell_status") or "").upper() not in {"PAYOUT", "REFUND"}:
            chosen = snap
            break
    source = "pre_close"
    if chosen is None:
        chosen = snapshots[0]
        source = "final_odds"
    picks = (chosen.get("picks") or {})
    for strategy_id, _label, _note in STRATEGY_SPECS:
        nums = [int(n) for n in picks.get(strategy_id) or []]
        if not nums:
            continue
        existing = conn.execute(
            text(
                """
                SELECT source FROM index_sel_scores
                WHERE race_id = :race_id AND strategy_id = :strategy_id
                """
            ),
            {"race_id": race_id, "strategy_id": strategy_id},
        ).fetchone()
        if existing and not (existing[0] == "final_odds" and source == "pre_close"):
            continue
        placed = placed_count(nums, finishes)
        conn.execute(
            text(
                """
                DELETE FROM index_sel_scores
                WHERE race_id = :race_id AND strategy_id = :strategy_id
                """
            ),
            {"race_id": race_id, "strategy_id": strategy_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO index_sel_scores
                (race_id, strategy_id, picks_json, placed_n, pick_n, source)
                VALUES (:race_id, :strategy_id, :picks, :placed_n, :pick_n, :source)
                """
            ),
            {
                "race_id": race_id,
                "strategy_id": strategy_id,
                "picks": json.dumps(nums),
                "placed_n": placed,
                "pick_n": len(nums),
                "source": source,
            },
        )


def _latest_captured(conn, race_id: str) -> Optional[datetime]:
    row = conn.execute(
        text(
            """
            SELECT captured_at FROM index_sel_snapshots
            WHERE race_id = :race_id
            ORDER BY id DESC LIMIT 1
            """
        ),
        {"race_id": race_id},
    ).fetchone()
    if not row or not row[0]:
        return None
    raw = row[0]
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=HK_TZ)
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=HK_TZ)


def refresh_live(*, max_races: int = 12, force: bool = False) -> Dict[str, Any]:
    """拉马会当前会议各场赔率。25 秒内重复调用只读库。"""
    ensure_schema()
    engine = _engine()
    summary = {"races": 0, "fetched": 0, "meeting_date": "", "venue": ""}
    try:
        with httpx.Client(timeout=25.0) as client:
            probe = fetch_race_pools(1, client=client)
            meeting_date = str(probe.get("meeting_date") or "")
            if not meeting_date:
                return summary
            fetched: List[Dict[str, Any]] = [probe]
            for race_no in range(2, max_races + 1):
                parsed = fetch_race_pools(race_no, client=client)
                if not parsed.get("horses"):
                    break
                fetched.append(parsed)
        with engine.begin() as conn:
            venue = _venue_for_date(conn, meeting_date)
            summary["meeting_date"] = meeting_date
            summary["venue"] = venue
            race_ids: List[str] = []
            for parsed in fetched:
                race_no = int(parsed.get("race_no") or 0)
                race_id = f"{meeting_date}{venue}{race_no:02d}"
                race_ids.append(race_id)
                latest = _latest_captured(conn, race_id)
                fresh = (
                    latest is not None
                    and (datetime.now(HK_TZ) - latest).total_seconds() < STALE_SECONDS
                    and not force
                )
                if fresh:
                    continue
                _attach_model(conn, race_id, parsed["horses"])
                prev_rows = conn.execute(
                    text(
                        """
                        SELECT payload_json, sell_status FROM index_sel_snapshots
                        WHERE race_id = :race_id
                        ORDER BY id DESC LIMIT 8
                        """
                    ),
                    {"race_id": race_id},
                ).fetchall()
                prev_payloads = []
                for payload_json, sell_status in reversed(prev_rows):
                    try:
                        body = json.loads(payload_json)
                    except json.JSONDecodeError:
                        continue
                    body["sell_status"] = sell_status
                    prev_payloads.append(body)
                prev_horses = prev_payloads[-1].get("horses") if prev_payloads else None
                history = _history_from_rows(prev_payloads)
                minutes = _minutes_to_post(conn, race_id, str(parsed.get("sell_status") or ""))
                picks = all_picks(
                    parsed["horses"],
                    qin_odds=_qin_map(parsed.get("qin") or {}),
                    fct_odds=_fct_map(parsed.get("fct") or {}),
                    prev_horses=prev_horses,
                    odds_history=history,
                    minutes_to_post=minutes,
                )
                payload = {
                    "horses": parsed["horses"],
                    "qin": parsed.get("qin") or {},
                    "fct": parsed.get("fct") or {},
                    "picks": picks,
                    "minutes_to_post": minutes,
                }
                _save_snapshot(conn, race_id, str(parsed.get("sell_status") or ""), payload)
                summary["fetched"] += 1
            summary["races"] = len(race_ids)
            for race_id in race_ids:
                snaps = []
                rows = conn.execute(
                    text(
                        """
                        SELECT payload_json, sell_status FROM index_sel_snapshots
                        WHERE race_id = :race_id ORDER BY id ASC
                        """
                    ),
                    {"race_id": race_id},
                ).fetchall()
                for payload_json, sell_status in rows:
                    try:
                        body = json.loads(payload_json)
                    except json.JSONDecodeError:
                        continue
                    body["sell_status"] = sell_status
                    snaps.append(body)
                _score_race(conn, race_id, snaps, _finishes(conn, race_id))
        return summary
    finally:
        engine.dispose()


def _rates(conn) -> Dict[str, Dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT strategy_id,
                   SUM(placed_n) AS placed_n,
                   SUM(pick_n) AS pick_n,
                   COUNT(*) AS races
            FROM index_sel_scores
            GROUP BY strategy_id
            """
        )
    ).fetchall()
    out = {}
    for strategy_id, placed_n, pick_n, races in rows:
        placed = int(placed_n or 0)
        picks = int(pick_n or 0)
        out[str(strategy_id)] = {
            "placed": placed,
            "picks": picks,
            "races": int(races or 0),
            "rate": hit_rate(placed, picks),
        }
    return out


def load_board() -> Dict[str, Any]:
    ensure_schema()
    engine = _engine()
    try:
        with engine.connect() as conn:
            race_rows = conn.execute(
                text(
                    """
                    SELECT race_id, MAX(id) AS max_id
                    FROM index_sel_snapshots
                    GROUP BY race_id
                    ORDER BY race_id
                    """
                )
            ).fetchall()
            races = []
            meeting_date = ""
            venue = ""
            for race_id, max_id in race_rows:
                row = conn.execute(
                    text(
                        """
                        SELECT payload_json, sell_status, captured_at
                        FROM index_sel_snapshots WHERE id = :id
                        """
                    ),
                    {"id": max_id},
                ).fetchone()
                if not row:
                    continue
                try:
                    payload = json.loads(row[0])
                except json.JSONDecodeError:
                    continue
                rid = str(race_id)
                if len(rid) >= 10:
                    meeting_date = rid[:8]
                    venue = rid[8:10]
                finishes = _finishes(conn, rid)
                strategies = []
                for strategy_id, label, note in STRATEGY_SPECS:
                    nums = [int(n) for n in (payload.get("picks") or {}).get(strategy_id) or []]
                    strategies.append(
                        {
                            "id": strategy_id,
                            "label": label,
                            "note": note,
                            "picks": nums,
                            "marks": finish_marks(nums, finishes),
                            "placed": placed_count(nums, finishes) if finishes else None,
                        }
                    )
                race_no = int(rid[-2:]) if rid[-2:].isdigit() else None
                races.append(
                    {
                        "race_id": rid,
                        "race_no": race_no,
                        "sell_status": row[1],
                        "captured_at": str(row[2] or ""),
                        "finished": bool(finishes),
                        "strategies": strategies,
                    }
                )
            return {
                "meeting_date": meeting_date,
                "venue": venue,
                "races": races,
                "rates": _rates(conn),
            }
    finally:
        engine.dispose()
