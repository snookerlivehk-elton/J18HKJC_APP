#!/usr/bin/env python3
"""補回／重算 hit_rate_day_snapshots（總命中率日快照）。

用法：
  python backfill_hit_snapshots.py
  python backfill_hit_snapshots.py --all          # 覆寫全部
  python backfill_hit_snapshots.py --batch ID
"""
from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

from factor_calibration import FactorCalibration


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Backfill hit_rate_day_snapshots")
    p.add_argument("--all", action="store_true", help="覆寫全部已結算（預設只補缺）")
    p.add_argument("--batch", action="append", dest="batches", help="指定 batch_id（可多次）")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    cal = FactorCalibration()
    out = cal.backfill_hit_rate_snapshots(
        only_missing=not args.all,
        batch_ids=args.batches,
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(
            f"ok={out.get('ok')} done={out.get('n_done')} skip={out.get('n_skip')}"
        )
        for d in out.get("details") or []:
            if not d.get("ok"):
                print("  fail:", d)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
