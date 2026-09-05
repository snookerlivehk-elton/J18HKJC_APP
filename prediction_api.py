"""
賽前預測 HTTP API（給外部平台展示 + 即時賠率凱利／值搏）。

啟動（Railway 建議獨立服務）：
  uvicorn prediction_api:app --host 0.0.0.0 --port $PORT

認證：Header  `X-API-Key: <PREDICTION_API_KEY>`
（環境變數 PREDICTION_API_KEY；未設定則拒絕所有受保護路由）
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

from prediction_export import (
    build_meeting_predictions,
    build_race_prediction,
    kelly_fraction,
    list_upcoming_meeting,
    parse_odds_map,
)

app = FastAPI(
    title="J18 Pre-race Prediction API",
    version="1.0.0",
    description=(
        "賽前預測 JSON：model_win_prob 供展示與 Kelly。"
        "外部傳入小數獨贏賠率後回傳 kelly_fraction / edge_vs_market。"
    ),
)

_cors = os.getenv("PREDICTION_API_CORS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    expected = (os.getenv("PREDICTION_API_KEY") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="PREDICTION_API_KEY not configured on server",
        )
    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return True


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "j18-prediction-api",
        "auth_configured": bool((os.getenv("PREDICTION_API_KEY") or "").strip()),
    }


@app.get("/v1/meetings", dependencies=[Depends(require_api_key)])
def get_meetings(
    date: Optional[str] = Query(None, description="YYYY-MM-DD；省略＝全部即將舉行"),
    course: Optional[str] = Query(None, description="ST 或 HV"),
):
    """即將舉行的賽日／場次清單。"""
    return list_upcoming_meeting(date, course)


@app.get("/v1/races/{race_id}/prediction", dependencies=[Depends(require_api_key)])
def get_race_prediction(
    race_id: str,
    odds: Optional[str] = Query(
        None,
        description="即時獨贏小數賠率：馬號:賠率,馬號:賠率 例 3:5.5,7:8",
    ),
    kelly_scale: float = Query(
        1.0, ge=0.05, le=1.0, description="凱利縮放（0.5＝半凱利）"
    ),
    include_factors: bool = Query(True, description="是否含各因子 Z"),
):
    """單場賽前預測；可帶 odds 計算每匹 kelly_fraction。"""
    payload = build_race_prediction(
        race_id,
        win_odds=parse_odds_map(odds),
        kelly_fraction_scale=kelly_scale,
        include_factors=include_factors,
    )
    if not payload.get("ok"):
        raise HTTPException(status_code=404, detail=payload.get("error") or "not found")
    return payload


@app.get("/v1/meetings/{racing_date}/{course}/predictions", dependencies=[Depends(require_api_key)])
def get_meeting_predictions(
    racing_date: str,
    course: str,
    kelly_scale: float = Query(1.0, ge=0.05, le=1.0),
    include_factors: bool = Query(False),
):
    """整日賽會所有場次預測（較重；預設不含 factors）。"""
    return build_meeting_predictions(
        racing_date,
        course,
        kelly_fraction_scale=kelly_scale,
        include_factors=include_factors,
    )


class KellyBody(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_win_prob: float = Field(..., ge=0, le=1, description="本系統 model_win_prob")
    win_odds_decimal: float = Field(..., gt=1, description="即時小數獨贏賠率")
    kelly_scale: float = Field(1.0, ge=0.05, le=1.0)


@app.post("/v1/kelly", dependencies=[Depends(require_api_key)])
def post_kelly(body: KellyBody):
    """純計算：已知 p 與即時賠率 → 凱利倉位與 edge（不讀 DB）。"""
    p = body.model_win_prob
    o = body.win_odds_decimal
    f = kelly_fraction(p, o, fraction=body.kelly_scale)
    implied = 1.0 / o
    edge = (p / implied - 1.0) if implied > 0 else None
    return {
        "ok": True,
        "model_win_prob": p,
        "win_odds_decimal": o,
        "implied_prob": round(implied, 6),
        "edge_vs_market": round(edge, 6) if edge is not None else None,
        "kelly_fraction": f,
        "kelly_scale": body.kelly_scale,
        "formula": "f*=(b*p-q)/b ; b=o-1 ; q=1-p",
    }


class OddsBatchBody(BaseModel):
    race_id: str
    win_odds: dict = Field(..., description='{"3": 5.5, "7": 8.0} 馬號→小數賠率')
    kelly_scale: float = Field(1.0, ge=0.05, le=1.0)
    include_factors: bool = False


@app.post("/v1/races/prediction-with-odds", dependencies=[Depends(require_api_key)])
def post_prediction_with_odds(body: OddsBatchBody):
    """單場預測 + JSON body 傳入即時賠率（適合輪詢賠率後重算值搏）。"""
    odds: dict = {}
    for k, v in (body.win_odds or {}).items():
        try:
            odds[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    payload = build_race_prediction(
        body.race_id,
        win_odds=odds,
        kelly_fraction_scale=body.kelly_scale,
        include_factors=body.include_factors,
    )
    if not payload.get("ok"):
        raise HTTPException(status_code=404, detail=payload.get("error") or "not found")
    return payload


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("prediction_api:app", host="0.0.0.0", port=port, reload=False)
