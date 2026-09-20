"""
分段時間／走位正規化落庫。

問題背景：
  schema 已有 race_sectionals、runner_sections，但 ETL／jjjc 賽果同步
  從未寫入；步速／速度因子只從 runners.raw_json 即時 JSON 解析，
  營運在 DB 一條一條對時找不到「分段／名次／步速原料」。

本模組：
  1) 把 J18 `sections.stage_N` 與 HKJC `running_position`（如「7 7 1」）
     正規化成可查表列
  2) upsert 進 runner_sections／race_sectionals
  3) 提供覆蓋度稽核與 raw_json 回填

Join 鍵：runner_id + stage_no；race_id + stage_no。
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import create_engine, text

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE, resolve_database_url

StageRow = Dict[str, Any]


def _safe_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        s = str(v).strip().replace(",", "")
        if s in ("-", "N", "None", "nan", "NaN"):
            return None
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _safe_time_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("-", "None", "nan"):
        return None
    return s[:20]


def parse_running_position(raw: Any) -> List[int]:
    """
    HKJC／jjjc 走位字串 → 各段名次。
    例：「7 7 1」「7-7-1」「7,7,1」→ [7, 7, 1]
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        out: List[int] = []
        for x in raw:
            n = _safe_int(x)
            if n is not None:
                out.append(n)
        return out
    s = str(raw).strip()
    if not s or s in ("-", "---"):
        return []
    parts = re.split(r"[\s\-–,，/|]+", s)
    out = []
    for p in parts:
        n = _safe_int(p)
        if n is not None:
            out.append(n)
    return out


def stages_from_j18_sections(sections: Any) -> List[StageRow]:
    """J18 horse.raw_json['sections']['stage_N'] → stage rows。"""
    if not isinstance(sections, dict):
        return []
    rows: List[StageRow] = []
    for key, stage in sections.items():
        if not isinstance(stage, dict):
            continue
        m = re.match(r"stage[_\s]?(\d+)$", str(key).strip(), re.I)
        stage_no = _safe_int(m.group(1)) if m else _safe_int(stage.get("stage_no") or stage.get("stage"))
        if stage_no is None:
            continue
        pos = stage.get("position")
        if pos is None:
            pos = stage.get("pos")
        rows.append(
            {
                "stage_no": int(stage_no),
                "position_raw": str(pos).strip() if pos is not None and str(pos).strip() not in ("", "-", "None") else None,
                "distance_behind_raw": _safe_time_str(
                    stage.get("distance_behind") or stage.get("lbw") or stage.get("lengths")
                ),
                "sectional_time": _safe_time_str(stage.get("sectional_time") or stage.get("time")),
                "split_1": _safe_time_str(stage.get("split_1") or stage.get("split1")),
                "split_2": _safe_time_str(stage.get("split_2") or stage.get("split2")),
                "raw_json": stage,
                "source": "j18_sections",
            }
        )
    rows.sort(key=lambda r: r["stage_no"])
    return rows


def stages_from_running_position(raw: Any, *, source: str = "running_position") -> List[StageRow]:
    positions = parse_running_position(raw)
    return [
        {
            "stage_no": i + 1,
            "position_raw": str(p),
            "distance_behind_raw": None,
            "sectional_time": None,
            "split_1": None,
            "split_2": None,
            "raw_json": {"running_position": raw, "parsed_position": p},
            "source": source,
        }
        for i, p in enumerate(positions)
    ]


def stages_from_runner_payload(runner: Dict[str, Any]) -> List[StageRow]:
    """
    優先 J18 sections；否則 running_position／沿途走位字串。
    若兩者都有：sections 有時間優先；若 sections 缺位置而 running_position 有，合併位置。
    """
    sections = runner.get("sections")
    if sections is None and isinstance(runner.get("raw_json"), dict):
        sections = runner["raw_json"].get("sections")
    j18 = stages_from_j18_sections(sections)
    rp_raw = (
        runner.get("running_position")
        or runner.get("runningPosition")
        or runner.get("run_position")
    )
    rp = stages_from_running_position(rp_raw) if rp_raw else []

    if j18 and rp:
        by_no = {r["stage_no"]: dict(r) for r in j18}
        for r in rp:
            cur = by_no.get(r["stage_no"])
            if cur is None:
                by_no[r["stage_no"]] = r
            elif not cur.get("position_raw") and r.get("position_raw"):
                cur["position_raw"] = r["position_raw"]
                cur["source"] = "j18_sections+running_position"
        return [by_no[k] for k in sorted(by_no)]
    if j18:
        return j18
    return rp


