"""
賽前預測廣告包：結構化 JSON + 海報資產 + webhook 通知。

幂等 id：{YYYY-MM-DD}-{hv|st}-{day|night}
寫入 ad_output/packages/{id}.json 與 {id}.png
status=ready（海報 PNG + AI 精選文案）後 POST 去 GROK_BOT_WEBHOOK_URL（指數退避重試 ≥3 次）
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ad_poster import (
    WEEKDAY_ZH,
    _venue_label,
    default_output_dir,
    generate_ads_from_snapshot_batch,
    latest_paths,
    load_copy_json,
    lookup_meeting_session,
    resolve_poster_theme,
)

logger = logging.getLogger(__name__)

HK_TZ = timezone(timedelta(hours=8))
PACKAGES_SUBDIR = "packages"
LATEST_ID_NAME = "_latest_id.txt"
DEFAULT_HASHTAGS = ["#J18", "#賽馬", "#賽前預測"]
DEFAULT_CTA = "想追臨場心水？而家就登入 J18.hk"
DEFAULT_SITE = "https://J18.hk"
DEFAULT_FB_PAGE = "https://www.facebook.com/j18hk"

# ready 需同時有海報 + AI 精選文案（Grok Bot 輪詢用）；可設 AD_PACKAGE_REQUIRE_AI_SOCIAL=false 關閉
def require_ai_social() -> bool:
    return (os.getenv("AD_PACKAGE_REQUIRE_AI_SOCIAL", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def ai_social_payload(output_root: Path) -> Optional[Dict[str, Any]]:
    """從 social_copy.json 組 Grok 可用的 AI 精選評述區塊；未就緒回傳 None。"""
    try:
        from ad_llm_copy import format_social_post_text, load_social_copy
    except Exception:
        return None
    social = load_social_copy(Path(output_root))
    if not social:
        return None
    featured = list(social.get("featured") or [])
    post_text = str(social.get("post_text") or "").strip()
    if not post_text:
        try:
            post_text = format_social_post_text(social).strip()
        except Exception:
            post_text = ""
    if not featured and not post_text:
        return None
    meeting = dict(social.get("meeting") or {})
    return {
        "title": str(social.get("title") or "").strip(),
        "subtitle": str(social.get("subtitle") or "").strip(),
        "featured": featured,
        "post_text": post_text,
        "hashtags": list(social.get("hashtags") or []),
        "source": social.get("source"),
        "tone": social.get("tone") or meeting.get("tone"),
        "generated_at": meeting.get("generated_at") or social.get("generated_at"),
    }



def _hk_now_iso() -> str:
    return datetime.now(HK_TZ).isoformat(timespec="seconds")


def packages_dir(output_root: Optional[Path] = None) -> Path:
    root = Path(output_root) if output_root else default_output_dir()
    d = root / PACKAGES_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def public_base_url() -> str:
    return (os.getenv("AD_API_PUBLIC_BASE") or os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")


def stable_ad_id(
    racing_date: str,
    course: str,
    *,
    session: Optional[str] = None,
    is_day_meeting: Optional[bool] = None,
) -> str:
    """幂等 id，例如 2026-07-15-hv-night。"""
    d = str(racing_date or "")[:10]
    c = str(course or "").upper()
    theme = resolve_poster_theme(course=c, session=session, is_day_meeting=is_day_meeting)
    session_key = "day" if theme == "day" else "night"
    venue = "hv" if c == "HV" else ("st" if c == "ST" else (c.lower() or "xx"))
    return f"{d}-{venue}-{session_key}"


def _session_zh(theme: str) -> str:
    return "日" if theme == "day" else "夜"


def _weekday_zh(racing_date: str) -> str:
    try:
        dt = datetime.strptime(str(racing_date)[:10], "%Y-%m-%d")
        return WEEKDAY_ZH[dt.weekday()]
    except Exception:
        return ""


def _tips_from_races(races: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tips: List[Dict[str, Any]] = []
    for r in races:
        rn = r.get("race_no")
        try:
            race_n = int(rn) if rn is not None and str(rn).isdigit() else None
        except Exception:
            race_n = None
        if race_n is None:
            continue
        horses: List[Dict[str, Any]] = []
        for p in list(r.get("fused_picks") or [])[:4]:
            try:
                no = int(p.get("horse_no"))
            except Exception:
                continue
            horses.append({"no": no, "name": str(p.get("horse_name") or "").strip()})
        tips.append({"race": race_n, "horses": horses})
    tips.sort(key=lambda x: x["race"])
    return tips


def _build_intro(meeting: Dict[str, Any], tips: Sequence[Dict[str, Any]]) -> str:
    return (
        f"{meeting.get('date', '')} {meeting.get('weekday', '')}"
        f"{meeting.get('venue', '')}{meeting.get('session', '')}賽共 {len(tips)} 場，"
        f"J18 綜合推介已出爐——開賽前或會更新，請以網站最新版為準。"
    )


def _build_facebook_copy(
    *,
    meeting: Dict[str, Any],
    tips: Sequence[Dict[str, Any]],
    intro: str,
    cta: str,
    hashtags: Sequence[str],
    fused_copy: str = "",
) -> str:
    lines = [
        (
            f"【J18 賽前預測】{meeting.get('date', '')} {meeting.get('weekday', '')} "
            f"{meeting.get('venue', '')}{meeting.get('session', '')}賽"
        ),
        "",
        intro,
        "",
    ]
    for t in tips:
        horses = t.get("horses") or []
        body = (
            "、".join(f"{h['no']} {h['name']}" for h in horses) if horses else "暫無推介"
        )
        lines.append(f"第{t.get('race')}場：{body}")
    lines.extend(
        [
            "",
            "⚠️ 預測或會於開賽前變更，請以 J18.hk 最新版本為準。",
            cta,
            "",
            " ".join(hashtags),
        ]
    )
    fc = str(fused_copy or "").strip()
    if fc and len(fc) < 800:
        lines.extend(["", "——", fc])
    return "\n".join(lines)


def _build_short_copy(
    meeting: Dict[str, Any], tips: Sequence[Dict[str, Any]], cta: str
) -> str:
    return (
        f"【J18】{meeting.get('date', '')} {meeting.get('venue', '')}"
        f"{meeting.get('session', '')}賽 {len(tips)} 場綜合推介已更新！{cta}"
    )


def package_paths(ad_id: str, output_root: Optional[Path] = None) -> Dict[str, Path]:
    root = packages_dir(output_root)
    return {
        "root": root,
        "json": root / f"{ad_id}.json",
        "poster": root / f"{ad_id}.png",
        "latest_id": root / LATEST_ID_NAME,
    }


def load_ad_package(
    ad_id: str, output_root: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    p = package_paths(ad_id, output_root)["json"]
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_latest_ad_package(
    output_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    lid = package_paths("_", output_root)["latest_id"]
    if lid.is_file():
        ad_id = lid.read_text(encoding="utf-8").strip()
        if ad_id:
            pkg = load_ad_package(ad_id, output_root)
            if pkg and pkg.get("status") == "ready":
                return pkg
    root = packages_dir(output_root)
    ranked: List[Tuple[float, Path]] = []
    for p in root.glob("*.json"):
        try:
            ranked.append((p.stat().st_mtime, p))
        except OSError:
            continue
    ranked.sort(reverse=True)
    for _, p in ranked:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") == "ready":
            return data
    return None


def save_ad_package(
    payload: Dict[str, Any], output_root: Optional[Path] = None
) -> Path:
    ad_id = str(payload.get("id") or "")
    if not ad_id:
        raise ValueError("ad package missing id")
    paths = package_paths(ad_id, output_root)
    paths["json"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if payload.get("status") == "ready":
        paths["latest_id"].write_text(ad_id, encoding="utf-8")
    return paths["json"]


def public_payload(pkg: Dict[str, Any]) -> Dict[str, Any]:
    """對外回傳：對齊公開 schema，去掉本機路徑／內部欄位。"""
    keys = (
        "id",
        "created_at",
        "status",
        "meeting",
        "intro",
        "tips",
        "copy",
        "assets",
        "publish",
        "links",
    )
    out: Dict[str, Any] = {}
    for k in keys:
        if k in pkg:
            out[k] = json.loads(json.dumps(pkg[k]))
    assets = dict(out.get("assets") or {})
    assets.pop("poster_path", None)
    out["assets"] = assets
    return out


def build_ad_package_from_copy(
    copy_data: Dict[str, Any],
    *,
    output_root: Optional[Path] = None,
    poster_src: Optional[Path] = None,
    session: Optional[str] = None,
    is_day_meeting: Optional[bool] = None,
    notify: bool = False,
) -> Dict[str, Any]:
    meeting_meta = dict(copy_data.get("meeting") or {})
    racing_date = str(meeting_meta.get("racing_date") or "")[:10]
    course = str(meeting_meta.get("course") or "").upper()
    if not racing_date or not course:
        raise ValueError("copy.json missing meeting.racing_date / course")

    fx = lookup_meeting_session(racing_date, course)
    if session is None:
        session = fx.get("session")
    if is_day_meeting is None and "is_day_meeting" in fx:
        is_day_meeting = fx.get("is_day_meeting")

    theme = resolve_poster_theme(
        course=course, session=session, is_day_meeting=is_day_meeting
    )
    ad_id = stable_ad_id(
        racing_date, course, session=session, is_day_meeting=is_day_meeting
    )
    venue = _venue_label(course)
    session_zh = _session_zh(theme)
    meeting = {
        "date": racing_date,
        "weekday": _weekday_zh(racing_date),
        "venue": venue,
        "venue_code": course,
        "session": session_zh,
    }
    tips = _tips_from_races(list(copy_data.get("races") or []))
    intro = _build_intro(meeting, tips)
    cta = DEFAULT_CTA
    hashtags = list(DEFAULT_HASHTAGS)
    template_facebook = _build_facebook_copy(
        meeting=meeting,
        tips=tips,
        intro=intro,
        cta=cta,
        hashtags=hashtags,
        fused_copy=str(copy_data.get("fused_copy") or ""),
    )
    short = _build_short_copy(meeting, tips, cta)

    out_root = Path(output_root) if output_root else default_output_dir()
    paths = package_paths(ad_id, out_root)
    src = Path(poster_src) if poster_src else latest_paths(out_root)["fused"]
    poster_url = ""
    has_poster = False
    if src.is_file():
        shutil.copy2(src, paths["poster"])
        has_poster = paths["poster"].is_file()
        base = public_base_url()
        poster_url = (
            f"{base}/v1/ads/{ad_id}/poster" if base else f"/v1/ads/{ad_id}/poster"
        )

    ai = ai_social_payload(out_root)
    facebook = str((ai or {}).get("post_text") or "").strip() or template_facebook
    if ai and ai.get("hashtags"):
        hashtags = list(ai.get("hashtags") or hashtags)

    # Grok Bot 期望 ready = 海報 PNG + AI 精選文案齊備
    if not has_poster:
        status = "pending_poster"
    elif require_ai_social() and not ai:
        status = "pending_ai"
    else:
        status = "ready"

    existing = load_ad_package(ad_id, out_root)
    created_at = (
        existing.get("created_at")
        if existing and existing.get("created_at")
        else _hk_now_iso()
    )

    copy_block: Dict[str, Any] = {
        "facebook": facebook,
        "short": short,
        "cta": cta,
        "hashtags": hashtags,
        "ai": ai,  # AI 精選評述（title／featured／post_text）；未齊則 null
    }

    payload: Dict[str, Any] = {
        "id": ad_id,
        "created_at": created_at,
        "updated_at": _hk_now_iso(),
        "status": status,
        "meeting": meeting,
        "intro": intro,
        "tips": tips,
        "copy": copy_block,
        "assets": {
            "poster_url": poster_url,
            "poster_alt": f"J18 賽前預測海報 {racing_date} {venue}{session_zh}",
            "poster_path": str(paths["poster"]) if paths["poster"].is_file() else "",
        },
        "publish": {
            "channels": ["facebook"],
            "page": DEFAULT_FB_PAGE,
            "when": "immediate",
        },
        "links": {"site": DEFAULT_SITE, "detail": ""},
        "meta": {
            "batch_id": meeting_meta.get("batch_id"),
            "theme": theme,
            "n_races": len(tips),
            "primary_track": meeting_meta.get("primary_track") or "fused",
            "has_ai_social": bool(ai),
            "has_poster": has_poster,
            "require_ai_social": require_ai_social(),
        },
    }
    save_ad_package(payload, out_root)

    # 只在海報 +（預設）AI 文案齊備時 webhook，避免 Grok 提早發半成品
    if notify and payload.get("status") == "ready":
        wh = dispatch_ad_webhook(payload)
        payload["webhook"] = wh
        save_ad_package(payload, out_root)

    return payload


def publish_ad_package_after_outputs(
    *,
    output_root: Path,
    notify: bool = True,
) -> Dict[str, Any]:
    copy_data = load_copy_json(output_root)
    if not copy_data or not (copy_data.get("meeting") or {}).get("racing_date"):
        return {"ok": False, "error": "copy.json 未就緒"}
    try:
        pkg = build_ad_package_from_copy(
            copy_data, output_root=output_root, notify=notify
        )
        return {
            "ok": True,
            "id": pkg.get("id"),
            "status": pkg.get("status"),
            "package": pkg,
        }
    except Exception as e:
        logger.exception("publish_ad_package_after_outputs failed")
        return {"ok": False, "error": str(e)}


def generate_ad_package(
    *,
    batch_id: Optional[str] = None,
    racing_date: str = "",
    course: str = "",
    output_root: Optional[Path] = None,
    notify: bool = True,
    force_regen_poster: bool = False,
) -> Dict[str, Any]:
    out_root = Path(output_root) if output_root else default_output_dir()
    out_root.mkdir(parents=True, exist_ok=True)

    if batch_id and force_regen_poster:
        regen = generate_ads_from_snapshot_batch(batch_id, output_root=out_root)
        if not regen.get("ok"):
            return {
                "ok": False,
                "error": regen.get("error") or "regen failed",
                "regen": regen,
            }

    copy_data = load_copy_json(out_root)
    if racing_date and course:
        meeting = dict(copy_data.get("meeting") or {})
        meeting["racing_date"] = racing_date[:10]
        meeting["course"] = course.upper()
        copy_data["meeting"] = meeting

    if not copy_data.get("meeting"):
        return {"ok": False, "error": "無可用 copy.json／meeting 資料"}

    pkg = build_ad_package_from_copy(copy_data, output_root=out_root, notify=notify)
    return {"ok": True, "id": pkg["id"], "status": pkg["status"], "package": pkg}


def _webhook_headers(ad_id: str) -> Dict[str, str]:
    secret = (os.getenv("GROK_BOT_WEBHOOK_SECRET") or "").strip()
    secret_header = (
        os.getenv("GROK_BOT_WEBHOOK_SECRET_HEADER") or "X-Webhook-Secret"
    ).strip()
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": ad_id,
        "User-Agent": "J18-AdPackage/1.0",
    }
    if secret:
        headers[secret_header] = secret
    return headers


def dispatch_ad_webhook(
    payload: Dict[str, Any],
    *,
    url: Optional[str] = None,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    if payload.get("status") != "ready":
        return {"ok": False, "skipped": True, "reason": "status not ready"}
    target = (url or os.getenv("GROK_BOT_WEBHOOK_URL") or "").strip()
    if not target:
        return {"ok": False, "skipped": True, "reason": "GROK_BOT_WEBHOOK_URL not set"}

    ad_id = str(payload.get("id") or "")
    headers = _webhook_headers(ad_id)
    # 只推送對外 schema（唔含本機路徑／webhook 狀態）
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
                logger.info("ad webhook ok id=%s attempt=%s", ad_id, i + 1)
                return {"ok": True, "attempts": attempts, "url": target}
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            logger.warning("ad webhook non-2xx id=%s %s", ad_id, last_error)
        except Exception as e:
            last_error = str(e)
            attempts.append({"attempt": i + 1, "error": last_error})
            logger.warning("ad webhook error id=%s %s", ad_id, last_error)
        if i + 1 < max_attempts:
            time.sleep(2 ** i)

    return {"ok": False, "error": last_error, "attempts": attempts, "url": target}


def list_ad_package_ids(output_root: Optional[Path] = None) -> List[str]:
    root = packages_dir(output_root)
    return sorted({p.stem for p in root.glob("*.json")}, reverse=True)
