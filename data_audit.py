"""
賽日資料齊備／正確性稽核 + 因子原料血緣。

給營運中心／作戰室用：唔使只靠快照同答案，可以直接睇
  - 邊日邊樣唔齊（名次／分段／評述）
  - 分段走位是否同 raw running_position 一致
  - 某匹馬近績／步速分嘅歷史出賽原料列
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import text

from sectionals_store import (
    backfill_from_runners,
    coverage_for_prefix,
    early_stage_from_rows,
    explain_pace_inputs,
    load_runner_payload,
    parse_running_position,
    stages_from_runner_payload,
)
from jjjc_export_common import (
    field_size_issues,
    max_horse_no_for_venue,
    normalize_venue,
    venue_from_race_id,
)


def _prefix(racing_date: str, course: str) -> str:
    d = str(racing_date or "").replace("-", "")[:8]
    c = str(course or "").strip().upper()
    return f"{d}{c}"


def meeting_inventory(engine, racing_date: str, course: str) -> Dict[str, Any]:
    """
    單日單場地齊備度。
    flags：
      finish_ok / sectionals_ok / running_comment_ok / incident_ok
    """
    prefix = _prefix(racing_date, course)
    # 通配符喺 Python 拼接，避免部分 PG driver 對 `:p || '%'` 綁參異常
    like_prefix = f"{prefix}%"
    cov = coverage_for_prefix(engine, prefix)

    with engine.connect() as conn:
        race_n = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT race_id) FROM runners
                WHERE race_id LIKE :p
                """
            ),
            {"p": like_prefix},
        ).scalar()
        race_n = int(race_n or 0)

        # 評述：有 finish 的 runner 為母體。
        # entity_id 同時認 runner_id 與同步回退鍵 race_id_horse_no
        #（與 data_backlog.measure_comment_coverage 對齊；否則作戰室會假報「評述不足」）。
        comment = conn.execute(
            text(
                """
                SELECT
                  COUNT(
                    DISTINCT CASE WHEN EXISTS (
                      SELECT 1 FROM text_reports tr
                      WHERE tr.entity_type = 'runner'
                        AND tr.report_type IN ('running_comment', 'corunning')
                        AND LENGTH(TRIM(COALESCE(tr.report_text, ''))) > 0
                        AND (
                          tr.entity_id = ru.runner_id
                          OR tr.entity_id = (ru.race_id || '_' || CAST(ru.horse_no AS TEXT))
                        )
                    ) THEN ru.race_id || ':' || CAST(ru.horse_no AS TEXT) END
                  ) AS running_n,
                  COUNT(
                    DISTINCT CASE WHEN EXISTS (
                      SELECT 1 FROM text_reports tr
                      WHERE tr.entity_type = 'runner'
                        AND tr.report_type IN ('incident_report', 'racereport')
                        AND LENGTH(TRIM(COALESCE(tr.report_text, ''))) > 0
                        AND (
                          tr.entity_id = ru.runner_id
                          OR tr.entity_id = (ru.race_id || '_' || CAST(ru.horse_no AS TEXT))
                        )
                    ) THEN ru.race_id || ':' || CAST(ru.horse_no AS TEXT) END
                  ) AS incident_n,
                  COUNT(DISTINCT ru.race_id || ':' || CAST(ru.horse_no AS TEXT)) AS finish_n
                FROM runners ru
                WHERE ru.race_id LIKE :p
                  AND ru.finish_order_num IS NOT NULL
                """
            ),
            {"p": like_prefix},
        ).mappings().first()

        missing_sec = conn.execute(
            text(
                """
                SELECT ru.race_id, ru.horse_no, ru.horse_name, ru.finish_order_num, ru.runner_id
                FROM runners ru
                LEFT JOIN runner_sections rs ON rs.runner_id = ru.runner_id
                WHERE ru.race_id LIKE :p
                  AND ru.finish_order_num IS NOT NULL
                  AND rs.id IS NULL
                ORDER BY ru.race_id, ru.horse_no
                LIMIT 40
                """
            ),
            {"p": like_prefix},
        ).mappings().all()

        # 場額幽靈：HV horse_no>12／ST>14（例如 ST Glenealy 誤寫入 HV race_id）
        venue = normalize_venue(course) or ""
        cap = max_horse_no_for_venue(venue)
        field_ghosts: List[Dict[str, Any]] = []
        if cap is not None:
            field_ghosts = [
                dict(r)
                for r in conn.execute(
                    text(
                        """
                        SELECT race_id, horse_no, horse_name, finish_order_num, runner_id
                        FROM runners
                        WHERE race_id LIKE :p
                          AND horse_no > :cap
                        ORDER BY race_id, horse_no
                        LIMIT 40
                        """
                    ),
                    {"p": like_prefix, "cap": int(cap)},
                ).mappings().all()
            ]

    finish_n = int((comment or {}).get("finish_n") or cov.get("with_finish") or 0)
    running_n = int((comment or {}).get("running_n") or 0)
    incident_n = int((comment or {}).get("incident_n") or 0)
    with_sec = int(cov.get("with_sections") or 0)
    with_times = int(cov.get("with_sectional_times") or 0)

    finish_ok = finish_n > 0 and race_n > 0
    # 半空賽果：已完賽日但只入咗少場（常見 export 先有 1 場、未 fetch）
    # 注意：唔改 finish_ok（分段 late-backfill／結算仍要「有名次」母體）
    thin_results = False
    try:
        from datetime import date as _date

        rd = _date.fromisoformat(str(racing_date)[:10])
        if rd < _date.today() and race_n > 0 and race_n < 5:
            thin_results = True
    except Exception:
        if race_n > 0 and race_n < 5 and finish_n > 0:
            thin_results = True
    # 分段：有名次嘅馬 ≥80% 有走位先當齊（同 backlog 門檻風格）
    sec_cov = (with_sec / finish_n) if finish_n else 0.0
    time_cov = (with_times / finish_n) if finish_n else 0.0
    sectionals_ok = finish_n > 0 and sec_cov >= 0.8
    times_ok = finish_n > 0 and time_cov >= 0.8
    run_cov = (running_n / finish_n) if finish_n else 0.0
    inc_cov = (incident_n / finish_n) if finish_n else 0.0

    gaps: List[str] = []
    if field_ghosts:
        gaps.append(
            f"場額幽靈 {len(field_ghosts)} 匹（{venue} 上限 {cap}；疑 ST 賽果誤入 HV）"
            if venue == "HV"
            else f"場額幽靈 {len(field_ghosts)} 匹（{venue} 上限 {cap}）"
        )
    if not finish_ok:
        gaps.append("無名次（需重同步 RESULTS）")
    elif thin_results:
        gaps.append(f"賽果場次不足 {race_n}（需重同步 RESULTS）")
    elif not sectionals_ok:
        gaps.append(f"分段走位不足 {with_sec}/{finish_n}（{sec_cov:.0%}）")
    elif not times_ok:
        gaps.append(
            f"有走位但缺分段秒數 {with_times}/{finish_n}（{time_cov:.0%}）—"
            "請 RESULTS「同步 R2 分段」（空 export 會自動 phases/post/run 補采）；"
            "唔好只靠賽果 running_position 回填"
        )
    if finish_ok and run_cov < 0.8:
        gaps.append(f"沿途評述不足 {running_n}/{finish_n}")
    if finish_ok and inc_cov < 0.8:
        gaps.append(f"事故評述不足 {incident_n}/{finish_n}")

    return {
        "racing_date": str(racing_date)[:10],
        "course": str(course).upper(),
        "prefix": prefix,
        "race_n": race_n,
        "finish_n": finish_n,
        "with_sections": with_sec,
        "with_sectional_times": with_times,
        "section_rows": int(cov.get("section_rows") or 0),
        "section_coverage": round(sec_cov, 3),
        "sectional_time_coverage": round(time_cov, 3),
        "running_comment_n": running_n,
        "running_comment_coverage": round(run_cov, 3),
        "incident_n": incident_n,
        "incident_coverage": round(inc_cov, 3),
        "finish_ok": finish_ok,
        "thin_results": thin_results,
        "sectionals_ok": sectionals_ok,
        "sectional_times_ok": times_ok,
        "running_comment_ok": run_cov >= 0.8 if finish_n else False,
        "incident_ok": inc_cov >= 0.8 if finish_n else False,
        "field_cap": cap,
        "field_ghost_n": len(field_ghosts),
        "field_ghost_sample": field_ghosts,
        "gaps": gaps,
        "status": "ok" if not gaps else ("partial" if finish_ok and not field_ghosts else ("contaminated" if field_ghosts else "missing")),
        "missing_sectionals_sample": [dict(r) for r in missing_sec],
    }


