"""
Phase D：廣告文案／宣傳評估自動化（供 meeting_tick 呼叫）。

賽前：snapshot＋copy.json 齊 → generate_social_copy → social_copy.json ＋ archive
賽後：SETTLED → evaluate_ad_promo_hits →（有可宣傳）generate_post_race_copy ＋ archive

原則：失敗不回滾快照／結算；冪等以 archive/{date}_{course}/*_latest.json 的 batch_id 判斷。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ad_llm_copy import (
    DEFAULT_TONE,
    AdSocialCopywriter,
    normalize_tone,
    save_social_copy,
)
from ad_poster import default_output_dir, load_copy_json

POST_RACE_COPY_FILE = "post_race_social_copy.json"
PROMO_HITS_FILE = "promo_hits.json"

DEFAULT_AD_TONE = (os.getenv("AD_SOCIAL_TONE") or DEFAULT_TONE).strip() or DEFAULT_TONE


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def archive_meeting_dir(
    output_root: Path, racing_date: str, course: str
) -> Path:
    d = str(racing_date)[:10]
    c = str(course or "").upper()
    return Path(output_root) / "archive" / f"{d}_{c}"


def archive_latest_path(
    output_root: Path, racing_date: str, course: str, kind: str
) -> Path:
    """kind: copy | social | post_race | promo_hits（只存 JSON，不存海報 PNG）"""
    return archive_meeting_dir(output_root, racing_date, course) / f"{kind}_latest.json"


def write_archive_version(
    output_root: Path,
    racing_date: str,
    course: str,
    kind: str,
    data: Dict[str, Any],
) -> Dict[str, str]:
    """寫 latest ＋ timestamped 版本；回傳路徑；並 dual-write 到共用 DB。"""
    root = archive_meeting_dir(output_root, racing_date, course)
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamped = root / f"{kind}_{ts}.json"
    latest = root / f"{kind}_latest.json"
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    stamped.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    try:
        from ad_store import upsert_archive

        meeting = data.get("meeting") if isinstance(data.get("meeting"), dict) else {}
        upsert_archive(
            str(racing_date)[:10],
            str(course or "").upper(),
            str(kind),
            data,
            batch_id=str(meeting.get("batch_id") or data.get("batch_id") or "") or None,
        )
    except Exception:
        pass
    return {"stamped": str(stamped), "latest": str(latest)}


def load_archive_latest(
    output_root: Path, racing_date: str, course: str, kind: str
) -> Dict[str, Any]:
    p = archive_latest_path(output_root, racing_date, course, kind)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        from ad_store import load_archive_latest_db

        return load_archive_latest_db(str(racing_date)[:10], str(course or "").upper(), str(kind)) or {}
    except Exception:
        return {}


def _meeting_batch_id(data: Dict[str, Any]) -> str:
    meeting = data.get("meeting") if isinstance(data, dict) else None
    if isinstance(meeting, dict) and meeting.get("batch_id"):
        return str(meeting.get("batch_id"))
    if isinstance(data, dict) and data.get("batch_id"):
        return str(data.get("batch_id"))
    return ""


def job_done_for_batch(
    output_root: Path,
    racing_date: str,
    course: str,
    kind: str,
    batch_id: str,
) -> bool:
    if not batch_id:
        return False
    data = load_archive_latest(output_root, racing_date, course, kind)
    if _meeting_batch_id(data) == str(batch_id):
        return True
    try:
        from ad_store import job_done_for_batch_db

        return bool(
            job_done_for_batch_db(
                str(racing_date)[:10], str(course or "").upper(), str(kind), str(batch_id)
            )
        )
    except Exception:
        return False


def resolve_meeting_batch_id(
    racing_date: str,
    course: str,
    *,
    prefer_settled: bool = False,
) -> Optional[str]:
    """取該賽日最新（或已結算）快照 batch_id。"""
    try:
        from factor_calibration import FactorCalibration

        cal = FactorCalibration()
        batches = cal.list_batches()
    except Exception:
        return None
    if batches is None or getattr(batches, "empty", True):
        return None
    d, c = str(racing_date)[:10], str(course or "").upper()
    sub = batches[
        (batches["racing_date"].astype(str).str[:10] == d)
        & (batches["course"].astype(str).str.upper() == c)
    ]
    if sub.empty:
        return None
    if prefer_settled and "settled_at" in sub.columns:
        settled = sub[sub["settled_at"].notna()]
        if not settled.empty:
            sub = settled
    # list_batches 已按 created_at DESC
    return str(sub.iloc[0]["batch_id"])


def copy_json_ready(output_root: Path) -> Tuple[bool, Dict[str, Any]]:
    copy_data = load_copy_json(output_root)
    races = list((copy_data or {}).get("races") or [])
    if not races:
        return False, copy_data or {}
    return True, copy_data




def _republish_ad_package_with_ai(output_root: Path, *, notify: bool = True) -> Dict[str, Any]:
    """AI 文案落盤後重建廣告包，令 /v1/ads/latest 同時有海報 + AI 精選。"""
    try:
        from ad_package import publish_ad_package_after_outputs

        return publish_ad_package_after_outputs(
            output_root=Path(output_root), notify=notify
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def run_auto_social_copy(
    *,
    racing_date: str,
    course: str,
    batch_id: Optional[str] = None,
    output_root: Optional[Path] = None,
    tone: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    賽前 AI 社交文案。依賴 ad_output/copy.json（快照後海報產物）。
    """
    out_root = Path(output_root) if output_root else default_output_dir()
    d, c = str(racing_date)[:10], str(course or "").upper()
    bid = batch_id or resolve_meeting_batch_id(d, c) or ""
    tone_key = normalize_tone(tone or DEFAULT_AD_TONE)

    if not force and bid and job_done_for_batch(out_root, d, c, "social", bid):
        pkg = _republish_ad_package_with_ai(out_root, notify=True)
        return {
            "ok": True,
            "skipped": True,
            "reason": "social copy already archived for batch",
            "batch_id": bid,
            "racing_date": d,
            "course": c,
            "ad_package": pkg,
        }

    ready, copy_data = copy_json_ready(out_root)
    if not ready:
        return {
            "ok": False,
            "waiting": True,
            "error": "copy.json 尚未就緒（請先完成快照／海報）",
            "batch_id": bid,
            "racing_date": d,
            "course": c,
        }

    # copy.json 的 meeting.batch_id 若存在且與目標不符，仍可產（單目錄覆蓋模式），但標註
    copy_bid = str(((copy_data.get("meeting") or {}) if copy_data else {}).get("batch_id") or "")
    if bid and copy_bid and copy_bid != bid:
        # 目錄內是另一賽日海報 — 仍允許 force；否則 waiting 避免錯配文案
        if not force:
            return {
                "ok": False,
                "waiting": True,
                "error": f"copy.json batch {copy_bid} ≠ target {bid}",
                "batch_id": bid,
                "racing_date": d,
                "course": c,
            }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "batch_id": bid or copy_bid,
            "racing_date": d,
            "course": c,
            "tone": tone_key,
        }

    writer = AdSocialCopywriter()
    if not writer.is_ready():
        return {
            "ok": False,
            "waiting": False,
            "error": "尚未設定 OPENAI_API_KEY",
            "batch_id": bid or copy_bid,
            "racing_date": d,
            "course": c,
        }

    try:
        social = writer.generate_social_copy(copy_data, tone=tone_key)
    except Exception as e:
        return {
            "ok": False,
            "waiting": False,
            "error": str(e),
            "batch_id": bid or copy_bid,
            "racing_date": d,
            "course": c,
        }

    use_bid = bid or copy_bid
    social["meeting"] = {
        "batch_id": use_bid,
        "racing_date": d,
        "course": c,
        "generated_at": _utcnow_iso(),
        "kind": "pre_race_social",
    }
    social_path = save_social_copy(out_root, social)
    archived = write_archive_version(out_root, d, c, "social", social)
    pkg = _republish_ad_package_with_ai(out_root, notify=True)
    return {
        "ok": True,
        "batch_id": use_bid,
        "racing_date": d,
        "course": c,
        "tone": tone_key,
        "source": social.get("source"),
        "n_featured": len(list(social.get("featured") or [])),
        "social_copy": str(social_path),
        "archive": archived,
        "ad_package": pkg,
    }


