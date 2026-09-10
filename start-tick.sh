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

if [ "${USE_SQLITE}" != "true" ]; then
  if [ -z "${DATABASE_URL:-}" ] && [ -z "${DATABASE_URL_SYNC:-}" ]; then
    echo "[start-tick] FATAL: USE_SQLITE=${USE_SQLITE} 但未設定 DATABASE_URL／DATABASE_URL_SYNC" >&2
    echo "[start-tick] Railway：在 Cron service Variables 用 Postgres 的 DATABASE_URL（Reference）" >&2
    exit 1
  fi
fi

# 除錯：只印 host，不印密碼
DB_HINT="${DATABASE_URL_SYNC:-${DATABASE_URL:-sqlite}}"
DB_HOST=$(python -c "from urllib.parse import urlparse; u=urlparse('''${DB_HINT}'''.split('?')[0]); print(u.hostname or u.path or 'unknown')" 2>/dev/null || echo "unknown")
echo "[start-tick] $(date -u +%Y-%m-%dT%H:%M:%SZ) mode=${MODE} lookback=${LOOKBACK} lookahead=${LOOKAHEAD} use_sqlite=${USE_SQLITE} db_host=${DB_HOST}"

exec python meeting_tick.py \
  --mode "${MODE}" \
  --lookback-days "${LOOKBACK}" \
  --lookahead-days "${LOOKAHEAD}" \
  --json
