import asyncio
import httpx
from selectolax.parser import HTMLParser
import argparse
import sqlite3
import re
from datetime import datetime

# 官方排位表 URL 範例: https://racing.hkjc.com/zh-hk/local/information/racecard?racedate=2026/09/06&Racecourse=ST&RaceNo=1

class HKJCRaceCardCrawler:
    def __init__(self, db_path='j18_local.db'):
        self.db_path = db_path
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://racing.hkjc.com/'
        }

    def init_db(self):
        """建立排位表專用資料表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS upcoming_races (
            race_id TEXT PRIMARY KEY,
            racing_date DATE,
            race_num INTEGER,
            course TEXT,
            race_name TEXT,
            class TEXT,
            distance_m INTEGER,
            track TEXT,
            ground TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS upcoming_runners (
            runner_id TEXT PRIMARY KEY,
            race_id TEXT,
            horse_no INTEGER,
            horse_name TEXT,
            horse_code TEXT,
            draw INTEGER,
            jockey_name TEXT,
            trainer_name TEXT,
            handicap_weight NUMERIC,
            horse_weight NUMERIC,
            rating INTEGER,
            rating_delta INTEGER,
            gear TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (race_id) REFERENCES upcoming_races(race_id) ON DELETE CASCADE
        )
        ''')
        conn.commit()
        conn.close()

    async def fetch_race(self, client, date_str, course, race_num):
        url = f"https://racing.hkjc.com/zh-hk/local/information/racecard?racedate={date_str}&Racecourse={course}&RaceNo={race_num}"
        try:
            print(f"正在抓取: {date_str} {course} 第 {race_num} 場...")
            response = await client.get(url, headers=self.headers, timeout=10.0)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"抓取失敗 (第 {race_num} 場): {e}")
            return None

    def parse_race_info(self, html, date_str, course, race_num):
        """解析單場賽事基本資訊與馬匹名單"""
        tree = HTMLParser(html)
        
        # 檢查是否真的有這場比賽 (避免抓過頭)
        table = tree.css_first('table.draggable')
        if not table:
            return None, None

        # 1. 萃取賽事資訊 (Race Info)
        race_id = f"{date_str.replace('/','')}{course}{race_num:02d}"
        
        race_info = {
            'race_id': race_id,
            'racing_date': date_str.replace('/', '-'),
            'race_num': race_num,
            'course': course,
            'race_name': '',
            'class': '',
            'distance_m': 0,
            'track': '',
            'ground': '未知' # 排位時通常未知
        }

        # 從標題區塊提取班次、距離等
        # 由於 HKJC 網頁結構，標題通常在 .f_fl .f_fs13
        title_divs = tree.css('.f_fl.f_fs13')
        if title_divs:
            # 整個標題列的文字拼起來
            text = " ".join([d.text(strip=True) for d in title_divs])
            
            # 尋找距離
            match_dist = re.search(r'(\d+)\s*米', text)
            if match_dist: race_info['distance_m'] = int(match_dist.group(1))
            
            # 尋找班次
            match_class = re.search(r'(第[一二三四五]班|國際[一二三]級賽|表列賽|新馬賽)', text)
            if match_class: race_info['class'] = match_class.group(1)
            
            # 尋找賽道
            if '草地' in text:
                match_track = re.search(r'"([A-Z\+]+)"', text)
                if match_track: 
                    race_info['track'] = f'"{match_track.group(1)}" 賽道'
                else:
                    race_info['track'] = '草地'
            elif '全天候' in text or '泥地' in text:
                race_info['track'] = '全天候跑道'
            else:
                race_info['track'] = '未知'
                
        # 再次檢查：整頁文字 + 常見英文距離 (1200M)
        if race_info['distance_m'] == 0 or race_info['track'] in ('', '未知'):
            text = tree.body.text(strip=True) if tree.body else ""
            if race_info['distance_m'] == 0:
                match_dist = re.search(r'(\d+)\s*米', text) or re.search(r'(\d+)\s*[Mm]', text)
                if match_dist:
                    race_info['distance_m'] = int(match_dist.group(1))
            if not race_info['class']:
                match_class = re.search(r'(第[一二三四五]班|國際[一二三]級賽|表列賽|新馬賽)', text)
                if match_class:
                    race_info['class'] = match_class.group(1)
            if race_info['track'] in ('', '未知'):
                match_track = re.search(r'"([A-Z]\+?\d?)"', text) or re.search(r'\b([ABC](?:\+\d)?)\s*賽道', text)
                if match_track:
                    race_info['track'] = f'"{match_track.group(1)}" 賽道'
                elif '全天候' in text or '泥地' in text or 'AWT' in text.upper():
                    race_info['track'] = '全天候跑道'
                elif '草地' in text:
                    race_info['track'] = '草地'

        # 2. 萃取馬匹名單 (Runners)
        runners = []
        rows = table.css('tbody tr')
        for row in rows:
            tds = row.css('td')
            if len(tds) < 10: continue
            
            try:
                # 解析馬號
                horse_no_text = tds[0].text(strip=True)
                if not horse_no_text.isdigit(): continue
                
                # 解析馬名與代碼
                horse_full = tds[3].text(strip=True)
                horse_name = horse_full.split('(')[0].strip() if '(' in horse_full else horse_full
                horse_code = ''
                match = re.search(r'\(([A-Z0-9]+)\)', horse_full)
                if match: horse_code = match.group(1)
                
                # 檔位、負磅、騎師、練馬師
                draw_text = tds[7].text(strip=True)
                draw = int(draw_text) if draw_text.isdigit() else 0
                
                weight_text = tds[5].text(strip=True)
                weight = float(weight_text) if weight_text.replace('.','',1).isdigit() else 0.0
                
                jockey = tds[6].text(strip=True).split('(')[0].strip()
                trainer = tds[8].text(strip=True)
                
                runner_id = f"{race_id}_{horse_no_text}"
                
                runners.append({
                    'runner_id': runner_id,
                    'race_id': race_id,
                    'horse_no': int(horse_no_text),
                    'horse_name': horse_name,
                    'horse_code': horse_code,
                    'draw': draw,
                    'jockey_name': jockey,
                    'trainer_name': trainer,
                    'handicap_weight': weight,
                    'horse_weight': 0.0, # 排位表通常還沒有體重
                    'rating': 0,
                    'rating_delta': 0,
                    'gear': ''
                })
            except Exception as e:
                print(f"解析馬匹失敗: {e}")
                continue
                
        return race_info, runners

    def save_to_db(self, race_info, runners):
        """寫入 SQLite 或 PostgreSQL"""
        if not race_info or not runners: return
        
        from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH
        import os
        
        if USE_SQLITE:
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            
            try:
                # Upsert Race
                cursor.execute('''
                    INSERT INTO upcoming_races 
                    (race_id, racing_date, race_num, course, race_name, class, distance_m, track, ground)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(race_id) DO UPDATE SET
                    class=excluded.class, distance_m=excluded.distance_m, track=excluded.track
                ''', (
                    race_info['race_id'], race_info['racing_date'], race_info['race_num'], 
                    race_info['course'], race_info['race_name'], race_info['class'], 
                    race_info['distance_m'], race_info['track'], race_info['ground']
                ))
                
                # Upsert Runners
                for r in runners:
                    cursor.execute('''
                        INSERT INTO upcoming_runners 
                        (runner_id, race_id, horse_no, horse_name, horse_code, draw, jockey_name, trainer_name, handicap_weight)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(runner_id) DO UPDATE SET
                        draw=excluded.draw, jockey_name=excluded.jockey_name, trainer_name=excluded.trainer_name, handicap_weight=excluded.handicap_weight
                    ''', (
                        r['runner_id'], r['race_id'], r['horse_no'], r['horse_name'], 
                        r['horse_code'], r['draw'], r['jockey_name'], r['trainer_name'], r['handicap_weight']
                    ))
                
                conn.commit()
                print(f"成功儲存 {race_info['course']} 第 {race_info['race_num']} 場 (共 {len(runners)} 匹馬) [SQLite]")
            except Exception as e:
                print(f"資料庫寫入失敗: {e}")
                conn.rollback()
            finally:
                conn.close()
        else:
            # 寫入 PostgreSQL (Railway)
            import psycopg2
            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                print("找不到 DATABASE_URL 環境變數，無法寫入 PostgreSQL。")
                return
                
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql://", 1)
                
            try:
                conn = psycopg2.connect(db_url)
                cursor = conn.cursor()
                
                # Upsert Race (PostgreSQL 語法)
                cursor.execute('''
                    INSERT INTO upcoming_races 
                    (race_id, racing_date, race_num, course, race_name, class, distance_m, track, ground)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(race_id) DO UPDATE SET
                    class=EXCLUDED.class, distance_m=EXCLUDED.distance_m, track=EXCLUDED.track
                ''', (
                    race_info['race_id'], race_info['racing_date'], race_info['race_num'], 
                    race_info['course'], race_info['race_name'], race_info['class'], 
                    race_info['distance_m'], race_info['track'], race_info['ground']
                ))
                
                # Upsert Runners
                for r in runners:
                    cursor.execute('''
                        INSERT INTO upcoming_runners 
                        (runner_id, race_id, horse_no, horse_name, horse_code, draw, jockey_name, trainer_name, handicap_weight)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(runner_id) DO UPDATE SET
                        draw=EXCLUDED.draw, jockey_name=EXCLUDED.jockey_name, trainer_name=EXCLUDED.trainer_name, handicap_weight=EXCLUDED.handicap_weight
                    ''', (
                        r['runner_id'], r['race_id'], r['horse_no'], r['horse_name'], 
                        r['horse_code'], r['draw'], r['jockey_name'], r['trainer_name'], r['handicap_weight']
                    ))
                
                conn.commit()
                print(f"成功儲存 {race_info['course']} 第 {race_info['race_num']} 場 (共 {len(runners)} 匹馬) [PostgreSQL]")
            except Exception as e:
                print(f"PostgreSQL 資料庫寫入失敗: {e}")
                conn.rollback()
            finally:
                if 'conn' in locals() and conn:
                    cursor.close()
                    conn.close()

    async def crawl_day(self, date_str, course):
        self.init_db()
        
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        # 移除 http2=True，因為在 Railway 環境可能會遇到 h2 未安裝的錯誤，
        # 改用標準 HTTP/1.1 即可滿足抓取需求
        async with httpx.AsyncClient(limits=limits) as client:
            # 先抓第 1 場探路
            html = await self.fetch_race(client, date_str, course, 1)
            if not html:
                print("找不到該日賽事或網路錯誤。")
                return

            race_info, runners = self.parse_race_info(html, date_str, course, 1)
            if not race_info:
                print("解析失敗，該日可能無賽事。")
                return
                
            self.save_to_db(race_info, runners)
            
            # TODO: 解析導覽列獲取總場數，目前預設嘗試抓到第 11 場
            print("開始抓取剩餘場次...")
            for num in range(2, 12):
                await asyncio.sleep(3.0) # 配合要求，將禮貌性延遲加長至 3 秒
                html = await self.fetch_race(client, date_str, course, num)
                if not html: break
                
                race_info, runners = self.parse_race_info(html, date_str, course, num)
                if not race_info:
                    print(f"第 {num} 場不存在，抓取結束。")
                    break
                    
                self.save_to_db(race_info, runners)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='J18 排位表爬蟲 (HKJC)')
    parser.add_argument('--date', type=str, required=True, help='日期 YYYY/MM/DD')
    parser.add_argument('--course', type=str, default='ST', help='馬場 ST 或 HV')
    
    args = parser.parse_args()
    
    crawler = HKJCRaceCardCrawler()
    asyncio.run(crawler.crawl_day(args.date, args.course))