def stages_from_race_times(times: Any) -> List[StageRow]:
    """
    賽事層分段時間（J18 detail.times 或類似 list／dict）。
    接受：
      - ["12.3", "23.1", ...]
      - [{"stage_no":1,"sectional_time":"12.3"}, ...]
      - {"stage_1": {"sectional_time": "12.3"}, ...}
    """
    if times is None:
        return []
    if isinstance(times, dict):
        return stages_from_j18_sections(times)
    if not isinstance(times, (list, tuple)):
        return []
    rows: List[StageRow] = []
    for i, item in enumerate(times):
        if isinstance(item, dict):
            stage_no = _safe_int(item.get("stage_no") or item.get("stage") or (i + 1))
            rows.append(
                {
                    "stage_no": int(stage_no or (i + 1)),
                    "position_raw": None,
                    "distance_behind_raw": None,
                    "sectional_time": _safe_time_str(
                        item.get("sectional_time") or item.get("time") or item.get("split")
                    ),
                    "split_1": _safe_time_str(item.get("split_1")),
                    "split_2": _safe_time_str(item.get("split_2")),
                    "raw_json": item,
                    "source": "race_times",
                }
            )
        else:
            t = _safe_time_str(item)
            if t is None:
                continue
            rows.append(
                {
                    "stage_no": i + 1,
                    "position_raw": None,
                    "distance_behind_raw": None,
                    "sectional_time": t,
                    "split_1": None,
                    "split_2": None,
                    "raw_json": {"time": item},
                    "source": "race_times",
                }
            )
    return rows


def _dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False)


def upsert_runner_sections(conn, runner_id: str, stages: Sequence[StageRow]) -> int:
    """寫入／覆寫一匹馬的分段走位。回傳寫入列數。"""
    if not runner_id or not stages:
        return 0
    n = 0
    for st in stages:
        stage_no = _safe_int(st.get("stage_no"))
        if stage_no is None:
            continue
        raw = dict(st.get("raw_json") or {})
        raw.setdefault("source", st.get("source"))
        conn.execute(
            text(
                """
                INSERT INTO runner_sections (
                  runner_id, stage_no, position_raw, distance_behind_raw,
                  sectional_time, split_1, split_2, raw_json
                ) VALUES (
                  :runner_id, :stage_no, :position_raw, :distance_behind_raw,
                  :sectional_time, :split_1, :split_2, :raw_json
                )
                ON CONFLICT (runner_id, stage_no) DO UPDATE SET
                  position_raw = EXCLUDED.position_raw,
                  distance_behind_raw = COALESCE(EXCLUDED.distance_behind_raw, runner_sections.distance_behind_raw),
                  sectional_time = COALESCE(EXCLUDED.sectional_time, runner_sections.sectional_time),
                  split_1 = COALESCE(EXCLUDED.split_1, runner_sections.split_1),
                  split_2 = COALESCE(EXCLUDED.split_2, runner_sections.split_2),
                  raw_json = EXCLUDED.raw_json
                """
            ),
            {
                "runner_id": runner_id,
                "stage_no": int(stage_no),
                "position_raw": st.get("position_raw"),
                "distance_behind_raw": st.get("distance_behind_raw"),
                "sectional_time": st.get("sectional_time"),
                "split_1": st.get("split_1"),
                "split_2": st.get("split_2"),
                "raw_json": _dumps(raw),
            },
        )
        n += 1
    return n


