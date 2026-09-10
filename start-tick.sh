#!/bin/bash
# 賽日 tick 入口（Railway Cron Service／阿里雲定時任務共用）
# 預設 mode=all（賽前＋賽後）；可用 MEETING_TICK_MODE=pre_race|post_race|all 覆寫
# 需已設定：USE_SQLITE=false、DATABASE_URL 或 DATABASE_URL_SYNC、JJJC_API_BASE
set -euo pipefail
cd "$(dirname "$0")"

export USE_SQLITE="${USE_SQLITE:-false}"
MODE="${MEETING_TICK_MODE:-all}"
LOOKBACK="${MEETING_TICK_LOOKBACK_DAYS:-3}"
LOOKAHEAD="${MEETING_TICK_LOOKAHEAD_DAYS:-3}"

echo "[start-tick] $(date -u +%Y-%m-%dT%H:%M:%SZ) mode=${MODE} lookback=${LOOKBACK} lookahead=${LOOKAHEAD}"
exec python meeting_tick.py \
  --mode "${MODE}" \
  --lookback-days "${LOOKBACK}" \
  --lookahead-days "${LOOKAHEAD}" \
  --json