def promo_hits_to_dict(
    race_df,
    summary_df,
    meta: Dict[str, Any],
    *,
    racing_date: str,
    course: str,
) -> Dict[str, Any]:
    races: List[Dict[str, Any]] = []
    if race_df is not None and not getattr(race_df, "empty", True):
        for row in race_df.to_dict(orient="records"):
            detail = row.get("推介明細")
            if not isinstance(detail, list):
                detail = []
            races.append(
                {
                    "racing_date": str(row.get("賽日") or racing_date)[:10],
                    "course": str(row.get("場地") or course),
                    "batch_id": str(row.get("batch_id") or ""),
                    "race_id": str(row.get("race_id") or ""),
                    "n_picks": int(row.get("推介數") or 0),
                    "picks": str(row.get("推介") or ""),
                    "picks_detail": detail,
                    "win_odds7": bool(row.get("WIN≥7")),
                    "qin_odds10": bool(row.get("冠亞+賠>10")),
                    "t3_cover": bool(row.get("T3覆蓋")),
                    "t4_cover": bool(row.get("T4覆蓋")),
                    "any_promo": bool(row.get("可宣傳")),
                }
            )
    summary: List[Dict[str, Any]] = []
    if summary_df is not None and not getattr(summary_df, "empty", True):
        summary = summary_df.to_dict(orient="records")
    return {
        "meeting": {
            "racing_date": str(racing_date)[:10],
            "course": str(course).upper(),
            "batch_id": (meta or {}).get("batch_ids", [None])[0]
            if (meta or {}).get("batch_ids")
            else "",
            "batch_ids": list((meta or {}).get("batch_ids") or []),
            "generated_at": _utcnow_iso(),
            "kind": "promo_hits",
        },
        "meta": dict(meta or {}),
        "n_promo_races": int((meta or {}).get("n_promo_races") or 0),
        "n_races_scored": int((meta or {}).get("n_races_scored") or 0),
        "races": races,
        "promo_races": [r for r in races if r.get("any_promo")],
        "summary": summary,
    }