def upsert_race_sectionals(conn, race_id: str, stages: Sequence[StageRow]) -> int:
    if not race_id or not stages:
        return 0
    n = 0
    for st in stages:
        stage_no = _safe_int(st.get("stage_no"))
        if stage_no is None:
            continue
        raw = dict(st.get("raw_json") or {})
        raw.setdefault("source", st.get("source"))
        conn.execute(
            text(
                """
                INSERT INTO race_sectionals (
                  race_id, stage_no, sectional_time, split_1, split_2, raw_json
                ) VALUES (
                  :race_id, :stage_no, :sectional_time, :split_1, :split_2, :raw_json
                )
                ON CONFLICT (race_id, stage_no) DO UPDATE SET
                  sectional_time = COALESCE(EXCLUDED.sectional_time, race_sectionals.sectional_time),
                  split_1 = COALESCE(EXCLUDED.split_1, race_sectionals.split_1),
                  split_2 = COALESCE(EXCLUDED.split_2, race_sectionals.split_2),
                  raw_json = EXCLUDED.raw_json
                """
            ),
            {
                "race_id": race_id,
                "stage_no": int(stage_no),
                "sectional_time": st.get("sectional_time"),
                "split_1": st.get("split_1"),
                "split_2": st.get("split_2"),
                "raw_json": _dumps(raw),
            },
        )
        n += 1
    return n


async def upsert_runner_sections_asyncpg(conn, runner_id: str, stages: Sequence[StageRow]) -> int:
    if not runner_id or not stages:
        return 0
    n = 0
    for st in stages:
        stage_no = _safe_int(st.get("stage_no"))
        if stage_no is None:
            continue
        raw = dict(st.get("raw_json") or {})
        raw.setdefault("source", st.get("source"))
        await conn.execute(
            """
            INSERT INTO runner_sections (
              runner_id, stage_no, position_raw, distance_behind_raw,
              sectional_time, split_1, split_2, raw_json
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
            ON CONFLICT (runner_id, stage_no) DO UPDATE SET
              position_raw = EXCLUDED.position_raw,
              distance_behind_raw = COALESCE(EXCLUDED.distance_behind_raw, runner_sections.distance_behind_raw),
              sectional_time = COALESCE(EXCLUDED.sectional_time, runner_sections.sectional_time),
              split_1 = COALESCE(EXCLUDED.split_1, runner_sections.split_1),
              split_2 = COALESCE(EXCLUDED.split_2, runner_sections.split_2),
              raw_json = EXCLUDED.raw_json
            """,
            runner_id,
            int(stage_no),
            st.get("position_raw"),
            st.get("distance_behind_raw"),
            st.get("sectional_time"),
            st.get("split_1"),
            st.get("split_2"),
            _dumps(raw),
        )
        n += 1
    return n


async def upsert_race_sectionals_asyncpg(conn, race_id: str, stages: Sequence[StageRow]) -> int:
    if not race_id or not stages:
        return 0
    n = 0
    for st in stages:
        stage_no = _safe_int(st.get("stage_no"))
        if stage_no is None:
            continue
        raw = dict(st.get("raw_json") or {})
        raw.setdefault("source", st.get("source"))
        await conn.execute(
            """
            INSERT INTO race_sectionals (
              race_id, stage_no, sectional_time, split_1, split_2, raw_json
            ) VALUES ($1,$2,$3,$4,$5,$6::jsonb)
            ON CONFLICT (race_id, stage_no) DO UPDATE SET
              sectional_time = COALESCE(EXCLUDED.sectional_time, race_sectionals.sectional_time),
              split_1 = COALESCE(EXCLUDED.split_1, race_sectionals.split_1),
              split_2 = COALESCE(EXCLUDED.split_2, race_sectionals.split_2),
              raw_json = EXCLUDED.raw_json
            """,
            race_id,
            int(stage_no),
            st.get("sectional_time"),
            st.get("split_1"),
            st.get("split_2"),
            _dumps(raw),
        )
        n += 1
    return n


def load_runner_payload(raw_json: Any) -> Dict[str, Any]:
    if raw_json is None:
        return {}
    if isinstance(raw_json, dict):
        return raw_json
    try:
        data = json.loads(raw_json)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def early_stage_from_rows(stages: Sequence[StageRow]) -> Tuple[Optional[int], Optional[float]]:
    """回傳 (早段名次, 首段時間秒)。"""
    if not stages:
        return None, None
    ordered = sorted(stages, key=lambda r: int(r.get("stage_no") or 99))
    early_pos = None
    early_sec = None
    for st in ordered:
        if early_pos is None:
            early_pos = _safe_int(st.get("position_raw"))
        if early_sec is None and st.get("sectional_time"):
            try:
                early_sec = float(str(st["sectional_time"]).strip())
            except (TypeError, ValueError):
                early_sec = None
        if early_pos is not None:
            break
    if early_sec is None:
        for st in ordered:
            if st.get("sectional_time"):
                try:
                    early_sec = float(str(st["sectional_time"]).strip())
                    break
                except (TypeError, ValueError):
                    continue
    return early_pos, early_sec


