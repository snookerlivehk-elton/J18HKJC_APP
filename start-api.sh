#!/bin/bash
# Railway 第二個服務：賽前預測 API（勿與 Streamlit 共用同一 process）
uvicorn prediction_api:app --host 0.0.0.0 --port $PORT
