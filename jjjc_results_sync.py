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
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from sqlalchemy import create_engine, text

from etl_pipeline import SQLITE_DB_PATH, USE_SQLITE
from jjjc_export_common import (
    display_horse_name,
    display_jockey_name,
    display_trainer_name,
    horse_no_allowed_for_venue,
    is_real_horse_code,
    max_horse_no_for_venue,
    normalize_venue,
    prefer_zh_text,
    venue_from_race_id,
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

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv("DATABASE_URL") or os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )
    if DATABASE_URL_SYNC.startswith("postgres://"):
        DATABASE_URL_SYNC = DATABASE_URL_SYNC.replace("postgres://", "postgresql://", 1)


def _api_base(explicit: Optional[str] = None) -> str:
    from jjjc_export_common import api_base

    return api_base(explicit)


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


def _clip(v: Any, max_len: int) -> Optional[str]:
    """裁切字串以符合既有 PG varchar 上限（避免 StringDataRightTruncation 令成日 sync 回滾）。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if len(s) <= max_len:
        return s
    return s[: max(1, max_len - 1)] + "…"


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


def _load_zh_name_maps(
    conn, race_id: str, *, brands: Optional[List[str]] = None
) -> Dict[str, Dict[str, str]]:
    """
    由排位／既有歷史列撈中文名，key=馬碼或 horse_no。
    results export 多數只有英文；racecard／sectionals／舊 runners 有中文。
    """
    by_brand: Dict[str, Dict[str, str]] = {}
    by_no: Dict[str, Dict[str, str]] = {}

    def _ingest(rows, *, brand_key: str = "brand") -> None:
        for r in rows:
            if not r:
                continue
            row = dict(r)
            hn = display_horse_name(row) or row.get("horse_name")
            jn = display_jockey_name(row) or row.get("jockey_name")
            tn = display_trainer_name(row) or row.get("trainer_name")
            brand = (
                str(row.get(brand_key) or row.get("brand_num") or row.get("horse_code") or "")
                .strip()
                .upper()
            )
            payload = {}
            if hn:
                payload["horse_name"] = str(hn)
            if jn:
                payload["jockey_name"] = str(jn)
            if tn:
                payload["trainer_name"] = str(tn)
            if not payload:
                continue
            if brand:
                cur = by_brand.get(brand) or {}
                by_brand[brand] = {
                    "horse_name": prefer_zh_text(
                        payload.get("horse_name"), cur.get("horse_name")
                    )
                    or cur.get("horse_name"),
                    "jockey_name": prefer_zh_text(
                        payload.get("jockey_name"), cur.get("jockey_name")
                    )
                    or cur.get("jockey_name"),
                    "trainer_name": prefer_zh_text(
                        payload.get("trainer_name"), cur.get("trainer_name")
                    )
                    or cur.get("trainer_name"),
                }
            hno = _safe_int(row.get("horse_no"))
            if hno is not None:
                key = str(hno)
                cur = by_no.get(key) or {}
                by_no[key] = {
                    "horse_name": prefer_zh_text(
                        payload.get("horse_name"), cur.get("horse_name")
                    )
                    or cur.get("horse_name"),
                    "jockey_name": prefer_zh_text(
                        payload.get("jockey_name"), cur.get("jockey_name")
                    )
                    or cur.get("jockey_name"),
                    "trainer_name": prefer_zh_text(
                        payload.get("trainer_name"), cur.get("trainer_name")
                    )
                    or cur.get("trainer_name"),
                }

    try:
        up = (
            conn.execute(
                text(
                    """
                    SELECT horse_no, horse_name, horse_code, jockey_name, trainer_name
                    FROM upcoming_runners WHERE race_id = :rid
                    """
                ),
                {"rid": race_id},
            )
            .mappings()
            .all()
        )
        _ingest(up, brand_key="horse_code")
    except Exception:
        pass
    try:
        hist = (
            conn.execute(
                text(
                    """
                    SELECT horse_no, horse_name, brand_num, jockey_name, trainer_name
                    FROM runners WHERE race_id = :rid
                    """
                ),
                {"rid": race_id},
            )
            .mappings()
            .all()
        )
        _ingest(hist, brand_key="brand_num")
    except Exception:
        pass
    # 同馬碼喺其他場次嘅中文名（賽果英文覆蓋後仍可還原）
    brand_list = sorted(
        {
            str(b).strip().upper()
            for b in (brands or [])
            if b and str(b).strip() and str(b).strip().upper() not in ("NONE", "NAN")
        }
    )
    if brand_list:
        try:
            ph = ", ".join(f":b{i}" for i in range(len(brand_list)))
            params = {f"b{i}": brand_list[i] for i in range(len(brand_list))}
            cross = (
                conn.execute(
                    text(
                        f"""
                        SELECT horse_name, brand_num, jockey_name, trainer_name, horse_no
                        FROM runners
                        WHERE brand_num IN ({ph})
                        ORDER BY runner_id DESC
                        LIMIT 200
                        """
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            _ingest(cross, brand_key="brand_num")
        except Exception:
            pass
        try:
            ph = ", ".join(f":c{i}" for i in range(len(brand_list)))
            params = {f"c{i}": brand_list[i] for i in range(len(brand_list))}
            cross_up = (
                conn.execute(
                    text(
                        f"""
                        SELECT horse_name, horse_code, jockey_name, trainer_name, horse_no
                        FROM upcoming_runners
                        WHERE UPPER(horse_code) IN ({ph})
                        LIMIT 200
                        """
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            _ingest(cross_up, brand_key="horse_code")
        except Exception:
            pass
    return {"by_brand": by_brand, "by_no": by_no}


def _resolve_display_names(
    ru: Dict[str, Any],
    *,
    horse_no: int,
    brand: Optional[str],
    zh_maps: Dict[str, Dict[str, str]],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """results 列 + 排位／既有中文 → 顯示用馬／騎／練名。"""
    hint = {}
    if brand and brand in (zh_maps.get("by_brand") or {}):
        hint = zh_maps["by_brand"][brand]
    elif str(horse_no) in (zh_maps.get("by_no") or {}):
        hint = zh_maps["by_no"][str(horse_no)]
    horse = prefer_zh_text(
        display_horse_name(ru),
        hint.get("horse_name"),
        ru.get("horse_name"),
    )
    jockey = prefer_zh_text(
        display_jockey_name(ru),
        hint.get("jockey_name"),
        ru.get("jockey_name"),
    )
    trainer = prefer_zh_text(
        display_trainer_name(ru),
        hint.get("trainer_name"),
        ru.get("trainer_name"),
    )
    return horse, jockey, trainer


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


def _results_fetch_timeout() -> float:
    try:
        return float(os.getenv("JJJC_RESULTS_FETCH_TIMEOUT", "120") or 120)
    except (TypeError, ValueError):
        return 120.0


def trigger_results_fetch(
    race_date: str,
    venue: str,
    *,
    base_url: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """
    上游主動抓官方賽果：POST {base}/api/results/fetch?date=&venue=

    export 空時必須先打呢步，否則 sync 永遠「無賽果」。
    """
    base = _api_base(base_url)
    if not base:
        return {"ok": False, "error": "未設定 JJJC_API_BASE"}
    v = str(venue or "").strip().upper()
    if v not in {"ST", "HV"}:
        return {"ok": False, "error": f"venue 必須係 ST|HV，收到：{venue!r}"}
    params = {"date": _normalize_date(race_date), "venue": v}
    url = f"{base}/api/results/fetch"
    to = float(timeout if timeout is not None else _results_fetch_timeout())
    try:
        with httpx.Client(timeout=to, follow_redirects=True) as client:
            r = client.post(url, params=params)
        body: Dict[str, Any]
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
        race_count = _safe_int(body.get("race_count"))
        runner_count = _safe_int(body.get("runner_count"))
        ok = bool(body.get("ok", True))
        return {
            "ok": ok,
            "status_code": r.status_code,
            "url": url,
            "race_date": body.get("race_date") or params["date"],
            "venue_code": body.get("venue_code") or v,
            "race_count": race_count,
            "runner_count": runner_count,
            "race_ids": body.get("race_ids"),
            "response": body,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "url": url}


def load_payload_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("file payload 非 JSON object")
    return payload


def _meeting_race_prefix(race_date: str, venue_code: str) -> Optional[str]:
    d = _normalize_date(race_date).replace("-", "")[:8]
    v = str(venue_code or "").strip().upper()
    if len(d) != 8 or v not in ("ST", "HV"):
        return None
    return f"{d}{v}"


def _race_no_from_race_id(race_id: str) -> Optional[int]:
    s = str(race_id or "").strip().upper()
    if len(s) < 10:
        return None
    tail = s[10:]
    return _safe_int(tail)


def _prune_orphan_meeting_races(
    conn,
    *,
    race_date: str,
    venue_code: str,
    keep_race_ids: List[str],
) -> Dict[str, Any]:
    """
    刪除同日同場地、但不在本次 export 的 race／runners／payouts。

    安全規則（避免賽中 partial export 誤刪已入庫之後數場）：
    - 空 keep → 不刪
    - 無 finish 的幽靈場：可刪
    - 已有 finish_order_num 的場次：僅當本次 export 像「完整卡」
      （含 1..keep_max 全部、且 keep_max >= 既有最大場號）時才刪
      → 可清 HV09/10 幽靈；唔會因只同步到 R5 而刪走 R6–R8
    """
    prefix = _meeting_race_prefix(race_date, venue_code)
    keep = sorted({str(x).strip() for x in keep_race_ids if str(x).strip()})
    if not prefix or not keep:
        return {"race_ids": [], "runners": 0, "races": 0, "payouts": 0}

    existing = [
        str(r[0])
        for r in conn.execute(
            text(
                """
                SELECT DISTINCT race_id FROM runners
                WHERE race_id LIKE :p || '%'
                UNION
                SELECT DISTINCT race_id FROM races
                WHERE race_id LIKE :p || '%'
                """
            ),
            {"p": prefix},
        ).fetchall()
        if r and r[0]
    ]
    orphans = [rid for rid in existing if rid not in set(keep)]
    if not orphans:
        return {"race_ids": [], "runners": 0, "races": 0, "payouts": 0}

    keep_nos = {
        n for n in (_race_no_from_race_id(rid) for rid in keep) if n is not None
    }
    keep_max = max(keep_nos) if keep_nos else 0
    contiguous_full = bool(keep_nos) and keep_nos >= set(range(1, keep_max + 1))
    existing_nos = [
        n for n in (_race_no_from_race_id(rid) for rid in existing) if n is not None
    ]
    existing_max = max(existing_nos) if existing_nos else 0
    # 完整卡判斷：
    # - export 已覆蓋既有最高場號，或
    # - 典型全日卡 keep_max>=8（可清 HV09/10 幽靈）
    # 賽中只到 R5（keep_max=5）時唔好刪已有名次的 R6+。
    allow_prune_finished = bool(
        contiguous_full
        and keep_max > 0
        and (keep_max >= existing_max or keep_max >= 8)
    )

    finished_orphans = {
        str(r[0])
        for r in conn.execute(
            text(
                """
                SELECT DISTINCT race_id FROM runners
                WHERE race_id LIKE :p || '%'
                  AND finish_order_num IS NOT NULL
                """
            ),
            {"p": prefix},
        ).fetchall()
        if r and r[0]
    }

    deletable: List[str] = []
    skipped_protected: List[str] = []
    for rid in orphans:
        rno = _race_no_from_race_id(rid)
        if rid in finished_orphans:
            # 已有名次：只刪「高於本次 export 最高場號」的幽靈場
            if not (
                allow_prune_finished
                and rno is not None
                and rno > keep_max
            ):
                skipped_protected.append(rid)
                continue
        deletable.append(rid)

    if not deletable:
        return {
            "race_ids": [],
            "runners": 0,
            "races": 0,
            "payouts": 0,
            "prefix": prefix,
            "skipped_protected_race_ids": skipped_protected,
            "allow_prune_finished": allow_prune_finished,
        }

    runners_n = 0
    races_n = 0
    payouts_n = 0
    for rid in deletable:
        runners_n += _delete_runners_for_race(conn, rid)
        try:
            payouts_n += int(
                conn.execute(
                    text("DELETE FROM payouts WHERE race_id = :rid"),
                    {"rid": rid},
                ).rowcount
                or 0
            )
        except Exception:
            pass
        try:
            races_n += int(
                conn.execute(
                    text("DELETE FROM races WHERE race_id = :rid"),
                    {"rid": rid},
                ).rowcount
                or 0
            )
        except Exception:
            pass

    return {
        "race_ids": deletable,
        "runners": runners_n,
        "races": races_n,
        "payouts": payouts_n,
        "prefix": prefix,
        "skipped_protected_race_ids": skipped_protected,
        "allow_prune_finished": allow_prune_finished,
    }


def _snapshot_sectional_times_for_race(conn, race_id: str) -> List[Dict[str, Any]]:
    """
    賽果「整場換血」會刪 runner_sections；先按馬號／馬碼＋段號留低已有秒數，
    之後寫回，避免重跑賽果把 R2 分段時間清走。
    """
    rid = str(race_id or "").strip()
    if not rid:
        return []
    try:
        rows = conn.execute(
            text(
                """
                SELECT r.horse_no,
                       UPPER(COALESCE(r.brand_num, '')) AS brand_num,
                       rs.stage_no,
                       rs.sectional_time,
                       rs.split_1,
                       rs.split_2
                FROM runner_sections rs
                JOIN runners r ON r.runner_id = rs.runner_id
                WHERE r.race_id = :rid
                  AND rs.sectional_time IS NOT NULL
                  AND TRIM(CAST(rs.sectional_time AS TEXT)) != ''
                """
            ),
            {"rid": rid},
        ).mappings().all()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        hn = _safe_int(row.get("horse_no"))
        stage_no = _safe_int(row.get("stage_no"))
        tm = str(row.get("sectional_time") or "").strip()
        if hn is None or stage_no is None or not tm:
            continue
        out.append(
            {
                "horse_no": int(hn),
                "brand_num": str(row.get("brand_num") or "").strip().upper() or None,
                "stage_no": int(stage_no),
                "sectional_time": tm[:20],
                "split_1": row.get("split_1"),
                "split_2": row.get("split_2"),
            }
        )
    return out


def _restore_sectional_times_for_race(
    conn, race_id: str, snapshot: Sequence[Dict[str, Any]]
) -> int:
    """把 snapshot 嘅秒數寫回而家嘅 runner_sections（只補空，唔覆蓋已有時間）。"""
    rid = str(race_id or "").strip()
    if not rid or not snapshot:
        return 0
    restored = 0
    for item in snapshot:
        hn = _safe_int(item.get("horse_no"))
        stage_no = _safe_int(item.get("stage_no"))
        tm = str(item.get("sectional_time") or "").strip()
        if hn is None or stage_no is None or not tm:
            continue
        brand = str(item.get("brand_num") or "").strip().upper() or None
        params: Dict[str, Any] = {
            "rid": rid,
            "hn": int(hn),
            "stage": int(stage_no),
            "tm": tm[:20],
            "s1": item.get("split_1"),
            "s2": item.get("split_2"),
        }
        # 優先馬碼對齊，再退回馬號
        if brand:
            params["brand"] = brand
            sql = """
                UPDATE runner_sections AS rs
                SET sectional_time = COALESCE(
                      NULLIF(TRIM(CAST(rs.sectional_time AS TEXT)), ''),
                      :tm
                    ),
                    split_1 = COALESCE(rs.split_1, :s1),
                    split_2 = COALESCE(rs.split_2, :s2)
                FROM runners r
                WHERE rs.runner_id = r.runner_id
                  AND r.race_id = :rid
                  AND UPPER(COALESCE(r.brand_num, '')) = :brand
                  AND rs.stage_no = :stage
                  AND (
                    rs.sectional_time IS NULL
                    OR TRIM(CAST(rs.sectional_time AS TEXT)) = ''
                  )
                """
        else:
            sql = """
                UPDATE runner_sections AS rs
                SET sectional_time = COALESCE(
                      NULLIF(TRIM(CAST(rs.sectional_time AS TEXT)), ''),
                      :tm
                    ),
                    split_1 = COALESCE(rs.split_1, :s1),
                    split_2 = COALESCE(rs.split_2, :s2)
                FROM runners r
                WHERE rs.runner_id = r.runner_id
                  AND r.race_id = :rid
                  AND r.horse_no = :hn
                  AND rs.stage_no = :stage
                  AND (
                    rs.sectional_time IS NULL
                    OR TRIM(CAST(rs.sectional_time AS TEXT)) = ''
                  )
                """
        try:
            restored += int(conn.execute(text(sql), params).rowcount or 0)
        except Exception:
            continue
    return restored


def _delete_runners_for_race(
    conn, race_id: str, *, keep_horse_nos: Optional[set] = None,
    keep_runner_ids: Optional[set] = None,
) -> int:
    """
    刪某場 runners（及 runner_sections）。
    - keep_runner_ids：只留呢啲 runner_id（重同步清幽靈／舊 id）
    - keep_horse_nos：只留呢啲馬號（無 runner_id 清單時用）
    """
    rid = str(race_id or "").strip()
    if not rid:
        return 0
    params: Dict[str, Any] = {"rid": rid}

    if keep_runner_ids is not None:
        keep_ids = sorted({str(x).strip() for x in keep_runner_ids if str(x).strip()})
        if not keep_ids:
            return 0
        # 逐個綁定避免 SQL injection；場額 ≤14 所以列表短
        id_ph = ", ".join(f":kid{i}" for i in range(len(keep_ids)))
        for i, kid in enumerate(keep_ids):
            params[f"kid{i}"] = kid
        where = f"race_id = :rid AND runner_id NOT IN ({id_ph})"
    elif keep_horse_nos is not None:
        keep = sorted({int(n) for n in keep_horse_nos if n is not None})
        if not keep:
            # 空 keep 唔刪（避免 partial／空 runners 誤清）
            return 0
        placeholders = ", ".join(str(int(n)) for n in keep)
        where = f"race_id = :rid AND horse_no NOT IN ({placeholders})"
    else:
        where = "race_id = :rid"

    # 先刪分段，再刪 runners
    try:
        conn.execute(
            text(
                f"""
                DELETE FROM runner_sections
                WHERE runner_id IN (
                  SELECT runner_id FROM runners WHERE {where}
                )
                """
            ),
            params,
        )
    except Exception:
        pass
    return int(
        conn.execute(
            text(f"DELETE FROM runners WHERE {where}"),
            params,
        ).rowcount
        or 0
    )


def _prune_orphan_runners_in_race(
    conn,
    race_id: str,
    *,
    keep_runner_ids: Optional[List[str]] = None,
    keep_horse_nos: Optional[List[int]] = None,
) -> int:
    """同步後刪同場但不在本次 export 的馬（例如 HV 殘留 #13/#14 或舊 runner_id）。"""
    return _delete_runners_for_race(
        conn,
        race_id,
        keep_runner_ids=set(keep_runner_ids) if keep_runner_ids is not None else None,
        keep_horse_nos=set(keep_horse_nos) if keep_horse_nos is not None else None,
    )


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
    section_n = 0
    race_section_n = 0
    race_ids: List[str] = []
    rejected_runners: List[Dict[str, Any]] = []
    pruned_ghost_runners = 0
    field_warnings: List[str] = []
    pruned: Dict[str, Any] = {}

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
                venue = (
                    normalize_venue(race.get("venue_code"))
                    or normalize_venue(payload.get("venue_code"))
                    or venue_from_race_id(race_id)
                )
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
                        "race_id": _clip(race_id, 50) or race_id,
                        "meeting_id": _clip(meeting_id, 50),
                        "race_num": race_num,
                        # schema: title/class/distance_text/course/ground = VARCHAR(50)
                        # race_name = VARCHAR(100)；完整原文仍在 raw_detail_json
                        "title": _clip(f"R{race_num}" if race_num else None, 50),
                        "race_name": _clip(race.get("race_name"), 100),
                        "klass": _clip(race.get("race_class"), 50),
                        "distance_text": _clip(
                            f"{distance_m}米" if distance_m else None, 50
                        ),
                        "distance_m": distance_m,
                        "course": _clip(course_text, 50),
                        "ground": _clip(going, 50),
                        "raw": json.dumps(race, ensure_ascii=False),
                    },
                )

                keep_runner_ids: List[str] = []
                # 先收集今次會寫入嘅合法馬；清掉舊列（唔同 runner_id／#13+#14 幽靈），
                # 避免 UNIQUE(race_id, horse_no) 擋住重同步。
                pending_runners: List[Dict[str, Any]] = []
                for ru in race.get("runners") or []:
                    horse_no = _safe_int(ru.get("horse_no"))
                    if horse_no is None:
                        continue
                    if not horse_no_allowed_for_venue(horse_no, venue):
                        cap = max_horse_no_for_venue(venue)
                        rejected_runners.append(
                            {
                                "race_id": race_id,
                                "horse_no": horse_no,
                                "horse_name": ru.get("horse_name"),
                                "reason": f"{venue or '?'} 場額上限 {cap}，拒寫馬號 {horse_no}",
                            }
                        )
                        continue
                    pending_runners.append(ru)

                # 刪之前先撈中文名（排位 upcoming + 舊 runners + 同馬碼跨場）
                brands = [
                    str(ru.get("horse_code") or "").strip().upper()
                    for ru in pending_runners
                    if ru.get("horse_code")
                ]
                zh_maps = (
                    _load_zh_name_maps(conn, race_id, brands=brands)
                    if pending_runners
                    else {"by_brand": {}, "by_no": {}}
                )

                # 換血前先保留已有分段秒數（R2 後補嘅時間），否則 DELETE runner_sections 會清光
                sectional_snapshot = (
                    _snapshot_sectional_times_for_race(conn, race_id)
                    if pending_runners
                    else []
                )
                if pending_runners:
                    # 整場換血：刪本場全部舊 runners（含場額幽靈），再按 export 插入
                    pruned_ghost_runners += _delete_runners_for_race(conn, race_id)

                for ru in pending_runners:
                    horse_no = _safe_int(ru.get("horse_no"))
                    if horse_no is None:
                        continue
                    horse_code = ru.get("horse_code")
                    runner_id, horse_id, brand = _runner_ids(
                        race_id, horse_no, horse_code, race_date
                    )
                    horse_name, jockey_name, trainer_name = _resolve_display_names(
                        ru, horse_no=horse_no, brand=brand, zh_maps=zh_maps
                    )
                    fin_num = _safe_int(ru.get("finish_order_num"))
                    if fin_num is None:
                        fin_num = _safe_int(ru.get("finishing_position"))
                    if fin_num is None:
                        fin_num = _safe_int(ru.get("finish_position"))
                    if fin_num is None:
                        fin_num = _safe_int(ru.get("place"))
                    if fin_num is None:
                        fin_num = _safe_int(ru.get("position"))
                    fin_raw = (
                        ru.get("finishing_position_raw")
                        or ru.get("finish_order_raw")
                        or ru.get("place_raw")
                    )
                    if fin_raw is None and fin_num is not None:
                        fin_raw = str(fin_num)
                    win_odds = _safe_float(ru.get("win_odds"))
                    raw_meta = {
                        **ru,
                        "source": race.get("source") or "official_hkjc",
                        "synced_via": "jjjc_results_sync",
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                        "display_horse_name": horse_name,
                        "display_jockey_name": jockey_name,
                        "display_trainer_name": trainer_name,
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
                              horse_name = EXCLUDED.horse_name,
                              brand_num = COALESCE(EXCLUDED.brand_num, runners.brand_num),
                              finish_order_raw = EXCLUDED.finish_order_raw,
                              finish_order_num = EXCLUDED.finish_order_num,
                              final_time = COALESCE(EXCLUDED.final_time, runners.final_time),
                              jockey_name = EXCLUDED.jockey_name,
                              trainer_name = EXCLUDED.trainer_name,
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
                            "brand_num": brand if is_real_horse_code(brand) else None,
                            "horse_name": horse_name,
                            "finish_order_raw": str(fin_raw) if fin_raw is not None else None,
                            "finish_order_num": fin_num,
                            "final_time": ru.get("finish_time"),
                            "jockey_name": jockey_name,
                            "trainer_name": trainer_name,
                            "handicap_weight": _safe_float(ru.get("actual_weight")),
                            "bar_draw": _safe_int(ru.get("draw")),
                            "horse_body_weight": _safe_float(ru.get("declared_horse_weight")),
                            "scratched": False,
                            "win_odds": str(win_odds) if win_odds is not None else None,
                            "raw_json": json.dumps(raw_meta, ensure_ascii=False),
                        },
                    )
                    runner_n += 1
                    keep_runner_ids.append(runner_id)
                    # 結構化分段走位（running_position / sections）→ runner_sections
                    section_n += upsert_runner_sections(
                        conn, runner_id, stages_from_runner_payload(raw_meta)
                    )

                # 清同場幽靈馬（唔喺今次 upsert 嘅 runner_id；含 #13/#14 同舊 id）
                if keep_runner_ids:
                    pruned_ghost_runners += _prune_orphan_runners_in_race(
                        conn, race_id, keep_runner_ids=keep_runner_ids
                    )

                # 賽事層分段時間（若 export 有提供）
                race_times = (
                    race.get("sectional_times")
                    or race.get("sectionals")
                    or race.get("times")
                )
                race_section_n += upsert_race_sectionals(
                    conn, race_id, stages_from_race_times(race_times)
                )
                # 換血後把先前 R2 秒數補返（results 多數只有走位）
                if sectional_snapshot:
                    section_n += _restore_sectional_times_for_race(
                        conn, race_id, sectional_snapshot
                    )

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

            # 清掉同日同場地、但不在本次 export 的幽靈場次
            # （例如 batch_crawler 誤寫 HV09–10 → 覆蓋分母變成 10×14=140）
            pruned = _prune_orphan_meeting_races(
                conn,
                race_date=str(payload.get("race_date") or ""),
                venue_code=str(payload.get("venue_code") or ""),
                keep_race_ids=race_ids,
            )
    finally:
        engine.dispose()

    if rejected_runners:
        # 去重原因字串做摘要
        reasons = sorted({str(r.get("reason") or "") for r in rejected_runners})
        field_warnings.extend(reasons)

    return {
        "ok": True,
        "schema": schema,
        "race_date": payload.get("race_date"),
        "venue_code": payload.get("venue_code"),
        "race_count": len(race_ids),
        "race_ids": race_ids,
        "runner_upserted": runner_n,
        "payout_upserted": payout_n,
        "runner_sections_upserted": section_n,
        "race_sectionals_upserted": race_section_n,
        "pruned_orphan_races": pruned.get("race_ids") if isinstance(pruned, dict) else [],
        "pruned_runners": int((pruned or {}).get("runners") or 0) + pruned_ghost_runners,
        "pruned_ghost_runners": pruned_ghost_runners,
        "rejected_runners": rejected_runners,
        "rejected_runner_count": len(rejected_runners),
        "field_warnings": field_warnings,
        "source_preference": payload.get("source_preference"),
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
    """拉取（或讀檔）後 upsert；供 CLI 與 meeting_pipeline／meeting_tick 呼叫。

    export 空時（預設）會先 POST /api/results/fetch 再重試 export，
    避免 tick 永遠卡在「無賽果」而上游其實只差一槍 fetch。
    """
    upstream_fetch: Optional[Dict[str, Any]] = None
    if from_file:
        payload = load_payload_file(from_file)
    else:
        payload = fetch_export(
            race_date=racing_date,
            venue=course,
            race_no=race_no,
            base_url=base_url,
        )
        # export 空 → 主動 fetch → 再 export（完整自動鏈）
        if auto_fetch and not list(payload.get("races") or []):
            upstream_fetch = trigger_results_fetch(
                racing_date, course, base_url=base_url
            )
            # fetch 成功或即使部分成功都再讀一次；官方未上架則仍空
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
                    "error": f"results fetch 後 re-export 失敗：{e}",
                    "upstream_fetch": upstream_fetch,
                    "racing_date": _normalize_date(racing_date),
                    "course": str(course or "").upper(),
                }

    races = list(payload.get("races") or [])
    if not races and not from_file:
        # 官方未上架／未來賽日：waiting（唔當硬失敗，tick 可按冷卻重試）
        detail = "export 無賽果"
        if upstream_fetch is not None:
            if upstream_fetch.get("ok"):
                detail = (
                    "export 無賽果（已自動 results fetch；"
                    f"fetch race_count={upstream_fetch.get('race_count') or 0}；"
                    "官方可能尚未上架）"
                )
            else:
                detail = (
                    "export 無賽果（自動 results fetch 失敗："
                    f"{upstream_fetch.get('error') or upstream_fetch.get('status_code')}）"
                )
        return {
            "ok": True,
            "waiting": True,
            "error": None,
            "detail": detail,
            "payload_keys": list(payload.keys()),
            "upstream_fetch": upstream_fetch,
            "racing_date": _normalize_date(racing_date),
            "course": str(course or "").upper(),
            "race_count": 0,
            "runner_upserted": 0,
        }
    out = upsert_payload(payload)
    out["racing_date"] = _normalize_date(racing_date)
    out["course"] = course.upper()
    if upstream_fetch is not None:
        out["upstream_fetch"] = upstream_fetch
        out["auto_fetched"] = True
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
