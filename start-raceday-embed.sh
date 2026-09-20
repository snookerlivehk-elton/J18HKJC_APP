#!/bin/bash
# 公開「賽日速覽」嵌入頁（無需登入；專為 j18.hk/pc 右手邊 iframe）
# 開發整頁：/embed/raceday-pc （pc.j18.hk 風格，不取代 /embed/raceday）
# Start Command 例：bash start-raceday-embed.sh
uvicorn raceday_embed_api:app --host 0.0.0.0 --port "${PORT:-8010}"
