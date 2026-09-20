"""
修復 runners（及可選 factor_scores）入面嘅英文馬／騎／練顯示名。

流程：
  1. 從 racecard 別名表 + upcoming↔runners 配對 + 馬碼中文名，建立 EN→ZH
  2. UPDATE runners 拉丁名 → 中文
  3. （可選）改 factor_scores 入面 JOCKEY／TRAINER／SYNERGY／HORSE_JOCKEY 實體名
  4. 之後仍需主頁「重算因子」先徹底清統計污染

CLI：
  python name_remediator.py --date 2026-09-13 --course ST
  python name_remediator.py --all
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text

from bucket_utils import normalize_person_name, synergy_name
from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE
from jjjc_export_common import looks_latin_name, prefer_zh_text
from name_aliases import (
    ensure_name_aliases_table,
    harvest_from_upcoming_vs_runners,
    harvest_horse_brand_aliases,
    load_alias_maps,
    resolve_via_alias,
)

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


def _engine():
    return create_engine(DATABASE_URL_SYNC)


def _prefix(racing_date: Optional[str], course: Optional[str]) -> Optional[str]:
    if not racing_date or not course:
        return None
    d = str(racing_date).strip().replace("-", "")[:8]
    v = str(course).strip().upper()
    if len(d) != 8 or v not in ("ST", "HV"):
        return None
    return f"{d}{v}"


def refresh_alias_sources(conn) -> Dict[str, int]:
    ensure_name_aliases_table(conn)
    n_pair = harvest_from_upcoming_vs_runners(conn)
    n_brand = harvest_horse_brand_aliases(conn)
    return {"from_upcoming_pair": n_pair, "from_brand": n_brand}


def remediate_runners(
    conn,
    *,
    prefix: Optional[str] = None,
    maps: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    maps = maps or load_alias_maps(conn)
    params: Dict[str, Any] = {}
    where = "1=1"
    if prefix:
        where = "race_id LIKE :p || '%'"
        params["p"] = prefix
    rows = (
        conn.execute(
            text(
                f"""
                SELECT runner_id, brand_num, horse_name, jockey_name, trainer_name
                FROM runners WHERE {where}
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    updated = 0
    samples: List[Dict[str, str]] = []
    for r in rows:
        h0 = r.get("horse_name")
        j0 = r.get("jockey_name")
        t0 = r.get("trainer_name")
        nh = prefer_zh_text(
            resolve_via_alias("horse", h0, maps), h0
        ) or h0
        nj = prefer_zh_text(
            resolve_via_alias("jockey", j0, maps), j0
        ) or j0
        nt = prefer_zh_text(
            resolve_via_alias("trainer", t0, maps), t0
        ) or t0
        if nh == h0 and nj == j0 and nt == t0:
            continue
        conn.execute(
            text(
                """
                UPDATE runners
                SET horse_name = :h, jockey_name = :j, trainer_name = :t
                WHERE runner_id = :rid
                """
            ),
            {"h": nh, "j": nj, "t": nt, "rid": r["runner_id"]},
        )
        updated += 1
        if len(samples) < 12:
            samples.append(
                {
                    "runner_id": str(r["runner_id"]),
                    "horse": f"{h0} → {nh}" if h0 != nh else str(nh or ""),
                    "jockey": f"{j0} → {nj}" if j0 != nj else str(nj or ""),
                    "trainer": f"{t0} → {nt}" if t0 != nt else str(nt or ""),
                }
            )
    return {"runners_updated": updated, "samples": samples}


