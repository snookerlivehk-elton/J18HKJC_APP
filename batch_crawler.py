import asyncio
import argparse
import logging
from datetime import datetime, timedelta
import asyncpg
import httpx
import os

from etl_pipeline import J18ETLPipeline

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("crawler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BatchCrawler")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/j18db")

class RaceCrawler:
    def __init__(self, start_date: str, end_date: str):
        self.start_date = datetime.strptime(start_date, "%Y-%m-%d")
        self.end_date = datetime.strptime(end_date, "%Y-%m-%d")
        self.pipeline = None
        self.db_pool = None

    async def setup(self):
        """初始化資料庫連線與 Pipeline"""
        from etl_pipeline import USE_SQLITE
        logger.info(f"Initializing database... (USE_SQLITE={USE_SQLITE})")
        if not USE_SQLITE:
            self.db_pool = await asyncpg.create_pool(DATABASE_URL)
        self.pipeline = J18ETLPipeline(db_pool=self.db_pool)

    async def teardown(self):
        """關閉資料庫連線"""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("Database pool closed.")

    async def get_processed_dates(self) -> set:
        """從資料庫取得已處理的賽日，用於斷點續傳"""
        import sqlite3
        from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH
        
        if USE_SQLITE:
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH)
                c = conn.cursor()
                c.execute("SELECT racing_date FROM race_meetings")
                dates = {row[0] for row in c.fetchall()}
                conn.close()
                return dates
            except sqlite3.OperationalError:
                return set()
                
        async with self.db_pool.acquire() as conn:
            records = await conn.fetch("SELECT racing_date FROM race_meetings")
            return {r['racing_date'].strftime("%Y-%m-%d") for r in records}

    async def probe_date(self, date_str: str) -> int:
        """探測特定日期是否有賽事，若有則回傳總場數，否則回傳 0"""
        url = f"https://api.j18.hk/calculate/v1/historyResult?date={date_str}&num=1"
        try:
            # 強制設定連接數限制，保證不會同時發出多個請求
            limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
            async with httpx.AsyncClient(timeout=10.0, limits=limits) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                
                # 如果 code == 0 且有資料，表示這天有比賽
                if data.get("code") == 0 and data.get("data", {}).get("data"):
                    race_count = data["data"]["data"].get("race_count", 0)
                    return int(race_count)
        except Exception as e:
            logger.warning(f"Probe failed for {date_str}: {e}")
        return 0

    async def process_single_race(self, date_str: str, race_num: int, max_retries=3):
        """處理單場賽事，包含重試機制"""
        for attempt in range(max_retries):
            try:
                result = await self.pipeline.process_and_load(date_str, race_num)
                logger.info(f"✅ 成功寫入: {date_str} 場次 {race_num} (擷取文字報告: {result.get('extracted_text_reports_count', 0)} 筆)")
                return True
            except httpx.HTTPError as e:
                wait_time = 2 ** attempt
                logger.warning(f"⚠️ 網路錯誤 {date_str} 場次 {race_num} (嘗試 {attempt+1}/{max_retries}): {e}. 等待 {wait_time} 秒...")
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Error processing {date_str} Race {race_num}: {e}")
                break
        return False

    async def run(self):
        """執行批量爬蟲主邏輯"""
        await self.setup()
        
        try:
            processed_dates = await self.get_processed_dates()
            logger.info(f"已發現 {len(processed_dates)} 個處理過的賽日，將自動略過。")

            current_date = self.start_date
            while current_date <= self.end_date:
                date_str = current_date.strftime("%Y-%m-%d")
                
                # 香港賽馬通常在星期三、星期六或星期日舉行，但為免漏抓，我們每天探測
                if date_str in processed_dates:
                    logger.debug(f"略過已處理日期: {date_str}")
                    current_date += timedelta(days=1)
                    continue

                logger.info(f"🔍 探測日期: {date_str} ...")
                race_count = await self.probe_date(date_str)
                
                if race_count > 0:
                    logger.info(f"🎯 發現賽事日! {date_str} 共有 {race_count} 場賽事。開始抓取...")
                    
                    # 依序抓取該日所有場次
                    for race_num in range(1, race_count + 1):
                        success = await self.process_single_race(date_str, race_num)
                        if not success:
                            logger.error(f"暫停抓取 {date_str} 由於場次 {race_num} 發生連續錯誤。")
                            break
                        
                        # 避免被 API 擋下，每場抓取後短暫休息 (配合對方要求加長至 3 秒)
                        await asyncio.sleep(3.0)
                        
                    logger.info(f"🎉 賽日 {date_str} 所有 {race_count} 場賽事處理完畢。")
                
                current_date += timedelta(days=1)
                
                # 探測下一天前稍微休息 (配合對方要求加長至 1.5 秒)
                await asyncio.sleep(1.5)

        finally:
            await self.teardown()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="J18 歷史賽果批量爬蟲")
    parser.add_argument("--start", type=str, required=True, help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="結束日期 (YYYY-MM-DD)")
    
    args = parser.parse_args()
    
    crawler = RaceCrawler(start_date=args.start, end_date=args.end)
    
    # 執行異步事件迴圈
    try:
        asyncio.run(crawler.run())
    except KeyboardInterrupt:
        print("\n使用者中斷爬蟲。")
