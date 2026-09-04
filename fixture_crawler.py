import asyncio
import httpx
from selectolax.parser import HTMLParser
import sqlite3
from datetime import datetime

class HKJCFixtureCrawler:
    def __init__(self, db_path='j18_local.db'):
        self.db_path = db_path
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://racing.hkjc.com/'
        }

    def init_db(self):
        """建立賽期表專用資料表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS fixtures (
            racing_date DATE PRIMARY KEY,
            course TEXT,          -- ST (沙田) 或 HV (跑馬地)
            day_of_week TEXT,     -- 星期三、星期日等
            is_day_meeting BOOLEAN, -- 日馬(True) 或 夜馬(False)
            status TEXT DEFAULT 'PENDING' -- PENDING, RACECARD_DONE, RESULT_DONE
        )
        ''')
        conn.commit()
        conn.close()

    async def fetch_fixtures(self):
        # 官方賽期表 URL
        url = "https://racing.hkjc.com/zh-hk/local/racing-fixtures"
        
        async with httpx.AsyncClient(http2=True) as client:
            try:
                print(f"正在抓取整季賽期表...")
                response = await client.get(url, headers=self.headers, timeout=15.0)
                response.raise_for_status()
                return response.text
            except Exception as e:
                print(f"抓取賽期表失敗: {e}")
                return None

    def parse_and_save(self, html):
        if not html: return
        
        tree = HTMLParser(html)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # HKJC 的賽期表通常放在一個有 .row 或特定 class 的表格裡
        # 由於網頁常變，我們這裡用泛用的搜尋方式找尋 YYYY/MM/DD 的格式
        import re
        date_pattern = re.compile(r'(202[5-9])/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])')
        
        text_blocks = tree.css('td, div, span')
        
        saved_count = 0
        current_year = datetime.now().year
        
        # 這是一個簡化的解析邏輯。實務上會根據 HKJC 的確切 DOM 結構 (如 table tr) 來精確定位。
        # 這裡我們模擬萃取出日期與馬場。
        
        # TODO: 由於 HKJC 賽期表網頁由大量 JavaScript 動態生成，若 selectolax 抓不到，
        # 未來在 Railway 上可以改接 J18 的 API (若他們有提供賽程表) 或用 Playwright。
        
        print("✅ 賽期表解析完成 (模擬)。")
        print("💡 在真實環境中，這會將未來 88 個賽馬日寫入 fixtures 資料表。")
        print("   例如: INSERT INTO fixtures (racing_date, course) VALUES ('2026-09-06', 'ST')")
        
        # 模擬寫入一筆測試資料
        cursor.execute('''
            INSERT INTO fixtures (racing_date, course, day_of_week, is_day_meeting)
            VALUES (?, ?, ?, ?) ON CONFLICT(racing_date) DO NOTHING
        ''', ('2026-09-06', 'ST', '星期日', True))
        
        conn.commit()
        conn.close()

if __name__ == "__main__":
    crawler = HKJCFixtureCrawler()
    asyncio.run(crawler.fetch_fixtures()).add_done_callback(lambda future: crawler.parse_and_save(future.result()))
