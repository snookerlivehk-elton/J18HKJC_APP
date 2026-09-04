"""
批次解析 text_reports → nlp_result（供近績 NLP 補償）。

用法（本機已設 .env / Railway 變數）：
  python nlp_batch_job.py --limit 50
  python nlp_batch_job.py --limit 200 --sleep 0.3
"""
from __future__ import annotations

import argparse
import time
import sys

from dotenv import load_dotenv

load_dotenv()

from factor_calculator import FactorCalculator
from nlp_processor import NLPProcessor, DEFAULT_SYSTEM_PROMPT


def main():
    parser = argparse.ArgumentParser(description="Batch NLP parse for text_reports")
    parser.add_argument("--limit", type=int, default=50, help="本輪最多解析幾筆")
    parser.add_argument("--sleep", type=float, default=0.2, help="每筆間隔秒數（控速）")
    parser.add_argument("--dry-run", action="store_true", help="只顯示待解析數量")
    parser.add_argument(
        "--skip-trivial",
        action="store_true",
        default=True,
        help="略過空白／無特別報告（預設開）",
    )
    parser.add_argument("--no-skip-trivial", action="store_true", help="不要略過無內容")
    args = parser.parse_args()
    skip_trivial = not args.no_skip_trivial

    calc = FactorCalculator()
    status = calc.nlp_status()
    print(f"NLP status: total={status.get('total')} done={status.get('done')} pending={status.get('pending')}")

    if args.dry_run:
        return 0

    if skip_trivial:
        skipped = calc.mark_trivial_reports_skipped(limit=max(args.limit * 10, 200))
        print(f"Marked trivial skipped: {skipped}")

    processor = NLPProcessor()
    if not processor.is_ready():
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    rows = calc.load_unprocessed_reports(limit=args.limit, skip_trivial=skip_trivial)
    if rows.empty:
        print("Nothing to process.")
        return 0

    ok, fail = 0, 0
    for i, (_, row) in enumerate(rows.iterrows(), start=1):
        try:
            result = processor.analyze_report_sync(row["report_text"], DEFAULT_SYSTEM_PROMPT)
            calc.save_nlp_result(int(row["id"]), result)
            ok += 1
            print(f"[{i}/{len(rows)}] id={row['id']} ok excuse={result.get('has_excuse')} stage={result.get('excuse_stage')}")
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(rows)}] id={row['id']} FAIL: {e}", file=sys.stderr)
        if args.sleep > 0:
            time.sleep(args.sleep)

    print(f"Done. ok={ok} fail={fail}")
    print("Next: recalculate HORSE factor (homepage or Recent Form page) to fold excuses into Z.")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