def run_auto_promo_hits(
    *,
    racing_date: str,
    course: str,
    batch_ids: Optional[Sequence[str]] = None,
    output_root: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """賽後宣傳評估；寫 promo_hits.json ＋ archive。"""
    out_root = Path(output_root) if output_root else default_output_dir()
    d, c = str(racing_date)[:10], str(course or "").upper()
    ids = [str(x) for x in (batch_ids or []) if x]
    if not ids:
        bid = resolve_meeting_batch_id(d, c, prefer_settled=True)
        if bid:
            ids = [bid]
    primary = ids[0] if ids else ""

    if not force and primary and job_done_for_batch(out_root, d, c, "promo_hits", primary):
        existing = load_archive_latest(out_root, d, c, "promo_hits")
        return {
            "ok": True,
            "skipped": True,
            "reason": "promo hits already archived for batch",
            "batch_id": primary,
            "batch_ids": ids,
            "n_promo_races": int(existing.get("n_promo_races") or 0),
            "racing_date": d,
            "course": c,
            "promo": existing,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "batch_id": primary,
            "batch_ids": ids,
            "racing_date": d,
            "course": c,
        }

    if not ids:
        return {
            "ok": False,
            "waiting": True,
            "error": "尚無已結算快照 batch",
            "racing_date": d,
            "course": c,
        }

    try:
        from factor_calibration import FactorCalibration

        cal = FactorCalibration()
        race_df, summary_df, meta = cal.evaluate_ad_promo_hits(
            batch_ids=ids, only_settled=True
        )
    except Exception as e:
        return {
            "ok": False,
            "waiting": False,
            "error": str(e),
            "batch_id": primary,
            "racing_date": d,
            "course": c,
        }

    if meta.get("error"):
        err = str(meta.get("error"))
        waiting = "尚無" in err or "尚未" in err
        return {
            "ok": False,
            "waiting": waiting,
            "error": err,
            "batch_id": primary,
            "racing_date": d,
            "course": c,
        }

    payload = promo_hits_to_dict(
        race_df, summary_df, meta, racing_date=d, course=c
    )
    if primary:
        payload["meeting"]["batch_id"] = primary
    out_root.mkdir(parents=True, exist_ok=True)
    promo_path = out_root / PROMO_HITS_FILE
    promo_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    archived = write_archive_version(out_root, d, c, "promo_hits", payload)
    return {
        "ok": True,
        "batch_id": primary,
        "batch_ids": ids,
        "racing_date": d,
        "course": c,
        "n_promo_races": int(payload.get("n_promo_races") or 0),
        "n_races_scored": int(payload.get("n_races_scored") or 0),
        "promo_hits": str(promo_path),
        "archive": archived,
        "promo": payload,
    }


# ----- 賽後文案 -----

POST_RACE_FOOTER_LINES: List[str] = [
    "以上為賽後模型表現回顧，只供資料研究及參考，不構成投注建議。關注 J18.HK 睇更多數據分析。未滿18歲切勿參與賭博。",
]


def post_race_footer_text() -> str:
    return "\n\n".join(POST_RACE_FOOTER_LINES)


def format_post_race_post_text(data: Dict[str, Any]) -> str:
    lines: List[str] = []
    title = str((data or {}).get("title") or "").strip()
    if title:
        lines.append(title)
    subtitle = str((data or {}).get("subtitle") or "").strip()
    if subtitle:
        lines.append(subtitle)
    if lines:
        lines.append("")

    for item in list((data or {}).get("featured") or []):
        race_no = item.get("race_no") or "?"
        horse = str(item.get("horse_name") or "").strip()
        picks = str(item.get("picks") or "").strip()
        rules = list(item.get("rules") or [])
        comment = str(item.get("comment") or "").strip()
        head = f"第{race_no}場"
        if horse:
            head += f"｜{horse}"
        elif picks:
            head += f"｜{picks}"
        lines.append(head)
        if rules:
            lines.append("命中：" + "／".join(str(r) for r in rules))
        if comment:
            lines.append(comment)
        lines.append("")

    hashtags = list((data or {}).get("hashtags") or [])
    if hashtags:
        lines.append(" ".join(str(t) for t in hashtags))
        lines.append("")

    footer = str((data or {}).get("footer") or "").strip() or post_race_footer_text()
    lines.append(footer)
    return "\n".join(lines).strip() + "\n"


def _promo_rule_labels(race: Dict[str, Any]) -> List[str]:
    labels = []
    if race.get("win_odds7"):
        labels.append("獨贏高賠")
    if race.get("qin_odds10"):
        labels.append("冠亞高賠")
    if race.get("t3_cover"):
        labels.append("T3全中")
    if race.get("t4_cover"):
        labels.append("T4全中")
    return labels


def _race_no_from_id(race_id: str) -> Optional[int]:
    s = str(race_id or "")
    if len(s) >= 2 and s[-2:].isdigit():
        try:
            return int(s[-2:])
        except ValueError:
            return None
    return None



def _primary_horse_from_race(race: Dict[str, Any]) -> str:
    detail = race.get("picks_detail") if isinstance(race.get("picks_detail"), list) else []
    for p in detail:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        no = p.get("no")
        if name:
            return f"{no} {name}".strip() if no is not None else name
    picks = str(race.get("picks") or "")
    return picks.split("/")[0].strip() if picks else ""


def _compact_promo_race(race: Dict[str, Any]) -> Dict[str, Any]:
    """結構化場次資料，供 LLM／fallback 文案使用。"""
    detail = []
    for p in list(race.get("picks_detail") or []):
        if not isinstance(p, dict):
            continue
        detail.append(
            {
                "rank": p.get("rank"),
                "no": p.get("no"),
                "name": str(p.get("name") or "").strip(),
                "finish": p.get("finish"),
                "win_odds": p.get("win_odds"),
            }
        )
    return {
        "race_id": race.get("race_id"),
        "race_no": _race_no_from_id(str(race.get("race_id") or "")),
        "picks": race.get("picks"),
        "picks_detail": detail,
        "rules": _promo_rule_labels(race),
    }

def build_post_race_fallback(promo: Dict[str, Any], *, limit: int = 3) -> Dict[str, Any]:
    promo_races = list(promo.get("promo_races") or [])
    featured: List[Dict[str, Any]] = []
    for r in promo_races[:limit]:
        compact = _compact_promo_race(r)
        rules = list(compact.get("rules") or [])
        detail = list(compact.get("picks_detail") or [])
        bits = []
        for p in detail[:4]:
            name = str(p.get("name") or "").strip() or f"#{p.get('no')}"
            fin = p.get("finish")
            odds = p.get("win_odds")
            seg = name
            if fin is not None:
                seg += f" 跑第{int(fin)}"
            if odds is not None:
                try:
                    seg += f" @{float(odds):g}"
                except (TypeError, ValueError):
                    pass
            bits.append(seg)
        detail_txt = "；".join(bits) if bits else str(r.get("picks") or "")
        if rules and detail_txt:
            comment = f"模型觀察命中「{'／'.join(rules)}」：{detail_txt}"
        elif rules:
            comment = f"模型觀察命中「{'／'.join(rules)}」，值得作為賽後研究回顧素材。"
        elif detail_txt:
            comment = f"分析場次表現達研究分享門檻：{detail_txt}"
        else:
            comment = "分析場次表現達研究分享門檻。"
        featured.append(
            {
                "race_no": compact.get("race_no"),
                "race_id": r.get("race_id"),
                "horse_name": _primary_horse_from_race(r),
                "picks": str(r.get("picks") or ""),
                "picks_detail": detail,
                "rules": rules,
                "comment": comment[:60],
                "basis": "promo_hits+picks_detail",
            }
        )
    meeting = promo.get("meeting") or {}
    d = str(meeting.get("racing_date") or "")[:10]
    c = str(meeting.get("course") or "")
    title = f"{d} {c} 賽後回顧：模型觀察命中精選".strip()
    result = {
        "title": title,
        "subtitle": f"共 {len(promo_races)} 場達宣傳門檻",
        "featured": featured,
        "hashtags": ["#J18", "#賽事數據", "#賽後回顧", "#模型分析", "#香港賽馬"],
        "footer": post_race_footer_text(),
        "footer_lines": list(POST_RACE_FOOTER_LINES),
        "tone": normalize_tone(DEFAULT_AD_TONE),
        "source": "fallback",
        "n_promo_races": len(promo_races),
    }
    result["post_text"] = format_post_race_post_text(result)
    return result


def generate_post_race_copy(
    promo: Dict[str, Any],
    *,
    tone: Optional[str] = None,
    writer: Optional[AdSocialCopywriter] = None,
) -> Dict[str, Any]:
    """
    依可宣傳場次生成賽後文案。LLM 失敗則本地 fallback。
    """
    promo_races = list(promo.get("promo_races") or [])
    if not promo_races:
        raise ValueError("無可宣傳場次，不產生賽後文案")

    tone_key = normalize_tone(tone or DEFAULT_AD_TONE)
    meeting = promo.get("meeting") or {}

    # 無 API key → 直接 fallback
    w = writer or AdSocialCopywriter()
    if not w.is_ready():
        out = build_post_race_fallback(promo)
        out["tone"] = tone_key
        out["source"] = "fallback:no_api_key"
        return out

    compact = [_compact_promo_race(r) for r in promo_races[:8]]

    system = (
        "你是香港公開賽事數據研究平台的社交媒體文案編輯（J18），負責寫「賽後模型表現回顧」貼文。\n"
        "根據可宣傳嘅模型命中場次（含每匹分析名單馬嘅名次 finish、獨贏賠率 win_odds、馬名），挑選最多 3 場寫研究向短評。\n"
        "必須用香港繁體／港式社交文；必須忠於提供嘅名次／賠率，不可虛構；不可誇大成穩膽必中；禁止心水／貼士／投注誘導用詞。\n"
        "嚴格輸出 JSON：\n"
        "{\n"
        '  "title": "...",\n'
        '  "subtitle": "...",\n'
        '  "featured": [\n'
        "    {\n"
        '      "race_no": 1,\n'
        '      "race_id": "...",\n'
        '      "horse_name": "重點馬或推介摘要",\n'
        '      "picks": "原推介字串",\n'
        '      "rules": ["獨贏高賠"],\n'
        '      "comment": "60字內賽後短評",\n'
        '      "basis": "為何值得宣傳"\n'
        "    }\n"
        "  ],\n"
        '  "hashtags": ["#J18", "#賽事數據", "#賽後回顧"]\n'
        "}\n"
    )
    user = json.dumps(
        {
            "meeting": meeting,
            "promo_races": compact,
            "tone": tone_key,
            "instruction": "挑選最多 3 場；comment 必須引用 picks_detail 的名次／賠率／馬名，忠於命中規則，港式繁體。",
        },
        ensure_ascii=False,
    )

    source = "llm"
    try:
        parsed = w._chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.45,
        )
    except Exception as e:
        out = build_post_race_fallback(promo)
        out["tone"] = tone_key
        out["source"] = f"fallback:{e}"
        return out

    featured_raw = parsed.get("featured") if isinstance(parsed, dict) else None
    featured: List[Dict[str, Any]] = []
    if isinstance(featured_raw, list):
        for item in featured_raw[:3]:
            if not isinstance(item, dict):
                continue
            featured.append(
                {
                    "race_no": item.get("race_no"),
                    "race_id": item.get("race_id"),
                    "horse_name": str(item.get("horse_name") or "").strip(),
                    "picks": str(item.get("picks") or "").strip(),
                    "rules": list(item.get("rules") or []),
                    "comment": str(item.get("comment") or "").strip()[:60],
                    "basis": str(item.get("basis") or "").strip(),
                }
            )
    if not featured:
        out = build_post_race_fallback(promo)
        out["tone"] = tone_key
        out["source"] = "fallback:empty_featured"
        return out

    hashtags = parsed.get("hashtags") if isinstance(parsed.get("hashtags"), list) else []
    clean_tags: List[str] = []
    for tag in hashtags:
        s = str(tag or "").strip()
        if not s:
            continue
        if not s.startswith("#"):
            s = "#" + s.lstrip("#")
        if s not in clean_tags:
            clean_tags.append(s)
    for default_tag in ("#J18", "#賽事數據", "#賽後回顧", "#模型分析"):
        if default_tag not in clean_tags:
            clean_tags.append(default_tag)

    d = str(meeting.get("racing_date") or "")[:10]
    c = str(meeting.get("course") or "")
    title = str(parsed.get("title") or "").strip() or f"{d} {c} 賽後回顧".strip()
    result = {
        "title": title,
        "subtitle": str(parsed.get("subtitle") or "").strip(),
        "featured": featured,
        "hashtags": clean_tags[:15],
        "footer": post_race_footer_text(),
        "footer_lines": list(POST_RACE_FOOTER_LINES),
        "tone": tone_key,
        "source": source,
        "n_promo_races": len(promo_races),
        "raw": parsed,
    }
    result["post_text"] = format_post_race_post_text(result)
    return result


