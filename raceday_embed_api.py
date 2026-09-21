"""
賽日速覽公開嵌入 API（無需登入）。

路由：
  GET /embed/raceday          → 電腦版 HTML（專為 j18.hk/pc 右手邊 iframe）
  GET /embed/raceday-pc       → 開發用：整頁複製 pc.j18.hk 排版的賽日速覽（不取代上者）
  GET /embed/racecard         → 排位表設計稿（左鎖馬號／檔／賠，右滑其餘欄）
  GET /embed/api/health
  GET /embed/api/meetings
  GET /embed/api/races/{id}

掛入：
  prediction_api / ad_api 呼叫 mount_raceday_embed(app)
  或獨立：uvicorn raceday_embed_api:app --port $PORT
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app_version import get_version
from raceday_embed_payload import (
    build_public_meetings,
    build_public_race_view,
    default_meeting_selection,
    health_payload,
)

_ROOT = Path(__file__).resolve().parent
_HTML_PATH = _ROOT / "static" / "raceday_embed.html"
_PC_HTML_PATH = _ROOT / "static" / "raceday_pc.html"
_RACECARD_HTML_PATH = _ROOT / "static" / "racecard_board.html"

# 允許被 j18.hk PC 頁 iframe 嵌入
_FRAME_ANCESTORS = os.getenv(
    "RACEDAY_EMBED_FRAME_ANCESTORS",
    "https://j18.hk http://j18.hk https://*.j18.hk http://localhost:* http://127.0.0.1:*",
)


def _embed_headers() -> dict:
    # 只用 CSP frame-ancestors（勿設 X-Frame-Options，以免擋 j18.hk iframe）
    return {
        "Content-Security-Policy": f"frame-ancestors {_FRAME_ANCESTORS}",
        "Cache-Control": "no-store",
    }


def _read_html() -> str:
    if _HTML_PATH.is_file():
        return _HTML_PATH.read_text(encoding="utf-8")
    return "<!DOCTYPE html><html><body><p>raceday_embed.html missing</p></body></html>"


def _read_pc_html() -> str:
    if _PC_HTML_PATH.is_file():
        html = _PC_HTML_PATH.read_text(encoding="utf-8")
    else:
        html = "<!DOCTYPE html><html><body><p>raceday_pc.html missing</p></body></html>"
    # 同機部署時留空（相對路徑）。僅當明確設 RACEDAY_PC_API_BASE 才注入外站。
    api_base = (os.getenv("RACEDAY_PC_API_BASE") or "").rstrip("/")
    return html.replace("__API_BASE__", api_base)


def mount_raceday_embed(app: FastAPI) -> None:
    """把公開嵌入路由掛到既有 FastAPI app。"""

    @app.get("/embed/raceday", response_class=HTMLResponse, include_in_schema=False)
    def embed_raceday_page():
        html = _read_html().replace("__APP_VERSION__", get_version())
        return HTMLResponse(content=html, headers=_embed_headers())

    @app.get("/embed/raceday-pc", response_class=HTMLResponse, include_in_schema=False)
    def embed_raceday_pc_page():
        """獨立開發頁：pc.j18.hk 風格整頁排版，不改動 /embed/raceday。"""
        html = _read_pc_html().replace("__APP_VERSION__", get_version())
        return HTMLResponse(content=html, headers=_embed_headers())

    @app.get("/embed/racecard", response_class=HTMLResponse, include_in_schema=False)
    def embed_racecard_board():
        """排位表設計稿：左鎖馬號／馬名／檔／賠，右滑其餘欄，點表頭整行排序。"""
        if _RACECARD_HTML_PATH.is_file():
            html = _RACECARD_HTML_PATH.read_text(encoding="utf-8")
        else:
            html = "<!DOCTYPE html><html><body><p>racecard_board.html missing</p></body></html>"
        return HTMLResponse(content=html, headers=_embed_headers())

    @app.get("/embed/api/health")
    def embed_health():
        return JSONResponse(health_payload(get_version()), headers=_embed_headers())

    @app.get("/embed/api/meetings")
    def embed_meetings(
        date: Optional[str] = Query(None, description="YYYY-MM-DD"),
        course: Optional[str] = Query(None, description="ST 或 HV"),
    ):
        return JSONResponse(
            build_public_meetings(date, course),
            headers=_embed_headers(),
        )

    @app.get("/embed/api/default")
    def embed_default():
        return JSONResponse(default_meeting_selection(), headers=_embed_headers())

    @app.get("/embed/api/races/{race_id}")
    def embed_race(race_id: str):
        try:
            payload = build_public_race_view(race_id)
        except Exception as exc:  # noqa: BLE001 — 公開頁勿 500 空白
            payload = {
                "ok": False,
                "error": "race_view_failed",
                "detail": str(exc)[:240],
                "race_id": race_id,
            }
        status = 200 if payload.get("ok") else 404
        return JSONResponse(payload, status_code=status, headers=_embed_headers())


def create_app() -> FastAPI:
    app = FastAPI(
        title="J18 Race Day Embed",
        version=get_version(),
        description="賽日速覽公開頁（j18.hk/pc 右手邊嵌入，無需登入）",
    )
    cors = os.getenv("PREDICTION_API_CORS") or os.getenv("AD_API_CORS") or "*"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def strip_xfo(request, call_next):
        resp: Response = await call_next(request)
        # 確保可被跨域 iframe（覆寫框架預設）
        if request.url.path.startswith("/embed"):
            resp.headers["Content-Security-Policy"] = (
                f"frame-ancestors {_FRAME_ANCESTORS}"
            )
            if "x-frame-options" in resp.headers:
                del resp.headers["x-frame-options"]
        return resp

    mount_raceday_embed(app)

    @app.get("/health")
    def health():
        return health_payload(get_version())

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8010"))
    uvicorn.run("raceday_embed_api:app", host="0.0.0.0", port=port, reload=False)
