"""
防止／修復廣告包海報「日期張冠李戴」。

典型故障：package id／meeting.date 已係 2026-10-04，但 poster PNG
bytes 同另一個賽日（如 2026-10-01）完全相同——上游誤把舊 fused.png ingest。

本模組：
1. ingest 時拒絕「同另一賽日海報 hash 完全一樣」嘅推送
2. Ad API 啟動時掃描 DB／碟，重畫被 clone 嘅海報並覆寫
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def poster_sha256(poster_png: bytes) -> str:
    return hashlib.sha256(poster_png or b"").hexdigest()


def _meeting_date_course(pkg: Dict[str, Any]) -> Tuple[str, str]:
    meeting = pkg.get("meeting") if isinstance(pkg.get("meeting"), dict) else {}
    meta = pkg.get("meta") if isinstance(pkg.get("meta"), dict) else {}
    d = (
        str(meeting.get("date") or meeting.get("racing_date") or meta.get("racing_date") or "")
        [:10]
    )
    c = str(
        meeting.get("venue_code")
        or meeting.get("course")
        or meta.get("course")
        or ""
    ).upper()
    # id 後備：2026-10-04-st-day / 2026-10-04-st-day-post
    if (not d or not c) and pkg.get("id"):
        parts = str(pkg["id"]).split("-")
        if len(parts) >= 4:
            d = d or f"{parts[0]}-{parts[1]}-{parts[2]}"
            c = c or str(parts[3] or "").upper()
    return d, c


def payloads_from_package_tips(pkg: Dict[str, Any]) -> List[Any]:
    """用 package.tips 組 RaceAdPayload（只夠重畫海報，唔依賴 snapshot）。"""
    from ad_poster import PickItem, RaceAdPayload

    d, c = _meeting_date_course(pkg)
    if not d or not c:
        raise ValueError("package missing meeting date/course")
    tips = list(pkg.get("tips") or [])
    if not tips:
        raise ValueError("package tips empty — cannot rebuild poster")

    payloads: List[RaceAdPayload] = []
    for tip in tips:
        if not isinstance(tip, dict):
            continue
        try:
            race_no = int(tip.get("race") or tip.get("race_no") or tip.get("race_num") or 0)
        except (TypeError, ValueError):
            race_no = 0
        if race_no <= 0:
            continue
        horses = list(tip.get("horses") or [])
        picks: List[PickItem] = []
        for i, h in enumerate(horses):
            if not isinstance(h, dict):
                continue
            try:
                hno = int(h.get("no") or h.get("horse_no") or 0)
            except (TypeError, ValueError):
                hno = 0
            name = str(h.get("name") or h.get("horse_name") or "").strip()
            if not hno or not name:
                continue
            picks.append(
                PickItem(
                    horse_no=hno,
                    horse_name=name,
                    share_pct=max(8.0, 28.0 - i * 5.0),
                    tag="爭勝" if i == 0 else "推介",
                )
            )
        if not picks:
            continue
        rid = f"{d.replace('-', '')}{c}{race_no:02d}"
        payloads.append(
            RaceAdPayload(
                race_id=rid,
                racing_date=d,
                course=c,
                race_num=race_no,
                race_name="",
                track="fused",
                model_picks=list(picks),
                ai_picks=list(picks),
                fused_picks=list(picks),
                fused_fallback_model_only=True,
            )
        )
    if not payloads:
        raise ValueError("no valid tip races for poster rebuild")
    return payloads


def regenerate_poster_png_from_package(pkg: Dict[str, Any]) -> bytes:
    """按 package meeting + tips 重畫 fused 海報，回傳 PNG bytes。"""
    from ad_poster import lookup_meeting_session, render_meeting_poster

    d, c = _meeting_date_course(pkg)
    payloads = payloads_from_package_tips(pkg)
    meeting = pkg.get("meeting") if isinstance(pkg.get("meeting"), dict) else {}
    session = meeting.get("session")
    is_day = None
    if session in ("日", "夜"):
        is_day = session == "日"
    else:
        fx = lookup_meeting_session(d, c)
        session = fx.get("session") or ("日" if c == "ST" else "夜")
        if "is_day_meeting" in fx:
            is_day = fx.get("is_day_meeting")
        else:
            is_day = c == "ST"

    with tempfile.TemporaryDirectory(prefix="ad_poster_guard_") as tmp:
        out = Path(tmp) / "fused.png"
        meta = render_meeting_poster(
            payloads,
            track="fused",
            out_path=out,
            session=str(session) if session else None,
            is_day_meeting=is_day,
        )
        if not out.is_file():
            raise RuntimeError(f"render_meeting_poster produced no file: {meta}")
        return out.read_bytes()


def _iter_ready_packages(output_root: Path) -> List[Dict[str, Any]]:
    from ad_package import list_ad_package_ids, load_ad_package

    out: List[Dict[str, Any]] = []
    try:
        from ad_store import list_ad_package_ids_db, load_ad_package_db

        ids = list(list_ad_package_ids_db() or []) or list(list_ad_package_ids(output_root) or [])
        for ad_id in ids:
            pkg = None
            try:
                pkg = load_ad_package_db(str(ad_id))
            except Exception:
                pkg = None
            if not pkg:
                try:
                    pkg = load_ad_package(str(ad_id), output_root)
                except Exception:
                    pkg = None
            if pkg and str(pkg.get("status") or "") == "ready":
                out.append(pkg)
    except Exception:
        for ad_id in list_ad_package_ids(output_root) or []:
            try:
                pkg = load_ad_package(str(ad_id), output_root)
            except Exception:
                continue
            if pkg and str(pkg.get("status") or "") == "ready":
                out.append(pkg)
    return out


def _poster_bytes_for_pkg(pkg: Dict[str, Any], output_root: Path) -> Optional[bytes]:
    ad_id = str(pkg.get("id") or "")
    if not ad_id:
        return None
    try:
        from ad_store import get_poster_bytes_db

        blob = get_poster_bytes_db(ad_id)
        if blob:
            return bytes(blob)
    except Exception:
        pass
    from ad_package import package_paths

    paths = package_paths(ad_id, output_root)
    if paths["poster"].is_file():
        return paths["poster"].read_bytes()
    fused = output_root / "fused.png"
    # 只喺 latest 先用 fused 兜底，避免誤判
    if ad_id == str((pkg.get("id") or "")) and fused.is_file():
        latest = None
        try:
            from ad_package import load_latest_ad_package

            latest = load_latest_ad_package(output_root, ready_only=True)
        except Exception:
            latest = None
        if latest and str(latest.get("id") or "") == ad_id:
            return fused.read_bytes()
    return None


def find_cloned_poster_groups(
    packages: Sequence[Dict[str, Any]],
    *,
    output_root: Path,
) -> List[Dict[str, Any]]:
    """
    回傳 clone 組：同一 poster sha256 對應多個唔同 meeting.date。
    每組 `reparable` = 除咗最早建立嗰個之外、需要重畫嘅 package。
    """
    by_hash: Dict[str, List[Tuple[Dict[str, Any], bytes]]] = {}
    for pkg in packages:
        blob = _poster_bytes_for_pkg(pkg, output_root)
        if not blob:
            continue
        h = poster_sha256(blob)
        by_hash.setdefault(h, []).append((pkg, blob))

    groups: List[Dict[str, Any]] = []
    for h, items in by_hash.items():
        dates = {_meeting_date_course(p)[0] for p, _ in items if _meeting_date_course(p)[0]}
        if len(dates) <= 1:
            continue
        items_sorted = sorted(
            items,
            key=lambda it: str(it[0].get("created_at") or it[0].get("updated_at") or ""),
        )
        source_pkg = items_sorted[0][0]
        reparable = [p for p, _ in items_sorted[1:]]
        groups.append(
            {
                "sha256": h,
                "dates": sorted(dates),
                "source_id": source_pkg.get("id"),
                "source_date": _meeting_date_course(source_pkg)[0],
                "clone_ids": [p.get("id") for p in reparable],
                "reparable": reparable,
            }
        )
    return groups


def assert_poster_not_foreign_clone(
    poster_png: bytes,
    *,
    meeting_date: str,
    output_root: Optional[Path] = None,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    ingest 閘：若 poster bytes 同現有另一個賽日海報完全一樣 → 拒絕（除非 force）。
    回傳 None 表示通過；有問題時 raise ValueError。
    """
    if force or not poster_png:
        return None
    d = str(meeting_date or "")[:10]
    if not d:
        return None
    from ad_poster import default_output_dir

    root = Path(output_root) if output_root else default_output_dir()
    h = poster_sha256(poster_png)
    for pkg in _iter_ready_packages(root):
        od, _ = _meeting_date_course(pkg)
        if not od or od == d:
            continue
        other = _poster_bytes_for_pkg(pkg, root)
        if other and poster_sha256(other) == h:
            raise ValueError(
                f"poster bytes identical to {pkg.get('id')} ({od}); "
                f"refusing ingest for meeting {d} (set force=true to override)"
            )
    return None


