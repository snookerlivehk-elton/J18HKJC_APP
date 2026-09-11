"""
賽前預測廣告包 HTTP API。

可獨立啟動：
  uvicorn ad_api:app --host 0.0.0.0 --port $PORT

或掛入 prediction_api（同一 Railway service）。

認證：Authorization: Bearer <AD_API_KEY>
（亦接受 X-API-Key 以方便與預測 API 共用工具）
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from ad_package import (
    build_ad_package_from_copy,
    dispatch_ad_webhook,
    generate_ad_package,
    list_ad_package_ids,
    load_ad_package,
    load_latest_ad_package,
    package_paths,
    public_payload,
)
from ad_poster import default_output_dir, latest_paths, load_copy_json
from app_version import get_version

app = FastAPI(
    title="J18 Ad Package API",
    version=get_version(),
    description="賽前預測廣告包：結構化 JSON + 海報 + webhook 通知",
)

_cors = os.getenv("AD_API_CORS") or os.getenv("PREDICTION_API_CORS") or "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _expected_api_key() -> str:
    return (os.getenv("AD_API_KEY") or os.getenv("PREDICTION_API_KEY") or "").strip()


def require_ad_api_key(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> bool:
    expected = _expected_api_key()
    if not expected:
        raise HTTPException(
            status_code=503, detail="AD_API_KEY (or PREDICTION_API_KEY) not configured"
        )
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()
    if not token or token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


def _output_root() -> Path:
    custom = (os.getenv("AD_OUTPUT_DIR") or "").strip()
    return Path(custom) if custom else default_output_dir()


class GenerateBody(BaseModel):
    batch_id: Optional[str] = Field(None, description="預測快照 batch_id；可選")
    racing_date: str = Field("", description="YYYY-MM-DD；可從 copy.json 推斷")
    course: str = Field("", description="ST / HV")
    force_regen_poster: bool = Field(
        False, description="若有 batch_id，是否先重產海報"
    )
    notify: bool = Field(True, description="是否 webhook 通知外部助手")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "j18-ad-api",
        "version": get_version(),
        "auth_configured": bool(_expected_api_key()),
        "webhook_configured": bool((os.getenv("GROK_BOT_WEBHOOK_URL") or "").strip()),
    }


@app.get("/v1/ads/latest", dependencies=[Depends(require_ad_api_key)])
def get_latest_ad():
    pkg = load_latest_ad_package(_output_root())
    if not pkg or pkg.get("status") != "ready":
        raise HTTPException(status_code=404, detail="No ready ad package")
    return public_payload(pkg)


@app.get("/v1/ads/{ad_id}", dependencies=[Depends(require_ad_api_key)])
def get_ad(ad_id: str):
    pkg = load_ad_package(ad_id, _output_root())
    if not pkg:
        raise HTTPException(status_code=404, detail=f"Ad package not found: {ad_id}")
    return public_payload(pkg)


@app.get("/v1/ads/{ad_id}/poster")
def get_ad_poster(
    ad_id: str,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    海報圖檔（預設公開可下載，供 assets.poster_url 使用）。
    設 AD_POSTER_REQUIRE_KEY=1 則需帶 API key。
    """
    require_key = (os.getenv("AD_POSTER_REQUIRE_KEY") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if require_key:
        try:
            require_ad_api_key(authorization=authorization, x_api_key=x_api_key)
        except HTTPException:
            raise

    paths = package_paths(ad_id, _output_root())
    poster = paths["poster"]
    if not poster.is_file():
        latest = load_latest_ad_package(_output_root())
        if latest and latest.get("id") == ad_id:
            fused = latest_paths(_output_root())["fused"]
            if fused.is_file():
                poster = fused
    if not poster.is_file():
        raise HTTPException(status_code=404, detail="Poster not found")
    return FileResponse(
        path=str(poster),
        media_type="image/png",
        filename=f"{ad_id}.png",
    )


@app.get("/v1/ads", dependencies=[Depends(require_ad_api_key)])
def list_ads():
    return {"ids": list_ad_package_ids(_output_root())}


@app.post("/v1/ads/generate", dependencies=[Depends(require_ad_api_key)])
def post_generate(body: GenerateBody) -> Dict[str, Any]:
    result = generate_ad_package(
        batch_id=body.batch_id,
        racing_date=body.racing_date,
        course=body.course,
        output_root=_output_root(),
        notify=body.notify,
        force_regen_poster=body.force_regen_poster,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "generate failed")
    pkg = result.get("package") or {}
    return {
        "ok": True,
        "id": result.get("id"),
        "status": result.get("status"),
        "package": public_payload(pkg) if pkg else None,
        "webhook": pkg.get("webhook"),
    }


@app.post("/v1/ads/{ad_id}/notify", dependencies=[Depends(require_ad_api_key)])
def post_notify(ad_id: str) -> Dict[str, Any]:
    """手動重發 webhook（方便外部助手重試）。"""
    pkg = load_ad_package(ad_id, _output_root())
    if not pkg:
        raise HTTPException(status_code=404, detail=f"Ad package not found: {ad_id}")
    if pkg.get("status") != "ready":
        raise HTTPException(status_code=409, detail="Package status is not ready")
    result = dispatch_ad_webhook(pkg)
    pkg["webhook"] = result
    from ad_package import save_ad_package

    save_ad_package(pkg, _output_root())
    return {"ok": bool(result.get("ok")), "id": ad_id, "webhook": result}


@app.post("/v1/ads/rebuild-from-copy", dependencies=[Depends(require_ad_api_key)])
def post_rebuild_from_copy(notify: bool = True) -> Dict[str, Any]:
    """用現有 copy.json／fused.png 重建廣告包（不重跑預測）。"""
    root = _output_root()
    copy_data = load_copy_json(root)
    if not copy_data:
        raise HTTPException(status_code=404, detail="copy.json not found")
    try:
        pkg = build_ad_package_from_copy(copy_data, output_root=root, notify=notify)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ok": True,
        "id": pkg.get("id"),
        "package": public_payload(pkg),
        "webhook": pkg.get("webhook"),
    }


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT") or 8000)
    uvicorn.run("ad_api:app", host="0.0.0.0", port=port, reload=False)
