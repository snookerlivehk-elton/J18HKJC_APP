#!/bin/bash
# 只啟動網頁；歷史更新交給 GitHub Actions / 手動批次，避免每次 deploy 重爬整年
# 公開賽日速覽（無需登入）：/?view=raceday
# 輕量 HTML 嵌入另見 start-raceday-embed.sh 或 Ad/Prediction API 的 /embed/raceday
streamlit run ui_app.py --server.port "${PORT:-8501}" --server.address 0.0.0.0
