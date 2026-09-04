import asyncio
import httpx
from selectolax.parser import HTMLParser
import argparse
import sqlite3
import re

class HKJCFormGuideCrawler:
    def __init__(self, db_path='j18_local.db'):
        self.db_path = db_path
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://racing.hkjc.com/'
        }

    def init_db(self):
        """建立賽前文字報告專用資料表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS upcoming_formguide (
            runner_id TEXT PRIMARY KEY,
            race_id TEXT,
            horse_no INTEGER,
            form_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        conn.commit()
        conn.close()

    async def fetch_formguide(self, client, race_num, date_str=None, course=None):
        # 官方 URL 格式 (有時候 HKJC 需要帶 date 和 course 才會準確)
        url = f"https://racing.hkjc.com/zh-hk/local/info/speedpro/formguide?raceno={race_num}"
        if date_str and course:
            url += f"&racedate={date_str}&Racecourse={course}"
            
        try:
            print(f"正在抓取速勢走位 (第 {race_num} 場): {url}")
            response = await client.get(url, headers=self.headers, timeout=10.0)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"抓取失敗 (第 {race_num} 場): {e}")
            return None

    def parse_and_save(self, html, date_str, course, race_num):
        if not html: return False
        
        tree = HTMLParser(html)
        race_id = f"{date_str.replace('/','')}{course}{race_num:02d}"
        
        # HKJC Speedpro 頁面通常包含多個區塊，每個區塊對應一匹馬
        # 這裡使用常見的 class 結構進行捕捉 (由於 HKJC DOM 常變，盡量抓取文字)
        horse_blocks = tree.css('.formguide-row, .row, table tr') # 需根據實際 DOM 微調
        
        results = []
        # 備用解析法：如果找不到精確結構，直接用正則抓取馬號與其後的文字
        raw_text = tree.body.text(separator='|', strip=True) if tree.body else ""
        
        # 假設結構：找尋馬號與短評的對應關係 (這部分在實際有比賽日時可能需要微調 CSS Selector)
        # 這裡提供一個泛用的資料庫寫入邏輯
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 模擬解析過程 (實際需依賴當天 HKJC 的 DOM)
        # 這裡我們假設能夠萃取出 horse_no 與 form_text
        # TODO: 由於賽前 1~2 天才有真實 Speedpro 頁面，這裡留了彈性的解析口
        
        print(f"✅ 第 {race_num} 場 Speedpro 頁面下載完成，準備進入 NLP 暫存區。")
        # 寫入資料庫範例
        # cursor.execute('''
        #     INSERT INTO upcoming_formguide (runner_id, race_id, horse_no, form_text)
        #     VALUES (?, ?, ?, ?) ON CONFLICT(runner_id) DO UPDATE SET form_text=excluded.form_text
        # ''', (runner_id, race_id, horse_no, form_text))
        
        conn.commit()
        conn.close()
        return True

    async def crawl_all_races(self, date_str, course):
        self.init_db()
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        async with httpx.AsyncClient(http2=True, limits=limits) as client:
            for num in range(1, 12):
                await asyncio.sleep(3.0) # 加長延遲，避免 API 過載
                html = await self.fetch_formguide(client, num, date_str, course)
                if html and "找不到" not in html and "Error" not in html:
                    self.parse_and_save(html, date_str, course, num)
                else:
                    print(f"第 {num} 場可能不存在或已結束。")
                    break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='J18 Speedpro 近績爬蟲')
    parser.add_argument('--date', type=str, required=True, help='日期 YYYY/MM/DD')
    parser.add_argument('--course', type=str, default='ST', help='馬場 ST 或 HV')
    
    args = parser.parse_args()
    
    crawler = HKJCFormGuideCrawler()
    asyncio.run(crawler.crawl_all_races(args.date, args.course))