def window_inventory(
    engine, meetings: Sequence[Tuple[str, str]]
) -> pd.DataFrame:
    rows = []
    for d, c in meetings:
        try:
            inv = meeting_inventory(engine, d, c)
            rows.append(
                {
                    "賽日": inv["racing_date"],
                    "場地": inv["course"],
                    "場數": inv["race_n"],
                    "有名次": inv["finish_n"],
                    "有分段": inv["with_sections"],
                    "分段覆蓋": inv["section_coverage"],
                    "沿途評述覆蓋": inv["running_comment_coverage"],
                    "事故評述覆蓋": inv["incident_coverage"],
                    "狀態": inv["status"],
                    "缺口": "；".join(inv["gaps"]) if inv["gaps"] else "",
                }
            )
        except Exception as e:
            rows.append(
                {
                    "賽日": str(d)[:10],
                    "場地": str(c).upper(),
                    "場數": 0,
                    "有名次": 0,
                    "有分段": 0,
                    "分段覆蓋": 0.0,
                    "沿途評述覆蓋": 0.0,
                    "事故評述覆蓋": 0.0,
                    "狀態": "error",
                    "缺口": str(e)[:120],
                }
            )
    return pd.DataFrame(rows)


def sectional_correctness_sample(
    engine, racing_date: str, course: str, *, limit: int = 30
) -> pd.DataFrame:
    """
    對照 runner_sections vs raw_json.running_position／sections。
    mismatch=True 代表落庫同來源字串解析結果唔一致。
    """
    prefix = _prefix(racing_date, course)
    q = text(
        """
        SELECT ru.runner_id, ru.race_id, ru.horse_no, ru.horse_name,
               ru.finish_order_num, ru.raw_json
        FROM runners ru
        WHERE ru.race_id LIKE :p || '%'
          AND ru.finish_order_num IS NOT NULL
        ORDER BY ru.race_id, ru.horse_no
        LIMIT :lim
        """
    )
    with engine.connect() as conn:
        runners = [dict(r) for r in conn.execute(q, {"p": prefix, "lim": int(limit)}).mappings().all()]
        sec_rows = conn.execute(
            text(
                """
                SELECT rs.runner_id, rs.stage_no, rs.position_raw
                FROM runner_sections rs
                JOIN runners ru ON ru.runner_id = rs.runner_id
                WHERE ru.race_id LIKE :p || '%'
                ORDER BY rs.runner_id, rs.stage_no
                """
            ),
            {"p": prefix},
        ).mappings().all()

    by_runner: Dict[str, List[Dict[str, Any]]] = {}
    for r in sec_rows:
        by_runner.setdefault(str(r["runner_id"]), []).append(dict(r))

    out = []
    for ru in runners:
        rid = str(ru["runner_id"])
        payload = load_runner_payload(ru.get("raw_json"))
        expected = stages_from_runner_payload(payload)
        exp_pos = [str(s.get("position_raw")) for s in expected if s.get("position_raw")]
        stored = by_runner.get(rid) or []
        got_pos = [str(s.get("position_raw")) for s in stored if s.get("position_raw")]
        early_exp, _ = early_stage_from_rows(expected)
        early_got, _ = early_stage_from_rows(
            [
                {
                    "stage_no": s.get("stage_no"),
                    "position_raw": s.get("position_raw"),
                    "sectional_time": None,
                }
                for s in stored
            ]
        )
        rp = payload.get("running_position") or payload.get("runningPosition")
        mismatch = bool(exp_pos) and got_pos != exp_pos
        missing = bool(exp_pos) and not got_pos
        out.append(
            {
                "race_id": ru["race_id"],
                "horse_no": ru["horse_no"],
                "horse_name": ru["horse_name"],
                "finish_order_num": ru["finish_order_num"],
                "running_position_raw": rp,
                "expected_positions": "-".join(exp_pos) if exp_pos else "",
                "stored_positions": "-".join(got_pos) if got_pos else "",
                "early_expected": early_exp,
                "early_stored": early_got,
                "missing_in_table": missing,
                "mismatch": mismatch,
                "ok": (not missing) and (not mismatch) and bool(got_pos),
            }
        )
    return pd.DataFrame(out)