def coverage_for_prefix(engine, race_id_prefix: str) -> Dict[str, Any]:
    """
    某日某場地（race_id LIKE prefix%）的分段覆蓋度。
    RESULTS「已拿到」只看 finish_order；此函式另報分段是否可算步速。
    """
    prefix = str(race_id_prefix or "").strip()
    with engine.connect() as conn:
        # SQLite 無 FILTER；兩邊都用 CASE 以求相容
        runners = conn.execute(
            text(
                """
                SELECT COUNT(*) AS n,
                       SUM(CASE WHEN finish_order_num IS NOT NULL THEN 1 ELSE 0 END) AS with_finish
                FROM runners
                WHERE race_id LIKE :p || '%'
                """
            ),
            {"p": prefix},
        ).mappings().first()
        sec = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT rs.runner_id) AS with_sections,
                       COUNT(*) AS section_rows
                FROM runner_sections rs
                JOIN runners ru ON ru.runner_id = rs.runner_id
                WHERE ru.race_id LIKE :p || '%'
                """
            ),
            {"p": prefix},
        ).mappings().first()
    n = int((runners or {}).get("n") or 0)
    with_finish = int((runners or {}).get("with_finish") or 0)
    with_sections = int((sec or {}).get("with_sections") or 0)
    section_rows = int((sec or {}).get("section_rows") or 0)
    denom = with_finish or n or 1
    return {
        "prefix": prefix,
        "runners": n,
        "with_finish": with_finish,
        "with_sections": with_sections,
        "section_rows": section_rows,
        "section_coverage": round(with_sections / denom, 3) if denom else 0.0,
        "results_ready_rule": "finish_order_num IS NOT NULL（結算不要求分段）",
        "pace_ready_rule": "runner_sections 有至少一段 position_raw（步速／跑法）",
    }


def audit_global(engine) -> Dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM runners) AS runners,
                  (SELECT COUNT(*) FROM runners WHERE finish_order_num IS NOT NULL) AS with_finish,
                  (SELECT COUNT(*) FROM runner_sections) AS section_rows,
                  (SELECT COUNT(DISTINCT runner_id) FROM runner_sections) AS runners_with_sections,
                  (SELECT COUNT(*) FROM race_sectionals) AS race_section_rows,
                  (SELECT COUNT(*) FROM factor_scores WHERE factor_type='PACE') AS pace_scores,
                  (SELECT COUNT(*) FROM factor_scores WHERE factor_type='HORSE') AS horse_scores
                """
            )
        ).mappings().first()
    return dict(row or {})