def run_auto_post_race_copy(
    *,
    racing_date: str,
    course: str,
    promo: Optional[Dict[str, Any]] = None,
    batch_id: Optional[str] = None,
    output_root: Optional[Path] = None,
    tone: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """賽後文案：需 promo 有 any_promo 場次。"""
    out_root = Path(output_root) if output_root else default_output_dir()
    d, c = str(racing_date)[:10], str(course or "").upper()
    tone_key = normalize_tone(tone or DEFAULT_AD_TONE)

    payload = promo
    if payload is None:
        payload = load_archive_latest(out_root, d, c, "promo_hits")
    if not payload:
        promo_file = out_root / PROMO_HITS_FILE
        if promo_file.is_file():
            try:
                payload = json.loads(promo_file.read_text(encoding="utf-8"))
            except Exception:
                payload = {}

    bid = (
        batch_id
        or _meeting_batch_id(payload or {})
        or resolve_meeting_batch_id(d, c, prefer_settled=True)
        or ""
    )

    if not force and bid and job_done_for_batch(out_root, d, c, "post_race", bid):
        return {
            "ok": True,
            "skipped": True,
            "reason": "post_race copy already archived for batch",
            "batch_id": bid,
            "racing_date": d,
            "course": c,
        }

    n_promo = int((payload or {}).get("n_promo_races") or 0)
    promo_races = list((payload or {}).get("promo_races") or [])
    if n_promo <= 0 and not promo_races:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no promo races — skip post_race copy",
            "batch_id": bid,
            "n_promo_races": 0,
            "racing_date": d,
            "course": c,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "batch_id": bid,
            "n_promo_races": n_promo or len(promo_races),
            "racing_date": d,
            "course": c,
            "tone": tone_key,
        }

    try:
        copy_data = generate_post_race_copy(payload or {}, tone=tone_key)
    except Exception as e:
        return {
            "ok": False,
            "waiting": False,
            "error": str(e),
            "batch_id": bid,
            "racing_date": d,
            "course": c,
        }

    copy_data["meeting"] = {
        "batch_id": bid,
        "racing_date": d,
        "course": c,
        "generated_at": _utcnow_iso(),
        "kind": "post_race_social",
        "n_promo_races": n_promo or len(promo_races),
    }
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / POST_RACE_COPY_FILE
    path.write_text(json.dumps(copy_data, ensure_ascii=False, indent=2), encoding="utf-8")
    archived = write_archive_version(out_root, d, c, "post_race", copy_data)
    return {
        "ok": True,
        "batch_id": bid,
        "racing_date": d,
        "course": c,
        "tone": tone_key,
        "source": copy_data.get("source"),
        "n_featured": len(list(copy_data.get("featured") or [])),
        "n_promo_races": n_promo or len(promo_races),
        "post_race_copy": str(path),
        "archive": archived,
    }