def remediate_factor_scores(
    conn,
    *,
    maps: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    就地改 JOCKEY／TRAINER／SYNERGY／HORSE_JOCKEY 嘅 entity_name。
    HORSE／PACE／SPEED 若已用馬碼做 entity 則跳過拉丁馬名列。
    徹底修復仍建議重算因子。
    """
    maps = maps or load_alias_maps(conn)
    try:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT factor_type, bucket_id, entity_name
                    FROM factor_scores
                    WHERE factor_type IN (
                      'JOCKEY', 'TRAINER', 'SYNERGY', 'HORSE_JOCKEY', 'HORSE'
                    )
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception as e:
        return {"factor_rows_updated": 0, "error": str(e)[:200]}

    updated = 0
    for r in rows:
        ft = str(r.get("factor_type") or "")
        ent = str(r.get("entity_name") or "")
        if not ent or not looks_latin_name(ent.replace("&", " ")):
            # synergy 可能「B Avdulla & C S Shum」——整串有拉丁都試
            if ft not in ("SYNERGY", "HORSE_JOCKEY") or "&" not in ent:
                if not looks_latin_name(ent):
                    continue
        new_ent = ent
        if ft == "JOCKEY":
            new_ent = resolve_via_alias("jockey", ent, maps) or ent
        elif ft == "TRAINER":
            new_ent = resolve_via_alias("trainer", ent, maps) or ent
        elif ft == "HORSE":
            new_ent = resolve_via_alias("horse", ent, maps) or ent
        elif ft == "SYNERGY":
            parts = [p.strip() for p in ent.split("&", 1)]
            if len(parts) == 2:
                j = resolve_via_alias("jockey", parts[0], maps) or parts[0]
                t = resolve_via_alias("trainer", parts[1], maps) or parts[1]
                new_ent = synergy_name(j, t)
        elif ft == "HORSE_JOCKEY":
            parts = [p.strip() for p in ent.split("&", 1)]
            if len(parts) == 2:
                h = resolve_via_alias("horse", parts[0], maps) or parts[0]
                j = resolve_via_alias("jockey", parts[1], maps) or parts[1]
                new_ent = f"{normalize_person_name(h)} & {normalize_person_name(j)}"
        if new_ent == ent:
            continue
        # 若目標名已存在同桶，刪舊留新（避免 PK 衝突）；唔知 schema 就試 UPDATE
        try:
            conn.execute(
                text(
                    """
                    UPDATE factor_scores
                    SET entity_name = :new
                    WHERE factor_type = :ft AND bucket_id = :b AND entity_name = :old
                    """
                ),
                {
                    "new": new_ent,
                    "ft": ft,
                    "b": r["bucket_id"],
                    "old": ent,
                },
            )
            updated += 1
        except Exception:
            # 可能 UNIQUE(factor_type, bucket_id, entity_name)：合併刪舊
            try:
                conn.execute(
                    text(
                        """
                        DELETE FROM factor_scores
                        WHERE factor_type = :ft AND bucket_id = :b AND entity_name = :old
                        """
                    ),
                    {"ft": ft, "b": r["bucket_id"], "old": ent},
                )
                updated += 1
            except Exception:
                pass
    return {"factor_rows_updated": updated}


def remediate_meeting(
    racing_date: Optional[str] = None,
    course: Optional[str] = None,
    *,
    all_meetings: bool = False,
    also_factors: bool = True,
    engine=None,
) -> Dict[str, Any]:
    prefix = None if all_meetings else _prefix(racing_date, course)
    if not all_meetings and not prefix:
        return {
            "ok": False,
            "error": "需要 --date + --course，或 --all",
        }
    own = engine is None
    eng = engine or _engine()
    try:
        with eng.begin() as conn:
            harvest = refresh_alias_sources(conn)
            maps = load_alias_maps(conn)
            runners = remediate_runners(conn, prefix=prefix, maps=maps)
            factors = (
                remediate_factor_scores(conn, maps=maps)
                if also_factors
                else {"factor_rows_updated": 0, "skipped": True}
            )
        return {
            "ok": True,
            "prefix": prefix or "*",
            "harvest": harvest,
            "alias_counts": {k: len(v) for k, v in maps.items()},
            "runners": runners,
            "factors": factors,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "next": "主頁或作戰室「重算因子」以合併中英拆散嘅 JOCKEY／TRAINER 統計",
        }
    finally:
        if own:
            eng.dispose()


def count_latin_runners(engine, prefix: Optional[str] = None) -> int:
    params: Dict[str, Any] = {}
    where = "1=1"
    if prefix:
        where = "race_id LIKE :p || '%'"
        params["p"] = prefix
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT horse_name, jockey_name, trainer_name FROM runners
                WHERE {where}
                """
            ),
            params,
        ).fetchall()
    n = 0
    for h, j, t in rows:
        if looks_latin_name(h) or looks_latin_name(j) or looks_latin_name(t):
            n += 1
    return n


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="修復 runners 英文馬／騎／練名 → 中文")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--course", "--venue", dest="course", help="ST or HV")
    p.add_argument("--all", action="store_true", help="全庫 runners")
    p.add_argument(
        "--skip-factors",
        action="store_true",
        help="唔改 factor_scores（之後重算即可）",
    )
    args = p.parse_args(argv)
    out = remediate_meeting(
        args.date,
        args.course,
        all_meetings=bool(args.all),
        also_factors=not args.skip_factors,
    )
    import json

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