def repair_package_poster(
    pkg: Dict[str, Any],
    *,
    output_root: Path,
    notify: bool = False,
) -> Dict[str, Any]:
    """重畫單一 package 海報並覆寫本機／DB（保留 AI 文案）。"""
    from ad_package import absolute_poster_url, package_paths, save_ad_package

    ad_id = str(pkg.get("id") or "")
    d, c = _meeting_date_course(pkg)
    if not ad_id or not d:
        return {"ok": False, "error": "missing id/date"}

    try:
        new_png = regenerate_poster_png_from_package(pkg)
    except Exception as exc:
        logger.exception("regenerate poster failed id=%s", ad_id)
        return {"ok": False, "id": ad_id, "error": str(exc)}

    old = _poster_bytes_for_pkg(pkg, output_root) or b""
    if old and poster_sha256(old) == poster_sha256(new_png):
        return {"ok": True, "id": ad_id, "skipped": True, "reason": "poster_unchanged"}

    paths = package_paths(ad_id, output_root)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["poster"].write_bytes(new_png)
    try:
        (output_root / "fused.png").write_bytes(new_png)
    except Exception:
        pass

    assets = dict(pkg.get("assets") or {})
    assets["poster_url"] = absolute_poster_url(ad_id)
    assets["poster_path"] = str(paths["poster"])
    pkg = dict(pkg)
    pkg["assets"] = assets
    meta = dict(pkg.get("meta") or {})
    meta["poster_repaired"] = True
    meta["poster_repair_reason"] = "cloned_bytes_other_meeting"
    meta["poster_sha256"] = poster_sha256(new_png)
    pkg["meta"] = meta

    save_ad_package(pkg, output_root, push_remote=False, force=True)
    if notify:
        try:
            from ad_package import dispatch_ad_webhook

            pkg["webhook"] = dispatch_ad_webhook(pkg)
            save_ad_package(pkg, output_root, push_remote=False, force=True)
        except Exception as exc:
            logger.warning("repair webhook failed id=%s: %s", ad_id, exc)

    return {
        "ok": True,
        "id": ad_id,
        "meeting_date": d,
        "course": c,
        "old_sha256": poster_sha256(old) if old else None,
        "new_sha256": poster_sha256(new_png),
        "bytes": len(new_png),
    }


