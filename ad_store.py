"""
廣告包／文案歸檔的共用 DB 儲存（Postgres／SQLite）。

背景：APP-CORN、Streamlit、Ad API 常共 DATABASE_URL 但不共本機碟。
海報與 packages 只寫 ad_output/ 時，其他服務睇唔到。
本模組做 dual-write：磁碟照寫，同時 upsert 到 ad_packages／ad_archives。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _env_use_sqlite() -> bool:
    return (os.getenv("USE_SQLITE", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _sqlite_path() -> str:
    return (
        os.getenv("SQLITE_DB_PATH")
        or os.getenv("SQLITE_PATH")
        or str(Path(__file__).resolve().parent / "data" / "j18.db")
    )


def _resolve_database_url() -> str:
    for key in ("DATABASE_URL_SYNC", "DATABASE_URL", "RAILWAY_DATABASE_URL"):
        v = (os.getenv(key) or "").strip()
        if v:
            return v
    return f"sqlite:///{_sqlite_path()}"


# 延遲對齊 etl_pipeline，避免 import 時拉入 httpx 等重依賴
USE_SQLITE = _env_use_sqlite()
SQLITE_DB_PATH = _sqlite_path()

_ENGINE: Optional[Engine] = None
_ENSURED = False

DDL_PG = """
CREATE TABLE IF NOT EXISTS ad_packages (
    id VARCHAR(64) PRIMARY KEY,
    racing_date DATE NOT NULL,
    course VARCHAR(8) NOT NULL,
    batch_id VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    package_json JSONB NOT NULL,
    copy_json JSONB,
    social_json JSONB,
    poster_png BYTEA,
    webhook_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ad_packages_meeting ON ad_packages(racing_date, course);
CREATE INDEX IF NOT EXISTS idx_ad_packages_updated ON ad_packages(updated_at DESC);

CREATE TABLE IF NOT EXISTS ad_archives (
    racing_date DATE NOT NULL,
    course VARCHAR(8) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    batch_id VARCHAR(64),
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (racing_date, course, kind)
);
"""

DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS ad_packages (
    id TEXT PRIMARY KEY,
    racing_date TEXT NOT NULL,
    course TEXT NOT NULL,
    batch_id TEXT,
    status TEXT NOT NULL,
    package_json TEXT NOT NULL,
    copy_json TEXT,
    social_json TEXT,
    poster_png BLOB,
    webhook_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ad_packages_meeting ON ad_packages(racing_date, course);
CREATE INDEX IF NOT EXISTS idx_ad_packages_updated ON ad_packages(updated_at DESC);

CREATE TABLE IF NOT EXISTS ad_archives (
    racing_date TEXT NOT NULL,
    course TEXT NOT NULL,
    kind TEXT NOT NULL,
    batch_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (racing_date, course, kind)
);
"""


def ad_store_enabled() -> bool:
    """預設：有 DATABASE_URL（或非 sqlite-only）就開；可 AD_STORE_ENABLED=false 關閉。"""
    flag = (os.getenv("AD_STORE_ENABLED") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    # auto
    if USE_SQLITE and not (os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_SYNC")):
        # 純本地 sqlite 仍可用（寫入同一檔），方便測試
        return True
    return True


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    if USE_SQLITE:
        Path(SQLITE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{SQLITE_DB_PATH}"
    else:
        url = _resolve_database_url()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
    _ENGINE = create_engine(url)
    return _ENGINE


def ensure_ad_tables(engine: Optional[Engine] = None) -> None:
    global _ENSURED
    if _ENSURED:
        return
    eng = engine or get_engine()
    ddl = DDL_SQLITE if USE_SQLITE else DDL_PG
    with eng.begin() as conn:
        for stmt in ddl.split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
        # soft link column on snapshot batches
        try:
            if USE_SQLITE:
                conn.execute(
                    text(
                        "ALTER TABLE prediction_snapshot_batches "
                        "ADD COLUMN ad_status TEXT"
                    )
                )
            else:
                conn.execute(
                    text(
                        "ALTER TABLE prediction_snapshot_batches "
                        "ADD COLUMN IF NOT EXISTS ad_status VARCHAR(20)"
                    )
                )
        except Exception:
            pass
    _ENSURED = True


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _json_load(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def _meeting_from_pkg(pkg: Dict[str, Any]) -> Tuple[str, str]:
    meeting = pkg.get("meeting") if isinstance(pkg.get("meeting"), dict) else {}
    # support both schemas: meeting.date / meeting.racing_date
    d = str(
        meeting.get("date")
        or meeting.get("racing_date")
        or (pkg.get("meta") or {}).get("racing_date")
        or ""
    )[:10]
    c = str(
        meeting.get("venue_code")
        or meeting.get("course")
        or meeting.get("course_code")
        or (pkg.get("meta") or {}).get("course")
        or ""
    ).upper()
    return d, c


def upsert_ad_package(
    pkg: Dict[str, Any],
    *,
    poster_png: Optional[bytes] = None,
    copy_json: Optional[Dict[str, Any]] = None,
    social_json: Optional[Dict[str, Any]] = None,
    engine: Optional[Engine] = None,
) -> Dict[str, Any]:
    if not ad_store_enabled():
        return {"ok": False, "skipped": True, "reason": "AD_STORE_ENABLED=false"}
    ad_id = str(pkg.get("id") or "").strip()
    if not ad_id:
        return {"ok": False, "error": "package missing id"}
    ensure_ad_tables(engine)
    eng = engine or get_engine()
    racing_date, course = _meeting_from_pkg(pkg)
    if not racing_date:
        racing_date = str((pkg.get("meta") or {}).get("racing_date") or "")[:10]
    if not course:
        course = str((pkg.get("meta") or {}).get("course") or "XX").upper()
    meta = pkg.get("meta") if isinstance(pkg.get("meta"), dict) else {}
    batch_id = meta.get("batch_id")
    if not batch_id and isinstance(pkg.get("meeting"), dict):
        batch_id = (pkg.get("meeting") or {}).get("batch_id")
    status = str(pkg.get("status") or "pending")
    webhook = pkg.get("webhook")
    # strip local path before persist public-ish package
    store_pkg = json.loads(json.dumps(pkg, ensure_ascii=False, default=str))
    assets = store_pkg.get("assets")
    if isinstance(assets, dict):
        assets.pop("poster_path", None)

    params = {
        "id": ad_id,
        "racing_date": racing_date or None,
        "course": course or "XX",
        "batch_id": str(batch_id) if batch_id else None,
        "status": status,
        "package_json": _json_dump(store_pkg),
        "copy_json": _json_dump(copy_json) if copy_json is not None else None,
        "social_json": _json_dump(social_json) if social_json is not None else None,
        "poster_png": poster_png,
        "webhook_json": _json_dump(webhook) if webhook is not None else None,
    }

    with eng.begin() as conn:
        if USE_SQLITE:
            # preserve existing poster/copy/social if not provided
            prev = conn.execute(
                text("SELECT poster_png, copy_json, social_json FROM ad_packages WHERE id=:id"),
                {"id": ad_id},
            ).mappings().first()
            if prev:
                if params["poster_png"] is None:
                    params["poster_png"] = prev["poster_png"]
                if params["copy_json"] is None:
                    params["copy_json"] = prev["copy_json"]
                if params["social_json"] is None:
                    params["social_json"] = prev["social_json"]
            conn.execute(
                text(
                    """
                    INSERT INTO ad_packages (
                        id, racing_date, course, batch_id, status,
                        package_json, copy_json, social_json, poster_png, webhook_json,
                        created_at, updated_at
                    ) VALUES (
                        :id, :racing_date, :course, :batch_id, :status,
                        :package_json, :copy_json, :social_json, :poster_png, :webhook_json,
                        datetime('now'), datetime('now')
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        racing_date=excluded.racing_date,
                        course=excluded.course,
                        batch_id=COALESCE(excluded.batch_id, ad_packages.batch_id),
                        status=excluded.status,
                        package_json=excluded.package_json,
                        copy_json=COALESCE(excluded.copy_json, ad_packages.copy_json),
                        social_json=COALESCE(excluded.social_json, ad_packages.social_json),
                        poster_png=COALESCE(excluded.poster_png, ad_packages.poster_png),
                        webhook_json=COALESCE(excluded.webhook_json, ad_packages.webhook_json),
                        updated_at=datetime('now')
                    """
                ),
                params,
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO ad_packages (
                        id, racing_date, course, batch_id, status,
                        package_json, copy_json, social_json, poster_png, webhook_json
                    ) VALUES (
                        :id, CAST(:racing_date AS DATE), :course, :batch_id, :status,
                        CAST(:package_json AS JSONB),
                        CAST(:copy_json AS JSONB),
                        CAST(:social_json AS JSONB),
                        :poster_png,
                        CAST(:webhook_json AS JSONB)
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        racing_date = EXCLUDED.racing_date,
                        course = EXCLUDED.course,
                        batch_id = COALESCE(EXCLUDED.batch_id, ad_packages.batch_id),
                        status = EXCLUDED.status,
                        package_json = EXCLUDED.package_json,
                        copy_json = COALESCE(EXCLUDED.copy_json, ad_packages.copy_json),
                        social_json = COALESCE(EXCLUDED.social_json, ad_packages.social_json),
                        poster_png = COALESCE(EXCLUDED.poster_png, ad_packages.poster_png),
                        webhook_json = COALESCE(EXCLUDED.webhook_json, ad_packages.webhook_json),
                        updated_at = NOW()
                    """
                ),
                params,
            )
    return {"ok": True, "id": ad_id, "status": status}


def load_ad_package_db(
    ad_id: str, *, engine: Optional[Engine] = None
) -> Optional[Dict[str, Any]]:
    if not ad_store_enabled():
        return None
    try:
        ensure_ad_tables(engine)
        eng = engine or get_engine()
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT package_json FROM ad_packages WHERE id=:id"),
                {"id": ad_id},
            ).mappings().first()
        if not row:
            return None
        pkg = _json_load(row["package_json"])
        return pkg if isinstance(pkg, dict) else None
    except Exception as exc:
        logger.warning("load_ad_package_db failed: %s", exc)
        return None


def load_latest_ad_package_db(
    *, ready_only: bool = True, engine: Optional[Engine] = None
) -> Optional[Dict[str, Any]]:
    if not ad_store_enabled():
        return None
    try:
        ensure_ad_tables(engine)
        eng = engine or get_engine()
        sql = "SELECT package_json FROM ad_packages"
        if ready_only:
            sql += " WHERE status = 'ready'"
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with eng.connect() as conn:
            row = conn.execute(text(sql)).mappings().first()
        if not row:
            return None
        pkg = _json_load(row["package_json"])
        return pkg if isinstance(pkg, dict) else None
    except Exception as exc:
        logger.warning("load_latest_ad_package_db failed: %s", exc)
        return None


def list_ad_package_ids_db(*, engine: Optional[Engine] = None) -> List[str]:
    if not ad_store_enabled():
        return []
    try:
        ensure_ad_tables(engine)
        eng = engine or get_engine()
        with eng.connect() as conn:
            rows = conn.execute(
                text("SELECT id FROM ad_packages ORDER BY updated_at DESC")
            ).fetchall()
        return [str(r[0]) for r in rows]
    except Exception as exc:
        logger.warning("list_ad_package_ids_db failed: %s", exc)
        return []


def get_poster_bytes_db(
    ad_id: str, *, engine: Optional[Engine] = None
) -> Optional[bytes]:
    if not ad_store_enabled():
        return None
    try:
        ensure_ad_tables(engine)
        eng = engine or get_engine()
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT poster_png FROM ad_packages WHERE id=:id"),
                {"id": ad_id},
            ).mappings().first()
        if not row or row["poster_png"] is None:
            return None
        blob = row["poster_png"]
        if isinstance(blob, memoryview):
            return blob.tobytes()
        if isinstance(blob, bytes):
            return blob
        return bytes(blob)
    except Exception as exc:
        logger.warning("get_poster_bytes_db failed: %s", exc)
        return None


def get_social_json_db(
    ad_id: str, *, engine: Optional[Engine] = None
) -> Optional[Dict[str, Any]]:
    """讀 ad_packages.social_json；若空則從 package_json.copy.ai 還原。"""
    if not ad_store_enabled() or not ad_id:
        return None
    try:
        ensure_ad_tables(engine)
        eng = engine or get_engine()
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT social_json, package_json FROM ad_packages WHERE id=:id"
                ),
                {"id": ad_id},
            ).mappings().first()
        if not row:
            return None
        social = _json_load(row["social_json"])
        if isinstance(social, dict) and (
            social.get("featured") or social.get("post_text") or social.get("title")
        ):
            return social
        pkg = _json_load(row["package_json"])
        if isinstance(pkg, dict):
            ai = (pkg.get("copy") or {}).get("ai")
            if isinstance(ai, dict) and (
                ai.get("featured") or ai.get("post_text") or ai.get("title")
            ):
                return ai
        return None
    except Exception as exc:
        logger.warning("get_social_json_db failed: %s", exc)
        return None


def upsert_archive(
    racing_date: str,
    course: str,
    kind: str,
    payload: Dict[str, Any],
    *,
    batch_id: Optional[str] = None,
    engine: Optional[Engine] = None,
) -> Dict[str, Any]:
    if not ad_store_enabled():
        return {"ok": False, "skipped": True, "reason": "AD_STORE_ENABLED=false"}
    d = str(racing_date or "")[:10]
    c = str(course or "").upper()
    k = str(kind or "").strip()
    if not d or not c or not k:
        return {"ok": False, "error": "racing_date/course/kind required"}
    ensure_ad_tables(engine)
    eng = engine or get_engine()
    bid = batch_id
    if not bid:
        meeting = payload.get("meeting") if isinstance(payload.get("meeting"), dict) else {}
        bid = meeting.get("batch_id") or payload.get("batch_id")
    params = {
        "racing_date": d,
        "course": c,
        "kind": k,
        "batch_id": str(bid) if bid else None,
        "payload_json": _json_dump(payload),
    }
    with eng.begin() as conn:
        if USE_SQLITE:
            conn.execute(
                text(
                    """
                    INSERT INTO ad_archives (
                        racing_date, course, kind, batch_id, payload_json, created_at, updated_at
                    ) VALUES (
                        :racing_date, :course, :kind, :batch_id, :payload_json,
                        datetime('now'), datetime('now')
                    )
                    ON CONFLICT(racing_date, course, kind) DO UPDATE SET
                        batch_id=excluded.batch_id,
                        payload_json=excluded.payload_json,
                        updated_at=datetime('now')
                    """
                ),
                params,
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO ad_archives (
                        racing_date, course, kind, batch_id, payload_json
                    ) VALUES (
                        CAST(:racing_date AS DATE), :course, :kind, :batch_id,
                        CAST(:payload_json AS JSONB)
                    )
                    ON CONFLICT (racing_date, course, kind) DO UPDATE SET
                        batch_id = EXCLUDED.batch_id,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = NOW()
                    """
                ),
                params,
            )
    return {"ok": True, "racing_date": d, "course": c, "kind": k}


def load_archive_latest_db(
    racing_date: str,
    course: str,
    kind: str,
    *,
    engine: Optional[Engine] = None,
) -> Dict[str, Any]:
    if not ad_store_enabled():
        return {}
    try:
        ensure_ad_tables(engine)
        eng = engine or get_engine()
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT payload_json FROM ad_archives
                    WHERE racing_date = :d AND course = :c AND kind = :k
                    """
                    if USE_SQLITE
                    else """
                    SELECT payload_json FROM ad_archives
                    WHERE racing_date = CAST(:d AS DATE) AND course = :c AND kind = :k
                    """
                ),
                {"d": str(racing_date)[:10], "c": str(course).upper(), "k": kind},
            ).mappings().first()
        if not row:
            return {}
        data = _json_load(row["payload_json"])
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("load_archive_latest_db failed: %s", exc)
        return {}


def job_done_for_batch_db(
    racing_date: str,
    course: str,
    kind: str,
    batch_id: str,
    *,
    engine: Optional[Engine] = None,
) -> bool:
    if not batch_id:
        return False
    data = load_archive_latest_db(racing_date, course, kind, engine=engine)
    if not data:
        return False
    meeting = data.get("meeting") if isinstance(data.get("meeting"), dict) else {}
    bid = meeting.get("batch_id") or data.get("batch_id") or ""
    return str(bid) == str(batch_id)


def set_batch_ad_status(
    batch_id: str, status: str, *, engine: Optional[Engine] = None
) -> None:
    if not batch_id:
        return
    try:
        ensure_ad_tables(engine)
        eng = engine or get_engine()
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE prediction_snapshot_batches SET ad_status=:s WHERE batch_id=:b"
                ),
                {"s": status, "b": batch_id},
            )
    except Exception as exc:
        logger.warning("set_batch_ad_status failed: %s", exc)


def get_batch_ad_status(
    batch_id: str, *, engine: Optional[Engine] = None
) -> Optional[str]:
    if not batch_id:
        return None
    try:
        ensure_ad_tables(engine)
        eng = engine or get_engine()
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT ad_status FROM prediction_snapshot_batches WHERE batch_id=:b"
                ),
                {"b": batch_id},
            ).first()
        return str(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def hydrate_package_to_disk(
    ad_id: str,
    output_root,
    *,
    engine: Optional[Engine] = None,
) -> Dict[str, Any]:
    """把 DB 內 package／海報／AI 文案寫回本機 ad_output，方便舊 UI 讀檔。"""
    from pathlib import Path

    root = Path(output_root)
    pkg = load_ad_package_db(ad_id, engine=engine)
    if not pkg:
        return {"ok": False, "error": "not in db"}
    packages = root / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    (packages / f"{ad_id}.json").write_text(
        json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    blob = get_poster_bytes_db(ad_id, engine=engine)
    if blob:
        (packages / f"{ad_id}.png").write_bytes(blob)
        fused = root / "fused.png"
        if not fused.is_file():
            fused.write_bytes(blob)
    social = get_social_json_db(ad_id, engine=engine)
    if social:
        (root / "social_copy.json").write_text(
            json.dumps(social, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if pkg.get("status") == "ready":
        (packages / "_latest_id.txt").write_text(ad_id, encoding="utf-8")
    return {
        "ok": True,
        "id": ad_id,
        "bytes": len(blob or b""),
        "has_social": bool(social),
    }
