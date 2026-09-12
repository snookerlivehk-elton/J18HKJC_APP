"""
社交留言機械人用「賽事答覆上下文」：

- 最新一期綜合推介（fused tips）
- 推介馬匹嘅 Form AI 評價（summary／score／confidence／tags／risks）

寫入 ad_output/reply_context/{id}.json；ready 時可 webhook 推去留言機械人。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

HK_TZ = timezone(timedelta(hours=8))
REPLY_SUBDIR = "reply_context"
LATEST_ID_NAME = "_latest_id.txt"
DEFAULT_DISCLAIMER = "預測／AI 評價只供參考，投注前請自行判斷。唔構成投注建議。"
DEFAULT_SITE = "https://J18.hk"


def _hk_now_iso() -> str:
    return datetime.now(HK_TZ).isoformat(timespec="seconds")


def _default_output_root() -> Path:
    try:
        from ad_poster import default_output_dir

        return default_output_dir()
    except Exception:
        custom = (os.getenv("AD_OUTPUT_DIR") or "").strip()
        return Path(custom) if custom else Path("ad_output")


def reply_context_dir(output_root: Optional[Path] = None) -> Path:
    root = Path(output_root) if output_root else _default_output_root()
    d = root / REPLY_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def reply_context_paths(
    context_id: str, output_root: Optional[Path] = None
) -> Dict[str, Path]:
    d = reply_context_dir(output_root)
    return {
        "json": d / f"{context_id}.json",
        "latest_id": d / LATEST_ID_NAME,
    }


def _parse_json_list(val: Any) -> List[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def race_id_from_meeting(racing_date: str, course: str, race_no: int) -> str:
    """與 ETL 一致：YYYYMMDD + ST|HV + 兩位場次。"""
    d = str(racing_date or "").replace("-", "")[:8]
    c = str(course or "").upper().strip()
    if c in {"沙田", "ST"}:
        c = "ST"
    elif c in {"跑馬地", "谷草", "HV"}:
        c = "HV"
    return f"{d}{c}{int(race_no):02d}"


def _race_id_lookup_from_copy(
    copy_data: Optional[Dict[str, Any]],
) -> Dict[int, str]:
    out: Dict[int, str] = {}
    if not copy_data:
        return out
    for r in list(copy_data.get("races") or []):
        if not isinstance(r, dict):
            continue
        try:
            n = int(r.get("race_no") or r.get("race") or r.get("race_num"))
        except (TypeError, ValueError):
            continue
        rid = str(r.get("race_id") or "").strip()
        if rid:
            out[n] = rid
    return out


def _pick_meta_from_copy(
    copy_data: Optional[Dict[str, Any]],
) -> Dict[tuple, Dict[str, Any]]:
    """(race_no, horse_no) → tag / share_pct from fused_picks."""
    out: Dict[tuple, Dict[str, Any]] = {}
    if not copy_data:
        return out
    for r in list(copy_data.get("races") or []):
        if not isinstance(r, dict):
            continue
        try:
            race_n = int(r.get("race_no") or r.get("race") or r.get("race_num"))
        except (TypeError, ValueError):
            continue
        picks = r.get("fused_picks") or r.get("model_picks") or r.get("ai_picks") or []
        if not isinstance(picks, list):
            continue
        for p in picks:
            if not isinstance(p, dict):
                continue
            try:
                hno = int(p.get("horse_no") or p.get("no"))
            except (TypeError, ValueError):
                continue
            meta: Dict[str, Any] = {}
            if p.get("tag"):
                meta["tag"] = str(p.get("tag"))
            sp = p.get("share_pct")
            if sp is not None:
                try:
                    meta["share_pct"] = round(float(sp), 1)
                except (TypeError, ValueError):
                    pass
            out[(race_n, hno)] = meta
    return out


def load_form_ai_map(
    race_id: str,
    *,
    loader: Optional[Callable[[str], Any]] = None,
) -> Dict[int, Dict[str, Any]]:
    """race_id → {horse_no: ai eval dict}。loader 可注入（測試用）。"""
    out: Dict[int, Dict[str, Any]] = {}
    df = None
    if loader is not None:
        df = loader(race_id)
    else:
        try:
            from form_ai_analyst import FormAIAnalyst

            df = FormAIAnalyst().load_ai_for_race(race_id)
        except Exception as exc:
            logger.debug("form ai load failed race_id=%s: %s", race_id, exc)
            return out

    if df is None:
        return out
    try:
        empty = getattr(df, "empty", True)
        if empty:
            return out
        rows = df.to_dict(orient="records") if hasattr(df, "to_dict") else list(df)
    except Exception:
        return out

    for a in rows:
        if not isinstance(a, dict):
            continue
        try:
            hno = int(a.get("horse_no"))
        except (TypeError, ValueError):
            continue
        sc = a.get("ai_score")
        cf = a.get("confidence")
        try:
            sc_f = None if sc is None else float(sc)
        except (TypeError, ValueError):
            sc_f = None
        try:
            cf_f = None if cf is None else float(cf)
        except (TypeError, ValueError):
            cf_f = None
        combo = None
        if sc_f is not None and cf_f is not None:
            combo = round(sc_f * cf_f, 4)
        out[hno] = {
            "ai_score": sc_f,
            "confidence": cf_f,
            "ai_combo": combo,
            "summary": str(a.get("summary") or "").strip() or None,
            "tags": _parse_json_list(a.get("tags_json") if "tags_json" in a else a.get("tags")),
            "risks": _parse_json_list(
                a.get("risks_json") if "risks_json" in a else a.get("risks")
            ),
            "evidence": _parse_json_list(
                a.get("evidence_json") if "evidence_json" in a else a.get("evidence")
            ),
        }
    return out


def enrich_tips_with_ai(
    tips: Sequence[Dict[str, Any]],
    *,
    racing_date: str = "",
    course: str = "",
    copy_data: Optional[Dict[str, Any]] = None,
    form_ai_loader: Optional[Callable[[str], Any]] = None,
) -> List[Dict[str, Any]]:
    """為綜合推介每匹馬掛上 Form AI 評價（冇評價則 ai=null）。"""
    race_ids = _race_id_lookup_from_copy(copy_data)
    pick_meta = _pick_meta_from_copy(copy_data)
    venue = str(course or "").upper()
    if not venue and copy_data:
        venue = str((copy_data.get("meeting") or {}).get("course") or "").upper()
    date = str(racing_date or "")[:10]
    if not date and copy_data:
        date = str((copy_data.get("meeting") or {}).get("racing_date") or "")[:10]

    enriched: List[Dict[str, Any]] = []
    ai_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}

    for tip in tips:
        if not isinstance(tip, dict):
            continue
        try:
            race_n = int(tip.get("race") or tip.get("race_no"))
        except (TypeError, ValueError):
            continue
        rid = str(tip.get("race_id") or race_ids.get(race_n) or "").strip()
        if not rid and date and venue:
            rid = race_id_from_meeting(date, venue, race_n)
        if rid and rid not in ai_cache:
            ai_cache[rid] = load_form_ai_map(rid, loader=form_ai_loader)

        horses_out: List[Dict[str, Any]] = []
        for h in list(tip.get("horses") or []):
            if not isinstance(h, dict):
                continue
            try:
                hno = int(h.get("no") if h.get("no") is not None else h.get("horse_no"))
            except (TypeError, ValueError):
                continue
            name = str(h.get("name") or h.get("horse_name") or "").strip()
            row: Dict[str, Any] = {"no": hno, "name": name}
            meta = pick_meta.get((race_n, hno)) or {}
            if meta.get("tag"):
                row["tag"] = meta["tag"]
            elif h.get("tag"):
                row["tag"] = str(h.get("tag"))
            if "share_pct" in meta:
                row["share_pct"] = meta["share_pct"]
            elif h.get("share_pct") is not None:
                try:
                    row["share_pct"] = round(float(h.get("share_pct")), 1)
                except (TypeError, ValueError):
                    pass
            ai = (ai_cache.get(rid) or {}).get(hno)
            row["ai"] = ai if ai else None
            horses_out.append(row)

        item: Dict[str, Any] = {"race": race_n, "horses": horses_out}
        if rid:
            item["race_id"] = rid
        enriched.append(item)

    enriched.sort(key=lambda x: x["race"])
    return enriched


def _count_ai_evals(tips: Sequence[Dict[str, Any]]) -> int:
    n = 0
    for t in tips:
        for h in list((t or {}).get("horses") or []):
            if isinstance(h, dict) and h.get("ai"):
                n += 1
    return n


def build_reply_context(
    ad_pkg: Dict[str, Any],
    *,
    copy_data: Optional[Dict[str, Any]] = None,
    output_root: Optional[Path] = None,
    form_ai_loader: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """由廣告包組留言機械人上下文。"""
    ad_id = str(ad_pkg.get("id") or "").strip()
    if not ad_id:
        raise ValueError("ad package missing id")

    meeting = dict(ad_pkg.get("meeting") or {})
    racing_date = str(meeting.get("date") or meeting.get("racing_date") or "")[:10]
    course = str(
        meeting.get("venue_code") or meeting.get("course") or ""
    ).upper()

    if copy_data is None:
        try:
            from ad_poster import load_copy_json

            root = Path(output_root) if output_root else _default_output_root()
            copy_data = load_copy_json(root) or {}
        except Exception:
            copy_data = {}
        # 嘗試 DB archive／package copy
        if not copy_data:
            try:
                from ad_store import get_copy_json_db, load_archive_latest_db

                copy_data = get_copy_json_db(ad_id) or {}
                if not copy_data and racing_date and course:
                    archived = load_archive_latest_db(racing_date, course, "copy") or {}
                    if isinstance(archived, dict):
                        copy_data = archived.get("payload") or archived
            except Exception:
                copy_data = {}

    tips = enrich_tips_with_ai(
        list(ad_pkg.get("tips") or []),
        racing_date=racing_date,
        course=course,
        copy_data=copy_data if isinstance(copy_data, dict) else {},
        form_ai_loader=form_ai_loader,
    )
    n_horses = sum(len(t.get("horses") or []) for t in tips)
    n_ai = _count_ai_evals(tips)
    if tips and n_horses:
        status = "ready"
    else:
        status = "pending_tips"

    copy_block = dict(ad_pkg.get("copy") or {})
    featured = []
    ai_social = copy_block.get("ai")
    if isinstance(ai_social, dict):
        featured = list(ai_social.get("featured") or [])

    existing = load_reply_context(ad_id, output_root)
    created_at = (
        existing.get("created_at")
        if existing and existing.get("created_at")
        else _hk_now_iso()
    )

    return {
        "id": ad_id,
        "created_at": created_at,
        "updated_at": _hk_now_iso(),
        "status": status,
        "purpose": "social_reply",
        "meeting": meeting,
        "intro": str(ad_pkg.get("intro") or "").strip(),
        "tips": tips,
        "featured": featured,
        "disclaimer": DEFAULT_DISCLAIMER,
        "links": {"site": DEFAULT_SITE, "detail": ""},
        "source": {
            "ad_id": ad_id,
            "ad_status": ad_pkg.get("status"),
            "primary_track": "fused",
        },
        "meta": {
            "n_races": len(tips),
            "n_horses": n_horses,
            "n_ai_evals": n_ai,
            "coverage": round(n_ai / n_horses, 3) if n_horses else 0.0,
        },
    }


def public_reply_payload(pkg: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "id",
        "created_at",
        "updated_at",
        "status",
        "purpose",
        "meeting",
        "intro",
        "tips",
        "featured",
        "disclaimer",
        "links",
        "source",
        "meta",
    )
    out: Dict[str, Any] = {}
    for k in keys:
        if k in pkg:
            out[k] = json.loads(json.dumps(pkg[k], ensure_ascii=False))
    return out


def save_reply_context(
    payload: Dict[str, Any],
    output_root: Optional[Path] = None,
) -> Path:
    cid = str(payload.get("id") or "")
    if not cid:
        raise ValueError("reply context missing id")
    paths = reply_context_paths(cid, output_root)
    paths["json"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if payload.get("status") == "ready":
        paths["latest_id"].write_text(cid, encoding="utf-8")
    return paths["json"]


def load_reply_context(
    context_id: str, output_root: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    paths = reply_context_paths(context_id, output_root)
    if not paths["json"].is_file():
        return None
    try:
        return json.loads(paths["json"].read_text(encoding="utf-8"))
    except Exception:
        return None


def load_latest_reply_context(
    output_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    root = Path(output_root) if output_root else _default_output_root()
    paths = reply_context_paths("_", root)
    latest_file = paths["latest_id"]
    if latest_file.is_file():
        cid = latest_file.read_text(encoding="utf-8").strip()
        if cid:
            pkg = load_reply_context(cid, root)
            if pkg:
                return pkg
    # fallback：最新 mtime
    d = reply_context_dir(root)
    files = sorted(
        [p for p in d.glob("*.json") if p.stem != LATEST_ID_NAME],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in files:
        try:
            pkg = json.loads(p.read_text(encoding="utf-8"))
            if pkg.get("status") == "ready":
                return pkg
        except Exception:
            continue
    return None


def list_reply_context_ids(output_root: Optional[Path] = None) -> List[str]:
    d = reply_context_dir(output_root)
    return sorted([p.stem for p in d.glob("*.json")], reverse=True)


def format_reply_context_prompt(pkg: Dict[str, Any]) -> str:
    """把上下文編成留言機械人可用嘅參考文本。"""
    meeting = pkg.get("meeting") or {}
    lines: List[str] = [
        "【J18 賽事答覆參考資料】",
        (
            f"賽事：{meeting.get('date', '')} "
            f"{meeting.get('weekday', '')}"
            f"{meeting.get('venue', '')}"
            f"{meeting.get('session', '')}賽"
        ).strip(),
        f"包 ID：{pkg.get('id')}",
        "",
        "以下係綜合推介（fused）同推介馬嘅 AI 評價。回答留言時請以此為準；"
        "唔好發明未列出嘅推介或評價；預測只供參考。",
        "",
    ]
    intro = str(pkg.get("intro") or "").strip()
    if intro:
        lines.append(intro)
        lines.append("")

    for tip in list(pkg.get("tips") or []):
        race_n = tip.get("race")
        lines.append(f"── 第{race_n}場 ──")
        for h in list(tip.get("horses") or []):
            tag = f"（{h.get('tag')}）" if h.get("tag") else ""
            share = (
                f" 綜合份額 {h.get('share_pct')}%"
                if h.get("share_pct") is not None
                else ""
            )
            lines.append(f"• {h.get('no')} {h.get('name')}{tag}{share}")
            ai = h.get("ai") or {}
            if not ai:
                lines.append("  AI 評價：暫無")
                continue
            sc = ai.get("ai_score")
            cf = ai.get("confidence")
            score_bits = []
            if sc is not None:
                score_bits.append(f"評分 {sc:+.2f}")
            if cf is not None:
                score_bits.append(f"信心 {float(cf):.0%}")
            if score_bits:
                lines.append("  " + "／".join(score_bits))
            if ai.get("summary"):
                lines.append(f"  評價：{ai['summary']}")
            tags = ai.get("tags") or []
            if tags:
                lines.append("  標籤：" + "、".join(str(t) for t in tags[:6]))
            risks = ai.get("risks") or []
            if risks:
                lines.append("  風險：" + "；".join(str(r) for r in risks[:4]))
        lines.append("")

    featured = list(pkg.get("featured") or [])
    if featured:
        lines.append("── 社交精選評述（可輔助語氣）──")
        for f in featured:
            lines.append(
                f"第{f.get('race_no')}場｜{f.get('horse_no')} {f.get('horse_name')}："
                f"{f.get('comment') or ''}"
            )
        lines.append("")

    lines.append(str(pkg.get("disclaimer") or DEFAULT_DISCLAIMER))
    site = (pkg.get("links") or {}).get("site") or DEFAULT_SITE
    lines.append(f"官網：{site}")
    return "\n".join(lines).strip() + "\n"


def _reply_webhook_headers(context_id: str) -> Dict[str, str]:
    secret = (
        os.getenv("SOCIAL_REPLY_BOT_WEBHOOK_SECRET")
        or os.getenv("GROK_BOT_WEBHOOK_SECRET")
        or ""
    ).strip()
    secret_header = (
        os.getenv("SOCIAL_REPLY_BOT_WEBHOOK_SECRET_HEADER")
        or os.getenv("GROK_BOT_WEBHOOK_SECRET_HEADER")
        or "X-Webhook-Secret"
    ).strip()
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": f"reply-{context_id}",
        "User-Agent": "J18-SocialReplyContext/1.0",
        "X-Context-Purpose": "social_reply",
    }
    if secret:
        headers[secret_header] = secret
    return headers


def dispatch_reply_webhook(
    payload: Dict[str, Any],
    *,
    url: Optional[str] = None,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    """推送留言上下文去 SOCIAL_REPLY_BOT_WEBHOOK_URL。"""
    if str(payload.get("status") or "") != "ready":
        return {
            "ok": False,
            "skipped": True,
            "reason": f"status not ready ({payload.get('status')})",
        }
    target = (
        url
        or os.getenv("SOCIAL_REPLY_BOT_WEBHOOK_URL")
        or os.getenv("REPLY_BOT_WEBHOOK_URL")
        or ""
    ).strip()
    if not target:
        return {
            "ok": False,
            "skipped": True,
            "reason": "SOCIAL_REPLY_BOT_WEBHOOK_URL not set",
        }

    cid = str(payload.get("id") or "")
    headers = _reply_webhook_headers(cid)
    body = json.dumps(public_reply_payload(payload), ensure_ascii=False).encode("utf-8")
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
                logger.info("reply webhook ok id=%s attempt=%s", cid, i + 1)
                return {"ok": True, "attempts": attempts, "url": target}
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            logger.warning("reply webhook non-2xx id=%s %s", cid, last_error)
        except Exception as e:
            last_error = str(e)
            attempts.append({"attempt": i + 1, "error": last_error})
            logger.warning("reply webhook error id=%s %s", cid, last_error)
        if i + 1 < max_attempts:
            time.sleep(2 ** i)

    return {"ok": False, "error": last_error, "attempts": attempts, "url": target}


def publish_reply_context(
    ad_pkg: Dict[str, Any],
    *,
    output_root: Optional[Path] = None,
    copy_data: Optional[Dict[str, Any]] = None,
    notify: bool = True,
    form_ai_loader: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """由廣告包產出／保存留言上下文，可選 webhook。"""
    if not ad_pkg or not ad_pkg.get("id"):
        return {"ok": False, "error": "missing ad package"}
    # 廣告包要有 tips；唔強制 ad status=ready（允許只得推介未有海報時先推上下文）
    tips = list(ad_pkg.get("tips") or [])
    if not tips:
        return {"ok": False, "skipped": True, "reason": "ad package tips empty"}

    ctx = build_reply_context(
        ad_pkg,
        copy_data=copy_data,
        output_root=output_root,
        form_ai_loader=form_ai_loader,
    )
    save_reply_context(ctx, output_root)

    webhook: Dict[str, Any] = {"ok": False, "skipped": True, "reason": "notify=false"}
    if notify and ctx.get("status") == "ready":
        webhook = dispatch_reply_webhook(ctx)
        ctx["webhook"] = webhook
        save_reply_context(ctx, output_root)

    return {
        "ok": True,
        "id": ctx.get("id"),
        "status": ctx.get("status"),
        "package": ctx,
        "webhook": webhook,
    }


def publish_reply_context_from_latest_ad(
    *,
    output_root: Optional[Path] = None,
    notify: bool = True,
    form_ai_loader: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """攞最新廣告包（唔一定 ready）重建留言上下文。"""
    from ad_package import load_ad_package, load_latest_ad_package

    root = Path(output_root) if output_root else _default_output_root()
    pkg = load_latest_ad_package(root)
    if not pkg:
        # 冇 ready 亦試最新檔
        try:
            from ad_package import list_ad_package_ids

            ids = list_ad_package_ids(root)
            if ids:
                pkg = load_ad_package(ids[0], root)
        except Exception:
            pkg = None
    if not pkg:
        return {"ok": False, "error": "no ad package found"}
    return publish_reply_context(
        pkg,
        output_root=root,
        notify=notify,
        form_ai_loader=form_ai_loader,
    )
