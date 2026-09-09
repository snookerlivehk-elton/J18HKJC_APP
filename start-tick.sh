#!/bin/bash
# 賽後日 tick 入口（Railway Cron Service／阿里雲定時任務共用）
# 需已設定：USE_SQLITE=false、DATABASE_URL 或 DATABASE_URL_SYNC、JJJC_API_BASE
set -euo pipefail
cd "$(dirname "$0")"

export USE_SQLITE="${USE_SQLITE:-false}"
LOOKBACK="${MEETING_TICK_LOOKBACK_DAYS:-3}"

echo "[start-tick] $(date -u +%Y-%m-%dT%H:%M:%SZ) lookback=${LOOKBACK}"
exec python meeting_tick.py --mode post_race --lookback-days "$LOOKBACK" --json