def factor_lineage(
    engine,
    horse_name: str,
    *,
    limit: int = 15,
) -> Dict[str, Any]:
    """近績原料（runners 名次）+ 步速原料（runner_sections）+ factor_scores 現況。"""
    name = str(horse_name or "").strip()
    form_rows: List[Dict[str, Any]] = []
    pace_rows = explain_pace_inputs(engine, name, limit=limit)
    scores: List[Dict[str, Any]] = []
    if not name:
        return {"horse_name": name, "form_races": [], "pace_races": [], "factor_scores": []}

    with engine.connect() as conn:
        form_rows = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT
                      ru.runner_id, ru.race_id, ru.horse_name, ru.finish_order_num,
                      ru.final_time, ru.jockey_name, ru.trainer_name,
                      ra.distance_m, ra.class AS race_class, ra.meeting_id
                    FROM runners ru
                    LEFT JOIN races ra ON ra.race_id = ru.race_id
                    WHERE ru.horse_name = :name
                      AND ru.finish_order_num IS NOT NULL
                    ORDER BY ru.race_id DESC
                    LIMIT :lim
                    """
                ),
                {"name": name, "lim": int(limit)},
            ).mappings().all()
        ]
        try:
            scores = [
                dict(r)
                for r in conn.execute(
                    text(
                        """
                        SELECT factor_type, bucket_id, entity_name,
                               actual_runs, adjusted_score, z_score,
                               early_speed_z, running_style, calculated_at
                        FROM factor_scores
                        WHERE entity_name = :name
                          AND factor_type IN ('HORSE', 'PACE', 'SPEED')
                        ORDER BY factor_type, bucket_id
                        """
                    ),
                    {"name": name},
                ).mappings().all()
            ]
        except Exception:
            scores = []

    return {
        "horse_name": name,
        "form_races": form_rows,
        "pace_races": pace_rows,
        "factor_scores": scores,
        "notes": {
            "form": "近績分＝上表名次經衰減＋貝葉斯後寫入 factor_scores(HORSE)",
            "pace": "步速分＝pace_races 嘅 positions_gained 聚合後寫入 factor_scores(PACE)",
            "snapshot": "prediction_snapshots 只係賽前快照答案，唔係計算原料",
        },
    }


def backfill_meeting_sectionals(
    engine, racing_date: str, course: str
) -> Dict[str, Any]:
    """從既有 runners.raw_json 回填該賽日分段。"""
    prefix = _prefix(racing_date, course)
    out = backfill_from_runners(engine, race_id_prefix=prefix)
    out["prefix"] = prefix
    out["inventory"] = meeting_inventory(engine, racing_date, course)
    return out


def resync_results_and_sectionals(
    pipe,
    racing_date: str,
    course: str,
    *,
    also_backfill: bool = True,
) -> Dict[str, Any]:
    """
    重跑賽果同步（會寫 runner_sections）+ R2 分段秒數 + 可選 raw_json 回填保險。
    pipe: MeetingPipeline 實例。

    名次優先：先 skip_sectionals 寫 finish_order，再拉 R2。
    避免 sectionals phases/post/run 過慢／Nginx 超時時，連名次都未提交、作戰室仍掛「無名次」。
    """
    # 1) 只寫賽果名次（短路徑）
    sync_out = pipe.run_action(
        racing_date, course, "sync_jjjc_results", skip_sectionals=True
    )
    # 2) R2 分段（可慢；失敗唔回滾名次）
    sec_out = None
    try:
        sec_out = pipe.run_action(racing_date, course, "sync_jjjc_sectionals")
    except Exception as e:
        sec_out = {"ok": False, "error": str(e)[:200]}
    bf_out = None
    if also_backfill and getattr(pipe, "engine", None) is not None:
        try:
            bf_out = backfill_meeting_sectionals(pipe.engine, racing_date, course)
        except Exception as e:
            bf_out = {"ok": False, "error": str(e)[:200]}
    inv = meeting_inventory(pipe.engine, racing_date, course)
    finish_ok = bool(inv.get("finish_ok")) and not bool(inv.get("thin_results"))
    return {
        "ok": bool(sync_out.get("ok")) and finish_ok,
        "sync": sync_out,
        "sectionals_export": sec_out,
        "backfill": bf_out,
        "inventory": inv,
        "finish_ok": finish_ok,
        "sectional_times_ok": bool(inv.get("sectional_times_ok")),
        "diagnose": {
            "race_n": inv.get("race_n"),
            "finish_n": inv.get("finish_n"),
            "sync_race_count": sync_out.get("race_count"),
            "sync_runner_upserted": sync_out.get("runner_upserted"),
            "sync_waiting": sync_out.get("waiting"),
            "sync_detail": sync_out.get("detail") or sync_out.get("error"),
            "gaps": inv.get("gaps"),
        },
    }


def list_meetings_missing_sectional_times(
    engine,
    *,
    as_of: Optional[Any] = None,
    min_age_days: int = 5,
    max_age_days: int = 120,
    limit: int = 40,
    min_time_coverage: float = 0.8,
) -> List[Dict[str, Any]]:
    """
    已有名次但分段秒數未齊嘅歷史賽日。

    官網分段通常賽後約第 5 日齊 → min_age_days 預設 5。
    回傳按賽日新→舊；每項含 inventory 摘要。
    """
    from datetime import date, datetime, timedelta

    if as_of is None:
        today = date.today()
    elif isinstance(as_of, datetime):
        today = as_of.date()
    elif isinstance(as_of, date):
        today = as_of
    else:
        today = date.fromisoformat(str(as_of)[:10])

    min_age = max(0, int(min_age_days))
    max_age = max(min_age, int(max_age_days))
    newest = today - timedelta(days=min_age)
    oldest = today - timedelta(days=max_age)

    q = text(
        """
        SELECT substr(race_id, 1, 8) AS d8,
               UPPER(substr(race_id, 9, 2)) AS course,
               COUNT(DISTINCT race_id) AS race_n,
               SUM(CASE WHEN finish_order_num IS NOT NULL THEN 1 ELSE 0 END) AS finish_n
        FROM runners
        WHERE finish_order_num IS NOT NULL
          AND length(race_id) >= 10
        GROUP BY 1, 2
        ORDER BY 1 DESC
        """
    )
    df = pd.read_sql(q, engine)
    out: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return out

    for row in df.itertuples(index=False):
        d8 = str(getattr(row, "d8") or "")
        course = str(getattr(row, "course") or "").upper()
        if len(d8) != 8 or course not in {"ST", "HV"}:
            continue
        try:
            rd = date(int(d8[:4]), int(d8[4:6]), int(d8[6:8]))
        except ValueError:
            continue
        if rd < oldest or rd > newest:
            continue
        racing_date = rd.isoformat()
        inv = meeting_inventory(engine, racing_date, course)
        if not inv.get("finish_ok"):
            continue
        if float(inv.get("sectional_time_coverage") or 0) >= float(min_time_coverage):
            continue
        out.append(
            {
                "racing_date": racing_date,
                "course": course,
                "age_days": (today - rd).days,
                "finish_n": int(inv.get("finish_n") or 0),
                "with_sectional_times": int(inv.get("with_sectional_times") or 0),
                "sectional_time_coverage": float(
                    inv.get("sectional_time_coverage") or 0
                ),
                "gaps": list(inv.get("gaps") or []),
                "status": inv.get("status"),
            }
        )
        if len(out) >= max(1, int(limit)):
            break
    return out


def list_meetings_missing_running_comments(
    engine,
    *,
    as_of: Optional[Any] = None,
    min_age_days: int = 2,
    max_age_days: int = 120,
    limit: int = 24,
    min_coverage: float = 0.8,
) -> List[Dict[str, Any]]:
    """
    已有名次但沿途評述覆蓋未達標的歷史賽日。

    沿途常在賽後才由馬會頁補上，上游卻把 placeholder 空殼停住。
    超出 backlog 保留窗（預設 14 日）後仍要掃到 max_age。
    """
    from datetime import date, datetime, timedelta

    if as_of is None:
        today = date.today()
    elif isinstance(as_of, datetime):
        today = as_of.date()
    elif isinstance(as_of, date):
        today = as_of
    else:
        today = date.fromisoformat(str(as_of)[:10])

    min_age = max(0, int(min_age_days))
    max_age = max(min_age, int(max_age_days))
    newest = today - timedelta(days=min_age)
    oldest = today - timedelta(days=max_age)

    q = text(
        """
        SELECT substr(race_id, 1, 8) AS d8,
               UPPER(substr(race_id, 9, 2)) AS course,
               COUNT(DISTINCT race_id) AS race_n,
               SUM(CASE WHEN finish_order_num IS NOT NULL THEN 1 ELSE 0 END) AS finish_n
        FROM runners
        WHERE finish_order_num IS NOT NULL
          AND length(race_id) >= 10
        GROUP BY 1, 2
        ORDER BY 1 DESC
        """
    )
    df = pd.read_sql(q, engine)
    out: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return out

    for row in df.itertuples(index=False):
        d8 = str(getattr(row, "d8") or "")
        course = str(getattr(row, "course") or "").upper()
        if len(d8) != 8 or course not in {"ST", "HV"}:
            continue
        try:
            rd = date(int(d8[:4]), int(d8[4:6]), int(d8[6:8]))
        except ValueError:
            continue
        if rd < oldest or rd > newest:
            continue
        racing_date = rd.isoformat()
        inv = meeting_inventory(engine, racing_date, course)
        if not inv.get("finish_ok"):
            continue
        if bool(inv.get("running_comment_ok")):
            continue
        if float(inv.get("running_comment_coverage") or 0) >= float(min_coverage):
            continue
        out.append(
            {
                "racing_date": racing_date,
                "course": course,
                "age_days": (today - rd).days,
                "finish_n": int(inv.get("finish_n") or 0),
                "running_comment_n": int(inv.get("running_comment_n") or 0),
                "running_comment_coverage": float(
                    inv.get("running_comment_coverage") or 0
                ),
                "gaps": list(inv.get("gaps") or []),
                "status": inv.get("status"),
            }
        )
        if len(out) >= max(1, int(limit)):
            break
    return out


def sync_running_comments_for_meeting(pipe, racing_date: str, course: str) -> Dict[str, Any]:
    """
    沿途評述晚補：sync_meeting 會在可疑空殼時 POST /api/text-reports/fetch 再入庫。
    """
    from jjjc_text_reports_sync import sync_meeting

    try:
        sync_out = sync_meeting(
            str(racing_date)[:10],
            str(course).upper(),
            report_type="running_comment",
        )
    except Exception as e:
        sync_out = {"ok": False, "waiting": False, "error": str(e)[:300]}

    inv = meeting_inventory(pipe.engine, racing_date, course)
    running_ok = bool(inv.get("running_comment_ok"))
    waiting = bool(sync_out.get("waiting")) and not running_ok
    return {
        "ok": bool(sync_out.get("ok")) or running_ok,
        "waiting": waiting,
        "sync": sync_out,
        "inventory": inv,
        "running_comment_ok": running_ok,
    }


def list_meetings_needing_results_resync(
    engine,
    *,
    as_of: Optional[Any] = None,
    min_age_days: int = 0,
    max_age_days: int = 21,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    無名次／半空賽果（場次 <5）嘅已完賽日。

    來源：fixtures ∪ runners 聚合；超出 lookback 仍可由 tick RESULTS_REPAIR 掃。
    """
    from datetime import date, datetime, timedelta

    if as_of is None:
        today = date.today()
    elif isinstance(as_of, datetime):
        today = as_of.date()
    elif isinstance(as_of, date):
        today = as_of
    else:
        today = date.fromisoformat(str(as_of)[:10])

    min_age = max(0, int(min_age_days))
    max_age = max(min_age, int(max_age_days))
    newest = today - timedelta(days=min_age)
    oldest = today - timedelta(days=max_age)

    candidates: Dict[Tuple[str, str], None] = {}

    # fixtures 視窗
    try:
        fx = pd.read_sql(
            text(
                """
                SELECT DISTINCT racing_date, course FROM fixtures
                WHERE CAST(racing_date AS TEXT) >= :a
                  AND CAST(racing_date AS TEXT) <= :b
                """
            ),
            engine,
            params={"a": oldest.isoformat(), "b": newest.isoformat()},
        )
        for row in fx.itertuples(index=False):
            d = str(getattr(row, "racing_date") or "")[:10]
            c = str(getattr(row, "course") or "").upper()
            if d and c in {"ST", "HV"}:
                candidates[(d, c)] = None
    except Exception:
        pass

    # runners 有資料但可能無名次／半空
    try:
        df = pd.read_sql(
            text(
                """
                SELECT substr(race_id, 1, 8) AS d8,
                       UPPER(substr(race_id, 9, 2)) AS course,
                       COUNT(DISTINCT race_id) AS race_n,
                       SUM(CASE WHEN finish_order_num IS NOT NULL THEN 1 ELSE 0 END) AS finish_n
                FROM runners
                WHERE length(race_id) >= 10
                GROUP BY 1, 2
                """
            ),
            engine,
        )
        for row in df.itertuples(index=False):
            d8 = str(getattr(row, "d8") or "")
            course = str(getattr(row, "course") or "").upper()
            if len(d8) != 8 or course not in {"ST", "HV"}:
                continue
            try:
                rd = date(int(d8[:4]), int(d8[4:6]), int(d8[6:8]))
            except ValueError:
                continue
            if rd < oldest or rd > newest:
                continue
            candidates[(rd.isoformat(), course)] = None
    except Exception:
        pass

    out: List[Dict[str, Any]] = []
    for racing_date, course in sorted(candidates.keys(), reverse=True):
        try:
            rd = date.fromisoformat(racing_date)
        except ValueError:
            continue
        if rd < oldest or rd > newest:
            continue
        inv = meeting_inventory(engine, racing_date, course)
        if inv.get("finish_ok") and not inv.get("thin_results"):
            continue
        # 未來賽日唔修
        if rd > today:
            continue
        gaps = list(inv.get("gaps") or [])
        needs = any("需重同步 RESULTS" in str(g) for g in gaps) or not inv.get(
            "finish_ok"
        )
        if not needs:
            continue
        out.append(
            {
                "racing_date": racing_date,
                "course": course,
                "age_days": (today - rd).days,
                "race_n": int(inv.get("race_n") or 0),
                "finish_n": int(inv.get("finish_n") or 0),
                "thin_results": bool(inv.get("thin_results")),
                "gaps": gaps,
                "status": inv.get("status"),
            }
        )
        if len(out) >= max(1, int(limit)):
            break
    return out


