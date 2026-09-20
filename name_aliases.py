"""
中英顯示名別名（馬／騎／練）。

來源：racecard `*_name_ch`／`*_name_en`；排位 upcoming（中文）對賽果 runners（英文）配對。
用途：修復 runners 英文污染、因子聚合前正規化騎練名。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import text

from bucket_utils import normalize_person_name
from jjjc_export_common import (
    display_horse_name,
    display_jockey_name,
    display_trainer_name,
    looks_latin_name,
    prefer_zh_text,
)

Kind = str  # horse | jockey | trainer


def alias_key(name: Any) -> str:
    """拉丁別名鍵：正規化後 upper（騎練「B Avdulla」／「b  avdulla」同一鍵）。"""
    s = normalize_person_name(name)
    if not s:
        return ""
    return s.upper()


def ensure_name_aliases_table(conn) -> None:
    dialect = getattr(getattr(conn, "dialect", None), "name", None) or ""
    # SQLite／Postgres 共用簡單 DDL
    if "postgres" in str(dialect).lower():
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS name_aliases (
                  kind VARCHAR(16) NOT NULL,
                  en_key VARCHAR(120) NOT NULL,
                  zh_name VARCHAR(120) NOT NULL,
                  source VARCHAR(64),
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (kind, en_key)
                )
                """
            )
        )
    else:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS name_aliases (
                  kind TEXT NOT NULL,
                  en_key TEXT NOT NULL,
                  zh_name TEXT NOT NULL,
                  source TEXT,
                  updated_at TEXT,
                  PRIMARY KEY (kind, en_key)
                )
                """
            )
        )


def upsert_alias(
    conn,
    kind: Kind,
    en_name: Any,
    zh_name: Any,
    *,
    source: str = "racecard",
) -> bool:
    """寫入一條 EN→ZH；只接受拉丁 en + 非拉丁 zh。回傳是否寫入。"""
    en = str(en_name or "").strip()
    zh = str(zh_name or "").strip()
    if not en or not zh:
        return False
    if not looks_latin_name(en):
        return False
    if looks_latin_name(zh):
        return False
    key = alias_key(en)
    if not key:
        return False
    ensure_name_aliases_table(conn)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        text(
            """
            INSERT INTO name_aliases (kind, en_key, zh_name, source, updated_at)
            VALUES (:kind, :en_key, :zh_name, :source, :updated_at)
            ON CONFLICT (kind, en_key) DO UPDATE SET
              zh_name = EXCLUDED.zh_name,
              source = EXCLUDED.source,
              updated_at = EXCLUDED.updated_at
            """
        ),
        {
            "kind": str(kind).strip().lower(),
            "en_key": key,
            "zh_name": zh,
            "source": source,
            "updated_at": now,
        },
    )
    return True


def harvest_aliases_from_row(conn, row: Dict[str, Any], *, source: str = "racecard") -> int:
    """從 racecard／export 列（含 *_ch／*_en）收別名。"""
    if not isinstance(row, dict):
        return 0
    n = 0
    pairs = (
        ("horse", row.get("horse_name_en"), display_horse_name(row)),
        ("jockey", row.get("jockey_name_en"), display_jockey_name(row)),
        ("trainer", row.get("trainer_name_en"), display_trainer_name(row)),
    )
    for kind, en, zh in pairs:
        # display_* 可能已係中文；en 欄可能空——用另一個拉丁候選
        zh_final = prefer_zh_text(zh, row.get(f"{kind}_name_ch"), row.get(f"{kind}_name"))
        en_final = en
        if not en_final or not looks_latin_name(en_final):
            # 若主欄係英文、ch 係中文
            main = row.get(f"{kind}_name")
            if looks_latin_name(main) and zh_final and not looks_latin_name(zh_final):
                en_final = main
        if upsert_alias(conn, kind, en_final, zh_final, source=source):
            n += 1
    return n


def load_alias_maps(conn) -> Dict[str, Dict[str, str]]:
    """kind → {en_key → zh_name}。"""
    ensure_name_aliases_table(conn)
    maps: Dict[str, Dict[str, str]] = {"horse": {}, "jockey": {}, "trainer": {}}
    try:
        rows = (
            conn.execute(text("SELECT kind, en_key, zh_name FROM name_aliases"))
            .mappings()
            .all()
        )
    except Exception:
        return maps
    for r in rows:
        kind = str(r.get("kind") or "").strip().lower()
        key = str(r.get("en_key") or "").strip().upper()
        zh = str(r.get("zh_name") or "").strip()
        if kind in maps and key and zh:
            maps[kind][key] = zh
    return maps


def resolve_via_alias(
    kind: Kind,
    name: Any,
    maps: Optional[Dict[str, Dict[str, str]]] = None,
    conn=None,
) -> Optional[str]:
    """有中文就保留；拉丁名則查別名表。"""
    raw = normalize_person_name(name) if name is not None else ""
    if not raw:
        return None
    if not looks_latin_name(raw):
        return raw
    if maps is None:
        if conn is None:
            return raw
        maps = load_alias_maps(conn)
    zh = (maps.get(str(kind).lower()) or {}).get(alias_key(raw))
    return prefer_zh_text(zh, raw) or raw


def harvest_from_upcoming_vs_runners(conn) -> int:
    """
    同場同馬號：upcoming（中）vs runners（英）→ 寫別名。
    唔使再打 API，適合賽果已寫英文、排位仍有中文嘅日。
    """
    n = 0
    try:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT
                      u.horse_name AS u_horse, r.horse_name AS r_horse,
                      u.jockey_name AS u_jockey, r.jockey_name AS r_jockey,
                      u.trainer_name AS u_trainer, r.trainer_name AS r_trainer
                    FROM upcoming_runners u
                    JOIN runners r
                      ON r.race_id = u.race_id AND r.horse_no = u.horse_no
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        return 0
    for row in rows:
        for kind, u_key, r_key in (
            ("horse", "u_horse", "r_horse"),
            ("jockey", "u_jockey", "r_jockey"),
            ("trainer", "u_trainer", "r_trainer"),
        ):
            u_val = row.get(u_key)
            r_val = row.get(r_key)
            zh = prefer_zh_text(u_val, r_val)
            en = r_val if looks_latin_name(r_val) else (
                u_val if looks_latin_name(u_val) else None
            )
            if upsert_alias(conn, kind, en, zh, source="upcoming_vs_runners"):
                n += 1
    return n


def harvest_horse_brand_aliases(conn) -> int:
    """同 brand_num／horse_code：有中文馬名 → 對英文馬名寫 horse 別名。"""
    n = 0
    try:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT brand_num AS code, horse_name AS name FROM runners
                    WHERE brand_num IS NOT NULL AND brand_num != ''
                    UNION ALL
                    SELECT UPPER(horse_code) AS code, horse_name AS name FROM upcoming_runners
                    WHERE horse_code IS NOT NULL AND horse_code != ''
                    """
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        return 0
    by_code: Dict[str, Dict[str, str]] = {}
    for r in rows:
        code = str(r.get("code") or "").strip().upper()
        name = str(r.get("name") or "").strip()
        if not code or not name:
            continue
        slot = by_code.setdefault(code, {"zh": "", "en": ""})
        if not looks_latin_name(name):
            slot["zh"] = prefer_zh_text(name, slot["zh"]) or slot["zh"]
        else:
            slot["en"] = name if not slot["en"] else slot["en"]
    for slot in by_code.values():
        if upsert_alias(conn, "horse", slot.get("en"), slot.get("zh"), source="brand"):
            n += 1
    return n
