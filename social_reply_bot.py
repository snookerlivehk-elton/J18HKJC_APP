"""
社交留言答覆機械人（資料側）。

職責：
1. 由最新廣告包＋Form AI 組「賽事答覆上下文」
2. 經 webhook 推去負責回覆社交媒體留言嘅下游機械人
3. 亦可輸出 LLM prompt 參考文本，畀下游機械人注入 system／context

用法：
  python social_reply_bot.py push [--no-notify]
  python social_reply_bot.py prompt
  python social_reply_bot.py show
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("social_reply_bot")


def _output_root() -> Path:
    import os

    custom = (os.getenv("AD_OUTPUT_DIR") or "").strip()
    if custom:
        return Path(custom)
    try:
        from ad_poster import default_output_dir

        return default_output_dir()
    except Exception:
        return Path("ad_output")


def push_latest(*, notify: bool = True, output_root: Optional[Path] = None) -> Dict[str, Any]:
    """重建最新留言上下文並可選推送 webhook。"""
    from social_reply_context import publish_reply_context_from_latest_ad

    root = output_root or _output_root()
    result = publish_reply_context_from_latest_ad(output_root=root, notify=notify)
    if result.get("ok"):
        meta = (result.get("package") or {}).get("meta") or {}
        logger.info(
            "reply context published id=%s status=%s races=%s horses=%s ai=%s webhook=%s",
            result.get("id"),
            result.get("status"),
            meta.get("n_races"),
            meta.get("n_horses"),
            meta.get("n_ai_evals"),
            (result.get("webhook") or {}).get("ok"),
        )
    else:
        logger.warning("reply context publish failed: %s", result)
    return result


def show_latest(*, output_root: Optional[Path] = None) -> Dict[str, Any]:
    from social_reply_context import load_latest_reply_context, public_reply_payload

    pkg = load_latest_reply_context(output_root or _output_root())
    if not pkg:
        return {"ok": False, "error": "no reply context"}
    return {"ok": True, "package": public_reply_payload(pkg)}


def prompt_latest(*, output_root: Optional[Path] = None) -> str:
    from social_reply_context import (
        format_reply_context_prompt,
        load_latest_reply_context,
        publish_reply_context_from_latest_ad,
    )

    root = output_root or _output_root()
    pkg = load_latest_reply_context(root)
    if not pkg:
        # 嘗試即時由廣告包重建
        result = publish_reply_context_from_latest_ad(output_root=root, notify=False)
        pkg = result.get("package") if result.get("ok") else None
    if not pkg:
        return ""
    return format_reply_context_prompt(pkg)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="J18 社交留言答覆機械人：推送綜合推介＋AI 評價上下文"
    )
    parser.add_argument(
        "command",
        choices=["push", "show", "prompt"],
        help="push=重建並 webhook；show=印 JSON；prompt=印 LLM 參考文本",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="push 時唔發 webhook",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="覆蓋 AD_OUTPUT_DIR",
    )
    args = parser.parse_args(argv)
    root = Path(args.output_dir) if args.output_dir else _output_root()

    if args.command == "push":
        result = push_latest(notify=not args.no_notify, output_root=root)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok") else 1

    if args.command == "show":
        result = show_latest(output_root=root)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok") else 1

    text = prompt_latest(output_root=root)
    if not text:
        print("no reply context", file=sys.stderr)
        return 1
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