def repair_cloned_ad_posters(
    *,
    output_root: Optional[Path] = None,
    notify: bool = False,
) -> Dict[str, Any]:
    """
    掃描 ready 包：同一海報 bytes 掛喺多個賽日 → 保留最早嗰個，其餘按 tips 重畫。
    可用 AD_POSTER_CLONE_REPAIR=false 關閉（預設 true）。
    """
    enabled = (os.getenv("AD_POSTER_CLONE_REPAIR", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    from ad_poster import default_output_dir

    root = Path(output_root) if output_root else default_output_dir()
    if not enabled:
        return {"ok": True, "skipped": True, "reason": "AD_POSTER_CLONE_REPAIR=false"}

    packages = _iter_ready_packages(root)
    groups = find_cloned_poster_groups(packages, output_root=root)
    repaired: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for g in groups:
        for pkg in g.get("reparable") or []:
            result = repair_package_poster(pkg, output_root=root, notify=notify)
            if result.get("ok"):
                repaired.append(result)
            else:
                errors.append(result)

    return {
        "ok": not errors,
        "groups": [
            {
                "sha256": g["sha256"],
                "dates": g["dates"],
                "source_id": g["source_id"],
                "clone_ids": g["clone_ids"],
            }
            for g in groups
        ],
        "repaired": repaired,
        "errors": errors,
        "scanned": len(packages),
    }
