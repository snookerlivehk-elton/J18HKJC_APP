#!/usr/bin/env python3
"""
由 JJJC racecard 快速組 ready 廣告包並 POST /v1/ads/ingest 去生產 Ad API。

用途：production store 被 redeploy 清空、CORN／Streamlit 未能推送時人手補推。
預設用官方評分（rating）揀每場最多 4 匹作數據觀察；有 OPENAI_API_KEY 則產粵語 AI 文案。

例：
  python ad_push_prod.py --date 2026-09-16 --course HV
  python ad_push_prod.py --date 2026-09-16 --course HV --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass


def _jjjc_base() -> str:
    return (
        os.getenv("JJJC_API_BASE")
        or os.getenv("JJJC_RESULTS_API_BASE")
        or "https://apicc.up.railway.app"
    ).rstrip("/")


def fetch_racecard(racing_date: str, course: str) -> Dict[str, Any]:
    import httpx

    url = f"{_jjjc_base()}/api/export/racecard"
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(url, params={"date": racing_date, "venue": course.upper()})
        resp.raise_for_status()
        return resp.json()


def _pick_runners(runners: List[Dict[str, Any]], *, limit: int = 4) -> List[Dict[str, Any]]:
    alive = [
        r
        for r in runners
        if not bool(r.get("scratched"))
        and str(r.get("status") or "").lower() not in {"scratched", "withdrawn"}
    ]

    def _rating(r: Dict[str, Any]) -> float:
        try:
            return float(r.get("rating") or 0)
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(alive, key=_rating, reverse=True)
    return ranked[:limit]


def racecard_to_payloads(
    card: Dict[str, Any], *, racing_date: str, course: str
) -> List[Any]:
    from ad_poster import PickItem, RaceAdPayload

    payloads: List[RaceAdPayload] = []
    for race in list(card.get("races") or []):
        race_no = int(race.get("race_no") or race.get("race_num") or 0)
        if race_no <= 0:
            continue
        runners = list(race.get("runners") or [])
        picks_src = _pick_runners(runners, limit=4)
        if not picks_src:
            continue
        picks: List[PickItem] = []
        for i, r in enumerate(picks_src):
            name = str(
                r.get("horse_name_ch")
                or r.get("horse_name")
                or r.get("horse_name_en")
                or ""
            ).strip()
            hno = int(r.get("horse_no") or 0)
            if not hno or not name:
                continue
            share = max(8.0, 28.0 - i * 5.0)
            picks.append(
                PickItem(
                    horse_no=hno,
                    horse_name=name,
                    share_pct=share,
                    tag="爭勝" if i == 0 else "推介",
                )
            )
        if not picks:
            continue
        rid = str(race.get("race_id") or f"{racing_date.replace('-', '')}{course}{race_no:02d}")
        payloads.append(
            RaceAdPayload(
                race_id=rid,
                racing_date=racing_date,
                course=course.upper(),
                race_num=race_no,
                race_name=str(race.get("race_name") or ""),
                distance_m=race.get("distance_m"),
                track="fused",
                model_picks=list(picks),
                ai_picks=list(picks),
                fused_picks=list(picks),
                fused_fallback_model_only=True,
            )
        )
    return payloads


def build_and_push(
    *,
    racing_date: str,
    course: str,
    output_root: Optional[Path] = None,
    notify: bool = False,
    dry_run: bool = False,
    tone: Optional[str] = None,
) -> Dict[str, Any]:
    from ad_llm_copy import AdSocialCopywriter, save_social_copy
    from ad_package import (
        build_ad_package_from_copy,
        push_ad_package_remote,
        public_payload,
    )
    from ad_poster import _write_primary_meeting_outputs, default_output_dir, load_copy_json

    d = str(racing_date)[:10]
    c = str(course or "").upper()
    out_root = Path(output_root) if output_root else default_output_dir()
    out_root.mkdir(parents=True, exist_ok=True)

    card = fetch_racecard(d, c)
    race_count = int(card.get("race_count") or len(card.get("races") or []))
    if race_count <= 0:
        return {
            "ok": False,
            "error": f"JJJC racecard empty for {d} {c}",
            "card": {"race_count": 0},
        }

    payloads = racecard_to_payloads(card, racing_date=d, course=c)
    if not payloads:
        return {"ok": False, "error": "no runners available for picks"}

    batch_id = f"jjjc_rc_{d.replace('-', '')}_{c}"
    # HV 夜馬／ST 日馬預設；可由 fixtures 覆寫
    is_day = c == "ST"
    written = _write_primary_meeting_outputs(
        payloads,
        batch_id=batch_id,
        racing_date=d,
        course=c,
        output_root=out_root,
        session="日" if is_day else "夜",
        is_day_meeting=is_day,
    )
    if not written.get("ok"):
        return {"ok": False, "error": written.get("error") or "poster write failed", "written": written}

    copy_data = load_copy_json(out_root)
    if not copy_data:
        return {"ok": False, "error": "copy.json missing after poster write"}

    writer = AdSocialCopywriter()
    social = None
    if writer.is_ready():
        social = writer.generate_social_copy(copy_data, tone=tone or "high_interaction")
        social["meeting"] = {
            "batch_id": batch_id,
            "racing_date": d,
            "course": c,
            "kind": "pre_race_social",
            "source_note": "jjjc_racecard_rating_fallback",
        }
        src = str(social.get("source") or "")
        if src.startswith("fallback:") or "LLM" in src or "失敗" in src:
            return {
                "ok": False,
                "error": f"refuse push: AI copy not from live LLM ({src[:180]})",
                "social_source": src,
            }
        save_social_copy(out_root, social)
    else:
        return {"ok": False, "error": "OPENAI_API_KEY not set — refuse ready without AI copy"}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "batch_id": batch_id,
            "n_races": len(payloads),
            "social_source": (social or {}).get("source"),
            "output_root": str(out_root),
        }

    pkg = build_ad_package_from_copy(
        copy_data,
        output_root=out_root,
        session="日" if is_day else "夜",
        is_day_meeting=is_day,
        notify=False,
        force_save=True,
    )
    remote = pkg.get("remote_push")
    if not (isinstance(remote, dict) and remote.get("ok")):
        # 強制再推一次（避免本機 save 略過 remote）
        poster_path = out_root / "packages" / f"{pkg.get('id')}.png"
        poster_bytes = poster_path.read_bytes() if poster_path.is_file() else None
        if poster_bytes is None:
            fused = out_root / "fused.png"
            poster_bytes = fused.read_bytes() if fused.is_file() else None
        remote = push_ad_package_remote(pkg, poster_png=poster_bytes, notify=notify)
        pkg["remote_push"] = remote

    return {
        "ok": bool(isinstance(remote, dict) and remote.get("ok")),
        "id": pkg.get("id"),
        "status": pkg.get("status"),
        "remote_push": remote,
        "package": public_payload(pkg) if pkg.get("status") == "ready" else None,
        "n_races": len(payloads),
        "batch_id": batch_id,
        "facebook_preview": ((pkg.get("copy") or {}).get("facebook") or "")[:240],
        "poster_url": ((pkg.get("assets") or {}).get("poster_url") or ""),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build + push ready ad package to production")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--course", required=True, help="ST or HV")
    parser.add_argument("--output-dir", default="", help="ad_output override")
    parser.add_argument("--notify", action="store_true", help="also fire webhook after ingest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tone", default="high_interaction")
    args = parser.parse_args(argv)

    # 本機推送唔好硬打 railway.internal DB
    os.environ.setdefault("USE_SQLITE", "true")
    os.environ.setdefault("AD_STORE_ENABLED", "true")
    # 等 AI 文案齊備先 publish／ingest，避免 pending 包搶先上生產
    os.environ["AD_SKIP_AUTO_PUBLISH"] = "1"

    out = build_and_push(
        racing_date=args.date,
        course=args.course,
        output_root=Path(args.output_dir) if args.output_dir else None,
        notify=bool(args.notify),
        dry_run=bool(args.dry_run),
        tone=args.tone,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
