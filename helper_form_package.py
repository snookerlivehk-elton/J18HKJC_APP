"""
賽前歷史戰績包：三幅 PNG + 結構化 JSON + webhook（對齊廣告包下游模式）。

id（幂等）：{YYYY-MM-DD}-{st|hv}-helper-form
status=ready：日期核對通過且三幅（或依 layout）圖齊備。
探測到排位／賽日資料更新後可呼叫 publish_helper_form_package()。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from helper_form_client import resolve_latest_meeting
from helper_form_poster import (
    default_output_dir,
    generate_helper_form_parts,
)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def helper_form_output_root(output_root: Optional[Path] = None) -> Path:
    if output_root is not None:
        return Path(output_root)
    custom = (os.getenv("AD_OUTPUT_DIR") or "").strip()
    base = Path(custom) if custom else default_output_dir().parent  # ad_output/
    return Path(base) / "helper_form"


def packages_dir(output_root: Optional[Path] = None) -> Path:
    d = helper_form_output_root(output_root) / "packages"
    d.mkdir(parents=True, exist_ok=True)
    return d


def package_id(racing_date: str, course: str) -> str:
    d = str(racing_date or "")[:10]
    c = str(course or "").strip().lower() or "st"
    if c not in {"st", "hv"}:
        c = c[:2] if c else "st"
    return f"{d}-{c}-helper-form"


def package_paths(pkg_id: str, output_root: Optional[Path] = None) -> Dict[str, Path]:
    root = helper_form_output_root(output_root)
    return {
        "root": root,
        "json": packages_dir(output_root) / f"{pkg_id}.json",
        "images_dir": root / "images" / pkg_id,
    }


def _public_base() -> str:
    raw = (
        os.getenv("AD_API_PUBLIC_BASE")
        or os.getenv("AD_API_BASE_URL")
        or ""
    ).strip().rstrip("/")
    if raw and not raw.startswith("http"):
        raw = "https://" + raw
    return raw


def _image_public_url(pkg_id: str, index: int) -> str:
    base = _public_base()
    path = f"/v1/helper-form/{pkg_id}/image/{index}"
    return f"{base}{path}" if base else path


def public_payload(pkg: Dict[str, Any]) -> Dict[str, Any]:
    """下游機械人／AI 可見 schema（不含本機路徑）。"""
    assets = dict(pkg.get("assets") or {})
    images = []
    for im in list(assets.get("images") or []):
        images.append(
            {
                "index": im.get("index"),
                "race_nums": im.get("race_nums"),
                "n_races": im.get("n_races"),
                "url": im.get("url"),
            }
        )
    return {
        "id": pkg.get("id"),
        "status": pkg.get("status"),
        "purpose": "helper_form",
        "kind": "pre_race_form_history",
        "meeting": pkg.get("meeting") or {},
        "layout": pkg.get("layout") or [],
        "n_races": pkg.get("n_races"),
        "assets": {"images": images},
        "guard": pkg.get("guard") or {},
        "created_at": pkg.get("created_at"),
        "updated_at": pkg.get("updated_at"),
        "publish": {
            "hint": "下載 assets.images[].url 三幅賽前歷史戰績圖；以 id 做幂等。",
            "image_count": len(images),
        },
    }


def save_package(pkg: Dict[str, Any], output_root: Optional[Path] = None) -> Path:
    pkg_id = str(pkg.get("id") or "")
    path = package_paths(pkg_id, output_root)["json"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_package(pkg_id: str, output_root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = package_paths(pkg_id, output_root)["json"]
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_package_ids(output_root: Optional[Path] = None) -> List[str]:
    ids = [p.stem for p in packages_dir(output_root).glob("*.json")]
    return sorted(ids, reverse=True)


def load_latest_package(
    output_root: Optional[Path] = None,
    *,
    ready_only: bool = True,
) -> Optional[Dict[str, Any]]:
    for pkg_id in list_package_ids(output_root):
        pkg = load_package(pkg_id, output_root)
        if not pkg:
            continue
        if ready_only and str(pkg.get("status") or "") != "ready":
            continue
        return pkg
    return None


def image_file_path(
    pkg_id: str,
    index: int,
    output_root: Optional[Path] = None,
) -> Optional[Path]:
    pkg = load_package(pkg_id, output_root)
    if not pkg:
        return None
    for im in (pkg.get("assets") or {}).get("images") or []:
        if int(im.get("index") or 0) == int(index):
            local = im.get("path")
            if local and Path(local).is_file():
                return Path(local)
            # fallback naming
            p = package_paths(pkg_id, output_root)["images_dir"] / f"helper_form_{index}.png"
            return p if p.is_file() else None
    p = package_paths(pkg_id, output_root)["images_dir"] / f"helper_form_{index}.png"
    return p if p.is_file() else None


def _webhook_headers(pkg_id: str) -> Dict[str, str]:
    secret = (os.getenv("GROK_BOT_WEBHOOK_SECRET") or "").strip()
    secret_header = (
        os.getenv("GROK_BOT_WEBHOOK_SECRET_HEADER") or "X-Webhook-Secret"
    ).strip()
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": pkg_id,
        "User-Agent": "J18-HelperForm/1.0",
        "X-J18-Purpose": "helper_form",
    }
    if secret:
        headers[secret_header] = secret
    return headers


def dispatch_helper_form_webhook(
    payload: Dict[str, Any],
    *,
    url: Optional[str] = None,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    if str(payload.get("status") or "") != "ready":
        return {"ok": False, "skipped": True, "reason": f"status not ready ({payload.get('status')})"}
    target = (
        url
        or os.getenv("HELPER_FORM_WEBHOOK_URL")
        or os.getenv("GROK_BOT_WEBHOOK_URL")
        or ""
    ).strip()
    if not target:
        return {
            "ok": False,
            "skipped": True,
            "reason": "HELPER_FORM_WEBHOOK_URL / GROK_BOT_WEBHOOK_URL not set",
        }

    pkg_id = str(payload.get("id") or "")
    headers = _webhook_headers(pkg_id)
    body = json.dumps(public_payload(payload), ensure_ascii=False).encode("utf-8")
    attempts: List[Dict[str, Any]] = []
    last_error = ""

    try:
        import httpx
    except ImportError:
        return {"ok": False, "error": "httpx not installed"}

    for i in range(max(1, int(max_attempts))):
        t0 = time.time()
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(target, content=body, headers=headers)
            info = {
                "attempt": i + 1,
                "status_code": resp.status_code,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }
            attempts.append(info)
            if 200 <= resp.status_code < 300:
                logger.info("helper-form webhook ok id=%s attempt=%s", pkg_id, i + 1)
                return {"ok": True, "attempts": attempts, "url": target}
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as e:
            last_error = str(e)
            attempts.append({"attempt": i + 1, "error": last_error})
        if i + 1 < max_attempts:
            time.sleep(2 ** i)

    return {"ok": False, "error": last_error, "attempts": attempts, "url": target}


def publish_helper_form_package(
    *,
    racing_date: Optional[str] = None,
    course: Optional[str] = None,
    output_root: Optional[Path] = None,
    notify: bool = True,
    raw: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    抓 Helper API → 核對最新賽日 → 產三幅圖 → 寫 package JSON → 可選 webhook。
    若已有同 id ready 且 force=False，可跳過重產（仍回傳現有包）。
    """
    latest = resolve_latest_meeting(racing_date, course)
    if not racing_date:
        if not latest.get("ok"):
            return {
                "ok": False,
                "error": latest.get("error") or "無法取得最新賽馬日",
            }
        racing_date = str(latest["racing_date"])[:10]
    if not course and latest.get("ok"):
        course = str(latest.get("course") or "").upper() or None

    course_u = str(course or "").upper()
    pkg_id = package_id(racing_date, course_u or "ST")
    paths = package_paths(pkg_id, output_root)
    existing = load_package(pkg_id, output_root)
    if (
        existing
        and str(existing.get("status") or "") == "ready"
        and not force
        and (existing.get("assets") or {}).get("images")
    ):
        return {
            "ok": True,
            "id": pkg_id,
            "status": "ready",
            "skipped": True,
            "reason": "already ready",
            "package": existing,
        }

    images_dir = paths["images_dir"]
    images_dir.mkdir(parents=True, exist_ok=True)

    gen = generate_helper_form_parts(
        out_dir=images_dir,
        expected_date=str(racing_date)[:10],
        expected_course=course_u or None,
        require_course=bool(course_u),
        raw=raw,
        render_even_if_stale=False,
        apply_logo=False,
        file_prefix="helper_form",
    )
    if not gen.get("ok"):
        pkg = {
            "id": pkg_id,
            "status": "error",
            "purpose": "helper_form",
            "kind": "pre_race_form_history",
            "meeting": {
                "date": str(racing_date)[:10],
                "course": course_u,
            },
            "error": gen.get("error"),
            "guard": gen.get("guard") or {},
            "created_at": (existing or {}).get("created_at") or _utc_now(),
            "updated_at": _utc_now(),
        }
        save_package(pkg, output_root)
        return {"ok": False, "id": pkg_id, "status": "error", "error": gen.get("error"), "package": pkg}

    images_out = []
    for part in gen.get("parts") or []:
        idx = int(part.get("index") or 0)
        src = Path(part.get("path") or "")
        dest = images_dir / f"helper_form_{idx}.png"
        if src.is_file() and src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        elif not dest.is_file() and src.is_file():
            dest.write_bytes(src.read_bytes())
        images_out.append(
            {
                "index": idx,
                "race_nums": part.get("race_nums"),
                "n_races": part.get("n_races"),
                "path": str(dest),
                "url": _image_public_url(pkg_id, idx),
                "size": part.get("size"),
            }
        )

    status = "ready" if images_out else "error"
    pkg = {
        "id": pkg_id,
        "status": status,
        "purpose": "helper_form",
        "kind": "pre_race_form_history",
        "meeting": {
            "date": gen.get("racing_date") or str(racing_date)[:10],
            "course": gen.get("course") or course_u,
        },
        "layout": gen.get("layout") or [],
        "n_races": gen.get("n_races") or 0,
        "assets": {"images": images_out},
        "guard": gen.get("guard") or {},
        "created_at": (existing or {}).get("created_at") or _utc_now(),
        "updated_at": _utc_now(),
    }
    save_package(pkg, output_root)

    webhook = None
    if notify and status == "ready":
        webhook = dispatch_helper_form_webhook(pkg)
        pkg["webhook"] = webhook
        save_package(pkg, output_root)

    return {
        "ok": status == "ready",
        "id": pkg_id,
        "status": status,
        "package": pkg,
        "webhook": webhook,
    }


def ensure_helper_form_for_meeting(
    racing_date: str,
    course: str,
    *,
    notify: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    """供 meeting_tick：排位更新後確保戰績三幅已產出。"""
    try:
        return publish_helper_form_package(
            racing_date=str(racing_date)[:10],
            course=str(course or "").upper(),
            notify=notify,
            force=force,
        )
    except Exception as exc:
        logger.exception("ensure_helper_form_for_meeting failed")
        return {"ok": False, "error": str(exc)}
