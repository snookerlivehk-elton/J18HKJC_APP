"""
應用版本管理。

單一真相：倉庫根目錄 `VERSION`（語意化 MAJOR.MINOR.PATCH）。
發佈／功能合入時請手動 bump；UI 與 prediction_api 皆由此讀取。

可選覆寫：環境變數 `APP_VERSION`（部署熱修時用，不改檔）。
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent
_VERSION_FILE = _ROOT / "VERSION"
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")


def _read_version_file() -> str:
    try:
        raw = _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    # 只取第一行非空、非註解
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return line
    return "0.0.0"


@lru_cache(maxsize=1)
def get_version() -> str:
    """回傳語意化版本字串，例如 `1.1.0`。"""
    env = (os.getenv("APP_VERSION") or "").strip()
    if env:
        return env.lstrip("vV")
    return _read_version_file().lstrip("vV")


def get_version_display(*, prefix: str = "v") -> str:
    """UI 用：預設 `v1.1.0`。"""
    ver = get_version()
    if prefix and not ver.lower().startswith("v"):
        return f"{prefix}{ver}"
    return ver


def parse_semver(ver: Optional[str] = None) -> tuple[int, int, int]:
    v = (ver or get_version()).lstrip("vV")
    m = _SEMVER_RE.match(v)
    if not m:
        return (0, 0, 0)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


# 模組級別名（供 `from app_version import __version__`）
__version__ = get_version()