def repair_results_for_meeting(
    pipe,
    racing_date: str,
    course: str,
    *,
    also_text_reports: bool = True,
    also_sectionals: bool = True,
) -> Dict[str, Any]:
    """
    補齊單日名次：auto-fetch 半空 export → upsert；可選 text-reports／R2 分段。
    """
    d = str(racing_date)[:10]
    c = str(course or "").upper()
    out: Dict[str, Any] = {
        "ok": True,
        "racing_date": d,
        "course": c,
        "action": "repair_results",
    }
    try:
        sync_out = pipe.run_action(
            d, c, "sync_jjjc_results", skip_sectionals=not also_sectionals
        )
        out["sync"] = sync_out
        if sync_out.get("ok") is False:
            out["ok"] = False
            out["error"] = sync_out.get("error") or sync_out.get("detail")
        if sync_out.get("waiting"):
            out["waiting"] = True
    except Exception as e:
        out["ok"] = False
        out["sync"] = {"ok": False, "error": str(e)[:200]}
        out["error"] = str(e)[:200]

    if also_text_reports:
        try:
            out["text_reports"] = pipe.run_action(d, c, "sync_jjjc_text_reports")
        except Exception as e:
            out["text_reports"] = {"ok": False, "error": str(e)[:200]}

    inv = meeting_inventory(pipe.engine, d, c)
    out["inventory"] = {
        k: inv.get(k)
        for k in (
            "race_n",
            "finish_n",
            "finish_ok",
            "thin_results",
            "running_comment_n",
            "incident_n",
            "with_sectional_times",
            "gaps",
            "status",
        )
    }
    out["finish_ok"] = bool(inv.get("finish_ok")) and not bool(inv.get("thin_results"))
    if out.get("finish_ok"):
        out["waiting"] = False
        out["ok"] = True
    elif out.get("waiting") is None and not out.get("finish_ok"):
        out["waiting"] = True
    return out


