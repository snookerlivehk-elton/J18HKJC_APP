#!/usr/bin/env bash
# 阿里雲賽日自動鏈診斷（在 ECS 上執行）
#   bash scripts/aliyun_tick_doctor.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== j18-meeting-tick.timer ==="
if systemctl list-unit-files j18-meeting-tick.timer &>/dev/null; then
  systemctl is-enabled j18-meeting-tick.timer || true
  systemctl is-active j18-meeting-tick.timer || true
  systemctl list-timers j18-meeting-tick.timer --no-pager || true
else
  echo "WARN: unit j18-meeting-tick.timer 不存在 — 請確認 systemd 單元已安裝"
fi

echo
echo "=== 最近 tick 日誌（service）==="
journalctl -u j18-meeting-tick.service -n 40 --no-pager 2>/dev/null || \
  echo "WARN: 無 journal（可改看 /var/log/j18_meeting_tick.log）"
if [ -f /var/log/j18_meeting_tick.log ]; then
  echo "--- /var/log/j18_meeting_tick.log (tail) ---"
  tail -n 40 /var/log/j18_meeting_tick.log || true
fi

echo
echo "=== 環境變數（只顯示是否已設，不印值）==="
for k in DATABASE_URL DATABASE_URL_SYNC JJJC_API_BASE OPENAI_API_KEY OPENAI_BASE_URL OPENAI_MODEL; do
  if [ -n "${!k:-}" ]; then
    echo "  $k=set"
  else
    # 嘗試從 .env 讀
    if [ -f .env ] && grep -qE "^${k}=" .env; then
      echo "  $k=set(.env)"
    else
      echo "  $k=MISSING"
    fi
  fi
done

echo
echo "=== 建議 ==="
echo "1) timer 非 active → sudo systemctl enable --now j18-meeting-tick.timer"
echo "2) 合併 harden PR 後 → cd 本倉 && git pull && 下一次 timer 會自動帶新 SG/FG auto-fetch"
echo "3) 今日若 Form AI 仍停 → 作戰室勾「只補缺」再「後台啟動 Form AI」一次即可由 tick 續跑"
