#!/bin/bash
# 只啟動網頁；歷史更新交給 GitHub Actions / 手動批次，避免每次 deploy 重爬整年
streamlit run 系統主頁.py --server.port $PORT --server.address 0.0.0.0