def sync_sectional_times_for_meeting(
    pipe,
    racing_date: str,
    course: str,
    *,
    also_backfill: bool = True,
    also_resync_results: bool = False,
) -> Dict[str, Any]:
    """
    補齊單日分段秒數：優先 R2 jjjc.sectionals.v1，再 raw_json 回填。
    可選重跑 results（較重；日常 late-backfill 唔使）。
    """
    d = str(racing_date)[:10]
    c = str(course or "").upper()
    out: Dict[str, Any] = {
        "ok": True,
        "racing_date": d,
        "course": c,
        "action": "sync_sectional_times",
    }
    if also_resync_results:
        try:
            out["sync"] = pipe.run_action(d, c, "sync_jjjc_results", skip_sectionals=True)
        except Exception as e:
            out["sync"] = {"ok": False, "error": str(e)[:200]}
    try:
        sec = pipe.run_action(d, c, "sync_jjjc_sectionals")
        out["sectionals_export"] = sec
        if sec.get("waiting"):
            out["waiting"] = True
        if sec.get("ok") is False:
            out["ok"] = False
            out["error"] = sec.get("error") or sec.get("detail")
    except Exception as e:
        out["ok"] = False
        out["waiting"] = False
        out["sectionals_export"] = {"ok": False, "error": str(e)[:200]}
        out["error"] = str(e)[:200]

    if also_backfill and getattr(pipe, "engine", None) is not None:
        try:
            out["backfill"] = backfill_meeting_sectionals(pipe.engine, d, c)
        except Exception as e:
            out["backfill"] = {"ok": False, "error": str(e)[:200]}

    inv = meeting_inventory(pipe.engine, d, c)
    out["inventory"] = {
        k: inv.get(k)
        for k in (
            "finish_n",
            "with_sections",
            "with_sectional_times",
            "sectional_time_coverage",
            "sectional_times_ok",
            "gaps",
            "status",
        )
    }
    out["sectional_times_ok"] = bool(inv.get("sectional_times_ok"))
    if out.get("sectional_times_ok"):
        out["waiting"] = False
        out["ok"] = True
    elif out.get("waiting") is None and not out.get("sectional_times_ok"):
        # 上游可能仍 empty；標 waiting 方便 tick 冷卻重試
        out["waiting"] = True
    return out