ARCHIVE_KINDS = ("copy", "social", "promo_hits", "post_race")


def archive_copy_payload(
    output_root: Path,
    *,
    racing_date: str,
    course: str,
    copy_data: Dict[str, Any],
    batch_id: str = "",
) -> Dict[str, str]:
    """
    歸檔海報生成資料（copy.json 內容），不存 PNG。
    之後可用同一份 JSON 重產海報。
    """
    d, c = str(racing_date)[:10], str(course or "").upper()
    meeting = dict((copy_data or {}).get("meeting") or {})
    if batch_id:
        meeting["batch_id"] = batch_id
    meeting.setdefault("racing_date", d)
    meeting.setdefault("course", c)
    meeting["kind"] = "copy"
    meeting["poster_archived"] = False
    payload = {
        "meeting": meeting,
        "fused_copy": (copy_data or {}).get("fused_copy"),
        "races": list((copy_data or {}).get("races") or []),
        "assets": {
            "poster_file": "fused.png",
            "poster_archived": False,
            "note": "archive 只保存生成資料；海報需由 copy 重產",
        },
        "archived_at": _utcnow_iso(),
    }
    return write_archive_version(output_root, d, c, "copy", payload)


def list_archive_meetings(output_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """掃描 archive/ 下各賽日，回傳可瀏覽摘要（唔含 PNG）。"""
    root = Path(output_root) if output_root else default_output_dir()
    base = root / "archive"
    if not base.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for meeting_dir in sorted(base.iterdir(), reverse=True):
        if not meeting_dir.is_dir():
            continue
        name = meeting_dir.name  # YYYY-MM-DD_COURSE
        if "_" not in name:
            continue
        d, c = name.rsplit("_", 1)
        kinds: Dict[str, Any] = {}
        for kind in ARCHIVE_KINDS:
            latest = load_archive_latest(root, d, c, kind)
            if not latest:
                continue
            meeting = latest.get("meeting") if isinstance(latest.get("meeting"), dict) else {}
            kinds[kind] = {
                "batch_id": _meeting_batch_id(latest),
                "generated_at": meeting.get("generated_at")
                or meeting.get("archived_at")
                or latest.get("archived_at")
                or "",
                "n_promo_races": latest.get("n_promo_races"),
                "n_featured": len(list(latest.get("featured") or [])),
                "n_races": len(list(latest.get("races") or [])),
                "path": str(archive_latest_path(root, d, c, kind)),
                "poster_archived": bool(
                    ((latest.get("assets") or {}) if isinstance(latest.get("assets"), dict) else {}).get(
                        "poster_archived"
                    )
                ),
            }
        if not kinds:
            continue
        rows.append(
            {
                "racing_date": d,
                "course": c,
                "label": f"{d} {c}",
                "kinds": kinds,
                "dir": str(meeting_dir),
            }
        )
    return rows


def redo_archive_job(
    *,
    kind: str,
    racing_date: str,
    course: str,
    batch_id: str = "",
    output_root: Optional[Path] = None,
    tone: Optional[str] = None,
) -> Dict[str, Any]:
    """UI／CLI 強制重做某一類廣告產出（force=True）。"""
    k = str(kind or "").strip()
    d, c = str(racing_date)[:10], str(course or "").upper()
    out_root = Path(output_root) if output_root else default_output_dir()
    if k == "social":
        return run_auto_social_copy(
            racing_date=d, course=c, batch_id=batch_id or None,
            output_root=out_root, tone=tone, force=True,
        )
    if k == "promo_hits":
        bids = [batch_id] if batch_id else None
        return run_auto_promo_hits(
            racing_date=d, course=c, batch_ids=bids,
            output_root=out_root, force=True,
        )
    if k == "post_race":
        return run_auto_post_race_copy(
            racing_date=d, course=c, batch_id=batch_id or None,
            output_root=out_root, tone=tone, force=True,
        )
    if k == "cascade":
        bids = [batch_id] if batch_id else None
        return run_post_race_ad_cascade(
            racing_date=d, course=c, batch_ids=bids,
            output_root=out_root, force=True,
        )
    if k == "copy":
        return {
            "ok": False,
            "error": "copy／海報請用「廣告輸出 → 手動重產」由快照重產；archive 只保存生成資料",
        }
    return {"ok": False, "error": f"unknown kind: {kind}"}


def run_post_race_ad_cascade(
    *,
    racing_date: str,
    course: str,
    batch_ids: Optional[Sequence[str]] = None,
    output_root: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
    auto_promo: bool = True,
    auto_copy: bool = True,
) -> Dict[str, Any]:
    """SETTLED 後一站：promo hits →（可選）post_race copy。"""
    out: Dict[str, Any] = {
        "racing_date": str(racing_date)[:10],
        "course": str(course).upper(),
        "actions": [],
    }
    promo_result: Optional[Dict[str, Any]] = None
    if auto_promo:
        promo_result = run_auto_promo_hits(
            racing_date=racing_date,
            course=course,
            batch_ids=batch_ids,
            output_root=output_root,
            force=force,
            dry_run=dry_run,
        )
        out["actions"].append({"action": "promo_hits", **promo_result})
        out["promo_hits"] = promo_result
    if auto_copy:
        promo_payload = None
        if promo_result and promo_result.get("promo"):
            promo_payload = promo_result["promo"]
        elif promo_result and promo_result.get("skipped") and promo_result.get("promo"):
            promo_payload = promo_result["promo"]
        copy_result = run_auto_post_race_copy(
            racing_date=racing_date,
            course=course,
            promo=promo_payload,
            batch_id=(promo_result or {}).get("batch_id"),
            output_root=output_root,
            force=force,
            dry_run=dry_run,
        )
        out["actions"].append({"action": "post_race_copy", **copy_result})
        out["post_race_copy"] = copy_result
    out["ok"] = all(
        a.get("ok", True) for a in out["actions"]
    ) if out["actions"] else True
    return out
