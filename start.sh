#!/bin/bash
# 啟動網頁服務
streamlit run ui_app.py --server.port $PORT --server.address 0.0.0.0 &

# 在背景啟動歷史資料爬蟲 (設定抓取 2024-01-01 到今天的資料)
# 加上 nohup 和 & 讓它在背景默默執行，不會干擾網頁服務
nohup python batch_crawler.py --start 2024-01-01 --end $(date +%Y-%m-%d) > crawler.log 2>&1 &

# 讓主程序保持運行，避免容器關閉
wait -n
