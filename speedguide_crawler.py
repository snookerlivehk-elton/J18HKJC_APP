import asyncio
import httpx
from selectolax.parser import HTMLParser
import argparse
import sqlite3
import re
import json

class HKJCSpeedGuideCrawler:
    def __init__(self, db_path='j18_local.db'):
        self.db_path = db_path
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://racing.hkjc.com/'
        }

    def init_db(self):
        """建立賽前 Speedguide (速勢能量) 專用資料表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS upcoming_speedguide (
            runner_id TEXT PRIMARY KEY,
            race_id TEXT,
            horse_no INTEGER,
            form_rating TEXT,
            speed_energy NUMERIC,
            speed_energy_delta NUMERIC,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        conn.commit()
        conn.close()

    async def fetch_speedguide(self, client, race_num, date_str=None, course=None):
        # 官方 Speedguide URL
        url = f"https://racing.hkjc.com/zh-hk/local/info/speedpro/speedguide?raceno={race_num}"
        if date_str and course:
            url += f"&racedate={date_str}&Racecourse={course}"
            
        try:
            print(f"正在抓取速勢能量與狀態評級 (第 {race_num} 場): {url}")
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
        
        # 模擬解析邏輯：這裡預留了對「狀態評級」、「速勢能量評估」與「速勢能量評估差值」的抓取口。
        # 由於 HKJC 的表格結構需要根據當天 DOM 微調，以下先設定一個資料庫寫入的標準介面。
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # TODO: 針對真實的 DOM 結構寫入 css 選擇器
        # 例如: rows = tree.css('table.speedguide-table tr')
        # for row in rows:
        #     horse_no = row.css_first('.horse-no').text()
        #     form_rating = row.css_first('.form-rating').text() # 如 'A', 'B', 'C' 等
        #     speed_energy = row.css_first('.speed-energy').text()
        #     speed_energy_delta = row.css_first('.speed-energy-delta').text()
        
        print(f"✅ 第 {race_num} 場 Speedguide 頁面下載完成，預備寫入資料庫...")
        
        # 示範寫入格式 (實際使用時，這會在迴圈內解析所有馬匹並寫入)
        # runner_id = f"{race_id}_{horse_no}"
        # cursor.execute('''
        #     INSERT INTO upcoming_speedguide 
        #     (runner_id, race_id, horse_no, form_rating, speed_energy, speed_energy_delta, raw_json)
        #     VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(runner_id) DO UPDATE SET 
        #     form_rating=excluded.form_rating, speed_energy=excluded.speed_energy, speed_energy_delta=excluded.speed_energy_delta
        # ''', (runner_id, race_id, horse_no, form_rating, speed_energy, speed_energy_delta, json.dumps({...})))
        
        conn.commit()
        conn.close()
        return True

    async def crawl_all_races(self, date_str, course):
        self.init_db()
        
        # 強制設定連接數限制為 1，完全遵守單線程、一個一個來的安全規範
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        async with httpx.AsyncClient(http2=True, limits=limits) as client:
            for num in range(1, 12):
                await asyncio.sleep(3.0) # 遵守 3 秒間隔規定
                html = await self.fetch_speedguide(client, num, date_str, course)
                if html and "找不到" not in html and "Error" not in html:
                    self.parse_and_save(html, date_str, course, num)
                else:
                    print(f"第 {num} 場可能不存在或已結束。")
                    break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='J18 Speedguide 速勢能量爬蟲')
    parser.add_argument('--date', type=str, required=True, help='日期 YYYY/MM/DD')
    parser.add_argument('--course', type=str, default='ST', help='馬場 ST 或 HV')
    
    args = parser.parse_args()
    
    crawler = HKJCSpeedGuideCrawler()
    asyncio.run(crawler.crawl_all_races(args.date, args.course))
