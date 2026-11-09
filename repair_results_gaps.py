#!/usr/bin/env python3
"""
補齊作戰室「無名次／賽果場次不足（需重同步 RESULTS）」缺口。

用法：
  # 掃最近 21 日缺口並修好（需 DATABASE_URL）
  python repair_results_gaps.py

  # 指定賽日
  python repair_results_gaps.py --date 2026-11-04 --course HV

  # 只列缺口
  python repair_results_gaps.py --list-only --max-age-days 30
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Repair RESULTS gaps (無名次／半空賽果)"
    )
    p.add_argument("--date", dest="racing_date", help="YYYY-MM-DD")
    p.add_argument("--course", help="ST / HV")
    p.add_argument("--list-only", action="store_true", help="只列缺口，唔寫庫")
    p.add_argument("--min-age-days", type=int, default=0)
    p.add_argument("--max-age-days", type=int, default=21)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--no-text", action="store_true", help="唔跟住 sync text-reports")
    p.add_argument("--no-sectionals", action="store_true", help="唔跟住拉 R2 分段")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    from meeting_pipeline import MeetingPipeline
    from data_audit import (
        list_meetings_needing_results_resync,
        meeting_inventory,
        repair_results_for_meeting,
    )

    pipe = MeetingPipeline()
    report: Dict[str, Any] = {"ok": True, "meetings": []}

    if args.racing_date and args.course:
        targets = [
            {
                "racing_date": str(args.racing_date)[:10],
                "course": str(args.course).upper(),
            }
        ]
    else:
        targets = list_meetings_needing_results_resync(
            pipe.engine,
            min_age_days=int(args.min_age_days),
            max_age_days=int(args.max_age_days),
            limit=int(args.limit),
        )
        report["n_candidates"] = len(targets)

    if args.list_only:
        for t in targets:
            d, c = t["racing_date"], t["course"]
            inv = meeting_inventory(pipe.engine, d, c)
            report["meetings"].append(
                {
                    "racing_date": d,
                    "course": c,
                    "inventory": {
                        k: inv.get(k)
                        for k in (
                            "race_n",
                            "finish_n",
                            "finish_ok",
                            "thin_results",
                            "gaps",
                            "status",
                        )
                    },
                }
            )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            if not report["meetings"]:
                print("無 RESULTS 缺口")
            for m in report["meetings"]:
                inv = m.get("inventory") or {}
                print(
                    f"{m['racing_date']} {m['course']}: "
                    f"race_n={inv.get('race_n')} finish_n={inv.get('finish_n')} "
                    f"gaps={inv.get('gaps')}"
                )
        return 0

    n_ok = 0
    for t in targets:
        d = str(t.get("racing_date") or "")[:10]
        c = str(t.get("course") or "").upper()
        if not d or c not in {"ST", "HV"}:
            continue
        out = repair_results_for_meeting(
            pipe,
            d,
            c,
            also_text_reports=not bool(args.no_text),
            also_sectionals=not bool(args.no_sectionals),
        )
        report["meetings"].append(out)
        if out.get("finish_ok"):
            n_ok += 1
        elif out.get("ok") is False:
            report["ok"] = False
    report["n_ok"] = n_ok
    report["n_processed"] = len(report["meetings"])

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for m in report["meetings"]:
            inv = m.get("inventory") or {}
            print(
                f"{m.get('racing_date')} {m.get('course')}: "
                f"finish_ok={m.get('finish_ok')} "
                f"race_n={inv.get('race_n')} finish_n={inv.get('finish_n')} "
                f"auto_fetched={(m.get('sync') or {}).get('auto_fetched')} "
                f"gaps={inv.get('gaps')}"
            )
        print(f"done ok={report['ok']} n_ok={n_ok}/{report['n_processed']}")

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
