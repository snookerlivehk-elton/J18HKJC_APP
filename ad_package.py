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
DEFAULT_DISCLAIMER = "預測／資料只供參考，投注前請自行判斷。"
PACKAGE_HASHTAG_LIMIT = 5

# ready 需同時有海報 + AI 精選文案（Grok Bot 輪詢用）；可設 AD_PACKAGE_REQUIRE_AI_SOCIAL=false 關閉
def require_ai_social() -> bool:
    return (os.getenv("AD_PACKAGE_REQUIRE_AI_SOCIAL", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _social_dict_to_ai_payload(social: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize social_copy / archive payload → package copy.ai block."""
    if not social:
        return None
    try:
        from ad_llm_copy import format_social_post_text
    except Exception:
        format_social_post_text = None  # type: ignore
    featured = list(social.get("featured") or [])
    post_text = str(social.get("post_text") or "").strip()
    if not post_text and format_social_post_text:
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


def ai_social_payload(
    output_root: Path,
    *,
    racing_date: str = "",
    course: str = "",
    ad_id: str = "",
) -> Optional[Dict[str, Any]]:
    """從 social_copy.json（或共用 DB archive／package）組 AI 精選區塊；未就緒回傳 None。"""
    social: Dict[str, Any] = {}
    try:
        from ad_llm_copy import load_social_copy

        social = load_social_copy(Path(output_root)) or {}
    except Exception:
        social = {}

    # 跨服務：本機無 social_copy.json 時，從共用 DB 取（CORN 產、Ad API／Streamlit 讀）
    if not social:
        try:
            from ad_store import get_social_json_db, load_archive_latest_db

            if ad_id:
                social = get_social_json_db(ad_id) or {}
            if not social and racing_date and course:
                social = (
                    load_archive_latest_db(
                        str(racing_date)[:10], str(course).upper(), "social"
                    )
                    or {}
                )
        except Exception:
            social = {}

    return _social_dict_to_ai_payload(social if isinstance(social, dict) else {})



def _hk_now_iso() -> str:
    return datetime.now(HK_TZ).isoformat(timespec="seconds")


def packages_dir(output_root: Optional[Path] = None) -> Path:
    root = Path(output_root) if output_root else default_output_dir()
    d = root / PACKAGES_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def public_base_url() -> str:
    return (os.getenv("AD_API_PUBLIC_BASE") or os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")


def remote_ad_api_base() -> str:
    """CORN／Streamlit 推送生產 Ad API 用（與 AD_API_PUBLIC_BASE 可相同主機）。"""
    return (
        os.getenv("AD_API_BASE_URL")
        or os.getenv("AD_API_PUSH_URL")
        or ""
    ).strip().rstrip("/")


def _cap_hashtags(tags: Sequence[str], *, limit: int = PACKAGE_HASHTAG_LIMIT) -> List[str]:
    out: List[str] = []
    for tag in tags:
        s = str(tag or "").strip()
        if not s:
            continue
        if not s.startswith("#"):
            s = "#" + s.lstrip("#")
        if s not in out:
            out.append(s)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _default_start_time(theme: str, session_zh: str = "") -> str:
    """無 race_time 時用場次慣例開跑時間（給文案用）。"""
    if theme == "day" or session_zh == "日":
        return "約下午1時"
    return "約晚上7時15分"


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
    start = str(meeting.get("start_time") or "").strip()
    start_bit = f"，預計{start}開跑" if start else ""
    return (
        f"{meeting.get('date', '')} {meeting.get('weekday', '')}"
        f"{meeting.get('venue', '')}{meeting.get('session', '')}賽共 {len(tips)} 場"
        f"{start_bit}，J18 綜合推介已出爐——"
        f"你又睇邊場最有睇頭？留言話我知！"
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
    start = str(meeting.get("start_time") or "").strip()
    start_line = f"開跑時間：{start}" if start else ""
    lines = [
        (
            f"【J18 賽前預測】{meeting.get('date', '')} {meeting.get('weekday', '')} "
            f"{meeting.get('venue', '')}{meeting.get('session', '')}賽"
        ),
    ]
    if start_line:
        lines.append(start_line)
    lines.extend(
        [
            "",
            intro,
            "",
            "今場邊匹令你最心水？留言一齊傾下👇",
            "",
        ]
    )
    for t in tips:
        horses = t.get("horses") or []
        body = (
            "、".join(f"{h['no']} {h['name']}" for h in horses) if horses else "暫無推介"
        )
        lines.append(f"第{t.get('race')}場：{body}")
    lines.extend(
        [
            "",
            cta,
            DEFAULT_DISCLAIMER,
            "賽前如有變動，請以 J18.hk 最新版本為準。",
            "",
            " ".join(_cap_hashtags(hashtags)),
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
        f"{meeting.get('session', '')}賽 {len(tips)} 場綜合推介已更新！"
        f"你又點睇？留言話我知！{cta}"
    )


def _ensure_facebook_publish_ready(
    text: str,
    *,
    meeting: Dict[str, Any],
    cta: str,
    hashtags: Sequence[str],
) -> str:
    """確保 AI／模板文案含日期場地、CTA、免責；缺則補尾。"""
    body = str(text or "").strip()
    if not body:
        return body
    lower = body.lower()
    extras: List[str] = []
    date = str(meeting.get("date") or "")
    venue = str(meeting.get("venue") or "")
    if date and date not in body:
        extras.append(
            f"{date} {meeting.get('weekday', '')} {venue}{meeting.get('session', '')}賽"
            f"{(' · ' + meeting['start_time']) if meeting.get('start_time') else ''}".rstrip()
        )
    if "j18.hk" not in lower and "j18.hk" not in body:
        extras.append(cta)
    if "參考" not in body and "免責" not in body:
        extras.append(DEFAULT_DISCLAIMER)
    tags = _cap_hashtags(hashtags)
    if tags and not any(t in body for t in tags[:2]):
        extras.append(" ".join(tags))
    if not extras:
        return body
    return body.rstrip() + "\n\n" + "\n".join(extras)


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
    # 跨服務：先讀共用 DB，再 fallback 本機碟
    try:
        from ad_store import load_ad_package_db

        db_pkg = load_ad_package_db(ad_id)
        if db_pkg:
            return db_pkg
    except Exception:
        pass
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
    try:
        from ad_store import load_latest_ad_package_db

        db_pkg = load_latest_ad_package_db(ready_only=True)
        if db_pkg:
            return db_pkg
    except Exception:
        pass
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
    payload: Dict[str, Any],
    output_root: Optional[Path] = None,
    *,
    push_remote: bool = True,
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
    # dual-write 到共用 DB，讓 Streamlit／Ad API 唔共碟都睇到
    poster_bytes = None
    try:
        from ad_store import upsert_ad_package

        out_root = Path(output_root) if output_root else default_output_dir()
        if paths["poster"].is_file():
            poster_bytes = paths["poster"].read_bytes()
        else:
            fused = out_root / "fused.png"
            if fused.is_file():
                poster_bytes = fused.read_bytes()
        social_json = None
        copy_json = None
        try:
            from ad_llm_copy import load_social_copy
            from ad_poster import load_copy_json

            social_json = load_social_copy(out_root) or None
            if not social_json and isinstance((payload.get("copy") or {}).get("ai"), dict):
                social_json = payload["copy"]["ai"]
            copy_json = load_copy_json(out_root) or None
        except Exception:
            if isinstance((payload.get("copy") or {}).get("ai"), dict):
                social_json = payload["copy"]["ai"]
        upsert_ad_package(
            payload,
            poster_png=poster_bytes,
            copy_json=copy_json,
            social_json=social_json,
        )
    except Exception as exc:
        logger.warning("ad_store upsert failed: %s", exc)

    # 跨服務：Streamlit／CORN → 生產 Ad API（HTTP ingest；唔靠共碟）
    if push_remote and payload.get("status") == "ready":
        try:
            if poster_bytes is None:
                if paths["poster"].is_file():
                    poster_bytes = paths["poster"].read_bytes()
                else:
                    out_root = Path(output_root) if output_root else default_output_dir()
                    fused = out_root / "fused.png"
                    if fused.is_file():
                        poster_bytes = fused.read_bytes()
            remote = push_ad_package_remote(payload, poster_png=poster_bytes)
            if remote.get("ok"):
                payload["remote_push"] = {"ok": True, "id": remote.get("id")}
            elif not remote.get("skipped"):
                payload["remote_push"] = {
                    "ok": False,
                    "error": remote.get("error") or remote.get("reason"),
                }
                logger.warning("ad package remote push failed: %s", remote)
        except Exception as exc:
            logger.warning("ad package remote push error: %s", exc)
            payload["remote_push"] = {"ok": False, "error": str(exc)}
    return paths["json"]


def push_ad_package_remote(
    payload: Dict[str, Any],
    *,
    poster_png: Optional[bytes] = None,
    notify: bool = False,
) -> Dict[str, Any]:
    """
    POST 完整 ready 包（+ 海報 bytes）到生產 Ad API /v1/ads/ingest。
    需設 AD_API_BASE_URL + AD_API_KEY（與下游讀取用同一 key）。
    """
    base = remote_ad_api_base()
    if not base:
        return {"ok": False, "skipped": True, "reason": "AD_API_BASE_URL not set"}
    public = public_base_url()
    # 本機就係 Ad API 且 base＝公開 URL 時唔好自推（避免無謂迴圈）
    if public and base.rstrip("/") == public.rstrip("/"):
        skip_self = (os.getenv("AD_API_PUSH_SELF") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if not skip_self:
            return {
                "ok": False,
                "skipped": True,
                "reason": "AD_API_BASE_URL equals AD_API_PUBLIC_BASE (set AD_API_PUSH_SELF=1 to force)",
            }
    key = (os.getenv("AD_API_KEY") or os.getenv("PREDICTION_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "skipped": True, "reason": "AD_API_KEY not set"}

    import base64

    try:
        import httpx
    except ImportError:
        return {"ok": False, "error": "httpx not installed"}

    body: Dict[str, Any] = {
        "package": public_payload(payload),
        "notify": bool(notify),
    }
    # public_payload 冇 meta；下游主要用 copy／assets；status 已有
    if poster_png:
        body["poster_png_b64"] = base64.b64encode(poster_png).decode("ascii")

    url = f"{base}/v1/ads/ingest"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "J18-AdPackage-Push/1.0",
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=body, headers=headers)
        if 200 <= resp.status_code < 300:
            data = {}
            try:
                data = resp.json()
            except Exception:
                data = {}
            return {
                "ok": True,
                "id": data.get("id") or payload.get("id"),
                "status_code": resp.status_code,
                "url": url,
            }
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}: {(resp.text or '')[:400]}",
            "url": url,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url}


def ingest_ad_package(
    package: Dict[str, Any],
    *,
    poster_png: Optional[bytes] = None,
    output_root: Optional[Path] = None,
    notify: bool = False,
) -> Dict[str, Any]:
    """
    接收上游推送嘅廣告包：寫本機 packages／DB，並改寫 poster_url 指向本服務公開 URL。
    """
    if not isinstance(package, dict) or not package.get("id"):
        raise ValueError("package.id required")
    pkg = json.loads(json.dumps(package, ensure_ascii=False, default=str))
    ad_id = str(pkg["id"])
    out_root = Path(output_root) if output_root else default_output_dir()
    paths = package_paths(ad_id, out_root)
    paths["root"].mkdir(parents=True, exist_ok=True)

    if poster_png:
        paths["poster"].write_bytes(poster_png)
        try:
            (out_root / "fused.png").write_bytes(poster_png)
        except Exception:
            pass

    base = public_base_url()
    assets = dict(pkg.get("assets") or {})
    assets["poster_url"] = (
        f"{base}/v1/ads/{ad_id}/poster" if base else f"/v1/ads/{ad_id}/poster"
    )
    assets.pop("poster_path", None)
    if paths["poster"].is_file():
        assets["poster_path"] = str(paths["poster"])
    pkg["assets"] = assets
    pkg["updated_at"] = _hk_now_iso()
    if not pkg.get("created_at"):
        pkg["created_at"] = _hk_now_iso()

    # 寫入本機＋DB，唔再向外推（本服務就係目標）
    save_ad_package(pkg, out_root, push_remote=False)

    if notify and pkg.get("status") == "ready":
        wh = dispatch_ad_webhook(pkg)
        pkg["webhook"] = wh
        save_ad_package(pkg, out_root, push_remote=False)
    return pkg


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
    start_time = str(
        meeting_meta.get("start_time")
        or meeting_meta.get("post_time")
        or fx.get("start_time")
        or ""
    ).strip() or _default_start_time(theme, session_zh)
    meeting = {
        "date": racing_date,
        "weekday": _weekday_zh(racing_date),
        "venue": venue,
        "venue_code": course,
        "session": session_zh,
        "start_time": start_time,
    }
    tips = _tips_from_races(list(copy_data.get("races") or []))
    intro = _build_intro(meeting, tips)
    cta = DEFAULT_CTA
    hashtags = _cap_hashtags(DEFAULT_HASHTAGS)
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

    ai = ai_social_payload(
        out_root, racing_date=racing_date, course=course, ad_id=ad_id
    )
    # Facebook 文案優先用 AI 高互動 post_text（含 J18.hk CTA footer）；否則 template
    facebook = str((ai or {}).get("post_text") or "").strip() or template_facebook
    if ai and ai.get("hashtags"):
        hashtags = _cap_hashtags(list(ai.get("hashtags") or hashtags))
    facebook = _ensure_facebook_publish_ready(
        facebook, meeting=meeting, cta=cta, hashtags=hashtags
    )

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

    # ready 必推；pending_ai 時若 AD_PACKAGE_WEBHOOK_ON_POSTER（預設 true）亦推海報版
    if notify and payload.get("status") in {"ready", "pending_ai", "pending_ai_social"}:
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
    status = str(payload.get("status") or "")
    allow_poster = (os.getenv("AD_PACKAGE_WEBHOOK_ON_POSTER", "true") or "true").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if status == "ready":
        pass
    elif allow_poster and status in {"pending_ai", "pending_ai_social"} and (
        (payload.get("meta") or {}).get("has_poster")
        or (payload.get("assets") or {}).get("poster_url")
    ):
        # 海報已齊但 AI 文案未到：預設仍可通知（跨服務自動化）；可用 env 關閉
        pass
    else:
        return {"ok": False, "skipped": True, "reason": f"status not ready ({status})"}
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
    ids: List[str] = []
    try:
        from ad_store import list_ad_package_ids_db

        ids = list(list_ad_package_ids_db())
    except Exception:
        ids = []
    root = packages_dir(output_root)
    for p in root.glob("*.json"):
        if p.stem not in ids:
            ids.append(p.stem)
    return sorted(ids, reverse=True)