def race_field_size_warning(engine, race_id: str) -> Optional[str]:
    """
    單場場額檢查。HV 出現 #13/#14 或 >12 匹 → 警告字串；正常回 None。
    """
    rid = str(race_id or "").strip()
    if not rid:
        return None
    venue = venue_from_race_id(rid)
    cap = max_horse_no_for_venue(venue)
    if cap is None:
        return None
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT horse_no FROM runners WHERE race_id = :rid
                """
            ),
            {"rid": rid},
        ).fetchall()
    nos = [r[0] for r in rows if r and r[0] is not None]
    issues = field_size_issues(venue, nos, race_id=rid)
    if not issues:
        return None
    return "；".join(issues)


def list_historical_races(engine, racing_date: str, course: str) -> pd.DataFrame:
    """歷史庫場次（race_id 前綴），供選賽日後揀場睇分段。"""
    prefix = _prefix(racing_date, course)
    q = text(
        """
        SELECT
          r.race_id,
          r.race_num,
          r.distance_m,
          r.class AS race_class,
          COUNT(DISTINCT ru.runner_id) AS runner_n,
          COUNT(DISTINCT CASE WHEN ru.finish_order_num IS NOT NULL THEN ru.runner_id END) AS finish_n,
          COUNT(DISTINCT rs.runner_id) AS section_runner_n
        FROM races r
        LEFT JOIN runners ru ON ru.race_id = r.race_id
        LEFT JOIN runner_sections rs ON rs.runner_id = ru.runner_id
        WHERE r.race_id LIKE :p || '%'
        GROUP BY r.race_id, r.race_num, r.distance_m, r.class
        ORDER BY r.race_num
        """
    )
    try:
        df = pd.read_sql(q, engine, params={"p": prefix})
        if not df.empty:
            return df
    except Exception:
        pass
    q2 = text(
        """
        SELECT
          ru.race_id,
          CAST(SUBSTR(ru.race_id, 11, 2) AS INTEGER) AS race_num,
          COUNT(DISTINCT ru.runner_id) AS runner_n,
          COUNT(DISTINCT CASE WHEN ru.finish_order_num IS NOT NULL THEN ru.runner_id END) AS finish_n,
          COUNT(DISTINCT rs.runner_id) AS section_runner_n
        FROM runners ru
        LEFT JOIN runner_sections rs ON rs.runner_id = ru.runner_id
        WHERE ru.race_id LIKE :p || '%'
        GROUP BY ru.race_id
        ORDER BY race_num
        """
    )
    try:
        return pd.read_sql(q2, engine, params={"p": prefix})
    except Exception:
        return pd.DataFrame()


def race_sectionals_grid(engine, race_id: str) -> pd.DataFrame:
    """
    單場各馬分段內容（選賽日／場次後直接睇）。
    欄：馬號、馬名、名次、完成時間、走位、各段名次／時間。
    """
    rid = str(race_id or "").strip()
    if not rid:
        return pd.DataFrame()

    with engine.connect() as conn:
        runners = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT runner_id, horse_no, horse_name, brand_num, finish_order_num, final_time
                    FROM runners
                    WHERE race_id = :rid
                    ORDER BY
                      CASE WHEN finish_order_num IS NULL THEN 999 ELSE finish_order_num END,
                      horse_no
                    """
                ),
                {"rid": rid},
            ).mappings().all()
        ]
        secs = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT runner_id, stage_no, position_raw, sectional_time,
                           split_1, split_2, distance_behind_raw
                    FROM runner_sections
                    WHERE runner_id IN (
                      SELECT runner_id FROM runners WHERE race_id = :rid
                    )
                    ORDER BY runner_id, stage_no
                    """
                ),
                {"rid": rid},
            ).mappings().all()
        ]
        race_secs = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT stage_no, sectional_time, split_1, split_2
                    FROM race_sectionals
                    WHERE race_id = :rid
                    ORDER BY stage_no
                    """
                ),
                {"rid": rid},
            ).mappings().all()
        ]

    by_runner: Dict[str, List[Dict[str, Any]]] = {}
    max_stage = 0
    for s in secs:
        by_runner.setdefault(str(s["runner_id"]), []).append(s)
        try:
            max_stage = max(max_stage, int(s["stage_no"] or 0))
        except (TypeError, ValueError):
            pass

    rows: List[Dict[str, Any]] = []
    for ru in runners:
        rid_u = str(ru["runner_id"])
        stages = sorted(
            by_runner.get(rid_u) or [], key=lambda x: int(x.get("stage_no") or 0)
        )
        pos_parts: List[str] = []
        time_parts: List[str] = []
        row: Dict[str, Any] = {
            "馬號": ru.get("horse_no"),
            "馬碼": ru.get("brand_num"),
            "馬名": ru.get("horse_name"),
            "名次": ru.get("finish_order_num"),
            "完成時間": ru.get("final_time"),
        }
        for stg in stages:
            sn = int(stg.get("stage_no") or 0)
            pos = stg.get("position_raw")
            tm = stg.get("sectional_time")
            if pos is not None and str(pos).strip() != "":
                pos_parts.append(str(pos).strip())
            if tm is not None and str(tm).strip() != "":
                time_parts.append(str(tm).strip())
            row[f"S{sn}名次"] = pos
            row[f"S{sn}時間"] = tm
            if stg.get("distance_behind_raw"):
                row[f"S{sn}距離"] = stg.get("distance_behind_raw")
        for sn in range(1, max_stage + 1):
            row.setdefault(f"S{sn}名次", None)
            row.setdefault(f"S{sn}時間", None)
        row["走位"] = "-".join(pos_parts) if pos_parts else ""
        row["分段時間串"] = " / ".join(time_parts) if time_parts else ""
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty and max_stage:
        front = ["馬號", "馬碼", "馬名", "名次", "完成時間", "走位", "分段時間串"]
        mid: List[str] = []
        for sn in range(1, max_stage + 1):
            mid.extend([f"S{sn}名次", f"S{sn}時間"])
            if f"S{sn}距離" in df.columns:
                mid.append(f"S{sn}距離")
        cols = [c for c in front + mid if c in df.columns]
        df = df[cols]
    df.attrs["race_sectionals"] = race_secs
    df.attrs["race_id"] = rid
    df.attrs["max_stage"] = max_stage
    return df