def backfill_from_runners(
    engine,
    *,
    limit: Optional[int] = None,
    race_id_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """從既有 runners.raw_json／running_position 回填 runner_sections。"""
    params: Dict[str, Any] = {}
    where = ["1=1"]
    if race_id_prefix:
        where.append("race_id LIKE :p || '%'")
        params["p"] = race_id_prefix
    lim = ""
    if limit is not None:
        lim = "LIMIT :lim"
        params["lim"] = int(limit)
    q = f"""
        SELECT runner_id, race_id, raw_json
        FROM runners
        WHERE {' AND '.join(where)}
        ORDER BY race_id DESC, runner_id
        {lim}
    """
    runner_n = 0
    section_n = 0
    race_sec_n = 0
    skipped = 0
    with engine.begin() as conn:
        rows = conn.execute(text(q), params).mappings().all()
        race_seen: Dict[str, bool] = {}
        for row in rows:
            payload = load_runner_payload(row["raw_json"])
            stages = stages_from_runner_payload(payload)
            if not stages:
                skipped += 1
                continue
            section_n += upsert_runner_sections(conn, str(row["runner_id"]), stages)
            runner_n += 1
            rid = str(row["race_id"] or "")
            if rid and rid not in race_seen:
                race_seen[rid] = True
                # 嘗試從同場 raw／detail 寫賽事分段（若 runner raw 無 times 則略）
                times = payload.get("times") or payload.get("race_times")
                if times:
                    race_sec_n += upsert_race_sectionals(conn, rid, stages_from_race_times(times))
    return {
        "scanned": len(rows),
        "runners_written": runner_n,
        "section_rows_upserted": section_n,
        "race_section_rows_upserted": race_sec_n,
        "skipped_no_sections": skipped,
    }


def explain_pace_inputs(
    engine,
    horse_name: str,
    *,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """
    列出構成步速分的原料列（可對 DB）：
    early_position、finish_order、positions_gained、首段時間。
    """
    name = str(horse_name or "").strip()
    if not name:
        return []
    q = text(
        """
        SELECT
          ru.runner_id,
          ru.race_id,
          ru.horse_name,
          ru.finish_order_num,
          rs.stage_no,
          rs.position_raw,
          rs.sectional_time,
          ra.distance_m,
          ra.meeting_id
        FROM runners ru
        JOIN runner_sections rs ON rs.runner_id = ru.runner_id
        LEFT JOIN races ra ON ra.race_id = ru.race_id
        WHERE ru.horse_name = :name
          AND ru.finish_order_num IS NOT NULL
        ORDER BY ru.race_id DESC, rs.stage_no ASC
        """
    )
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(q, {"name": name}).mappings().all()]

    by_runner: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = r["runner_id"]
        cur = by_runner.setdefault(
            rid,
            {
                "runner_id": rid,
                "race_id": r["race_id"],
                "horse_name": r["horse_name"],
                "finish_order_num": r["finish_order_num"],
                "distance_m": r.get("distance_m"),
                "meeting_id": r.get("meeting_id"),
                "stages": [],
                "early_position": None,
                "early_sectional_sec": None,
                "positions_gained": None,
            },
        )
        cur["stages"].append(
            {
                "stage_no": r["stage_no"],
                "position_raw": r["position_raw"],
                "sectional_time": r["sectional_time"],
            }
        )
        if cur["early_position"] is None:
            cur["early_position"] = _safe_int(r["position_raw"])
        if cur["early_sectional_sec"] is None and r.get("sectional_time"):
            try:
                cur["early_sectional_sec"] = float(str(r["sectional_time"]).strip())
            except (TypeError, ValueError):
                pass

    out = []
    for cur in by_runner.values():
        if cur["early_position"] is not None and cur["finish_order_num"] is not None:
            cur["positions_gained"] = int(cur["early_position"]) - int(cur["finish_order_num"])
        out.append(cur)
    out.sort(key=lambda x: str(x.get("race_id") or ""), reverse=True)
    return out[: max(1, int(limit))]


def _engine():
    if USE_SQLITE:
        url = f"sqlite:///{SQLITE_DB_PATH}"
    else:
        url = resolve_database_url(sqlite_fallback=False)
    return create_engine(url)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="分段走位落庫／回填／稽核")
    p.add_argument("--audit", action="store_true", help="印出全庫覆蓋度")
    p.add_argument("--backfill", action="store_true", help="從 runners.raw_json 回填")
    p.add_argument("--prefix", help="race_id 前綴，如 20260906ST")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--explain-pace", dest="explain_pace", help="馬名：列出步速原料列")
    args = p.parse_args(argv)

    eng = _engine()
    try:
        if args.audit:
            print(json.dumps(audit_global(eng), ensure_ascii=False, indent=2))
            if args.prefix:
                print(json.dumps(coverage_for_prefix(eng, args.prefix), ensure_ascii=False, indent=2))
        if args.backfill:
            out = backfill_from_runners(
                eng, limit=args.limit, race_id_prefix=args.prefix
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
        if args.explain_pace:
            rows = explain_pace_inputs(eng, args.explain_pace, limit=args.limit or 12)
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        if not (args.audit or args.backfill or args.explain_pace):
            p.print_help()
            return 2
    finally:
        eng.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
