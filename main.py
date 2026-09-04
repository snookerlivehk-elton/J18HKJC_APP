import os
from fastapi import FastAPI, HTTPException, Query
from contextlib import asynccontextmanager
from etl_pipeline import J18ETLPipeline
import asyncpg

# 嘗試讀取環境變數中的資料庫連線字串 (Railway 提供 DATABASE_URL)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/j18db")

# 建立 FastAPI 生命週期管理，用於初始化與關閉 DB Pool
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動時建立連線池 (若連線字串無效則先設為 None 方便本地測試 API)
    try:
        app.state.db_pool = await asyncpg.create_pool(DATABASE_URL)
        print("✅ Database pool created successfully.")
    except Exception as e:
        print(f"⚠️ Database connection failed (Mock mode enabled): {e}")
        app.state.db_pool = None
        
    yield
    
    # 關閉時釋放連線池
    if app.state.db_pool:
        await app.state.db_pool.close()
        print("🛑 Database pool closed.")

app = FastAPI(title="J18 ETL Worker", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok", "service": "J18 ETL Worker"}

@app.get("/dbg")
async def debug_etl_pipeline(
    date: str = Query(..., description="賽事日期 (YYYY-MM-DD)", example="2026-07-15"),
    num: int = Query(1, description="場次編號", example=1)
):
    """
    同步直接除錯入口 (Direct Debug Route)
    提供給開發者手動觸發單場賽事的爬取與入庫測試
    """
    try:
        pipeline = J18ETLPipeline(db_pool=app.state.db_pool)
        result = await pipeline.process_and_load(date_str=date, race_num=num)
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # 本地測試啟動指令: python main.py
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
