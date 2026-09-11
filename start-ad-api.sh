#!/bin/bash
# Railway：廣告／賽前預測產出 API（可與 Streamlit／prediction_api 分開服務）
# Start Command: bash start-ad-api.sh
uvicorn ad_api:app --host 0.0.0.0 --port "${PORT:-8001}"
