import httpx
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import sqlite3
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 支援 SQLite 以便本地免 Docker 開發
USE_SQLITE = os.getenv("USE_SQLITE", "true").lower() == "true"
SQLITE_DB_PATH = "j18_local.db"

# 公司內 J18 歷史 API（費用敏感）：只從環境變數讀取，勿把正式網址寫死在 repo
_DEFAULT_J18_ORIGIN = "https://api.j18.hk"
_J18_HISTORY_PATH = "/calculate/v1/historyResult"


def get_j18_history_result_url() -> str:
    """
    J18_API_BASE_URL 可為：
    - 源站：https://api.j18.hk  → 自動接 /calculate/v1/historyResult
    - 完整 endpoint：…/historyResult
    """
    raw = (os.getenv("J18_API_BASE_URL") or _DEFAULT_J18_ORIGIN).strip().rstrip("/")
    if raw.lower().endswith("historyresult"):
        return raw
    return f"{raw}{_J18_HISTORY_PATH}"


class J18ETLPipeline:
    def __init__(self, db_pool=None):
        """
        初始化 ETL Pipeline
        :param db_pool: asyncpg database pool (供 PostgreSQL 使用)，若 USE_SQLITE 為 True 則略過
        """
        self.db_pool = db_pool
        self.base_url = get_j18_history_result_url()
        
        if USE_SQLITE:
            self._init_sqlite_db()

    def _init_sqlite_db(self):
        """初始化 SQLite 資料表 (僅供本地測試)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        
        # 讀取 schema.sql (簡單替換 PostgreSQL 專用語法)
        try:
            with open("schema.sql", "r", encoding="utf-8") as f:
                schema_sql = f.read()
                
                # 簡易語法轉換 (PostgreSQL -> SQLite)
                schema_sql = schema_sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                schema_sql = schema_sql.replace("JSONB", "TEXT")
                schema_sql = schema_sql.replace("TIMESTAMPTZ", "DATETIME")
                schema_sql = schema_sql.replace("NOW()", "CURRENT_TIMESTAMP")
                schema_sql = schema_sql.replace("BOOLEAN", "INTEGER")
                
                # 移除 PostgreSQL 特有的語法
                import re
                schema_sql = re.sub(r"CREATE OR REPLACE FUNCTION.*?language 'plpgsql';", "", schema_sql, flags=re.DOTALL)
                schema_sql = re.sub(r"CREATE TRIGGER.*?;", "", schema_sql, flags=re.DOTALL)
                
                c.executescript(schema_sql)
        except Exception as e:
            logger.warning(f"SQLite init tables warning (可能已存在): {e}")
            
        conn.commit()
        conn.close()

    async def fetch_race_data(self, date_str: str, race_num: int) -> Dict[str, Any]:
        """
        透過 httpx 爬取指定日期與場次的 API 資料
        """
        url = f"{self.base_url}?date={date_str}&num={race_num}"
        logger.info(f"Fetching data from: {url}")
        
        # 強制設定連接數限制為 1，徹底杜絕併發
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        async with httpx.AsyncClient(timeout=10.0, limits=limits) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    def _safe_numeric(self, val: Any) -> Optional[float]:
        """安全轉換數值，處理如 '+14', '1,000' 等字串"""
        if val is None or val == "" or val == "-":
            return None
        try:
            return float(str(val).replace(",", "").replace("+", ""))
        except ValueError:
            return None

    def _safe_int(self, val: Any) -> Optional[int]:
        """安全轉換整數"""
        if val is None or val == "" or val == "-":
            return None
        try:
            return int(str(val).replace(",", "").replace("+", ""))
        except ValueError:
            return None

    async def extract_text_reports(self, data: Dict[str, Any], race_id: str):
        """
        獨立抽取 running_comment_text 及 incident_report_text
        準備存入 text_reports 資料表
        """
        reports = []
        try:
            races_data = data.get("data", {}).get("data", {}).get("races", {})
            for r_key, r_val in races_data.items():
                horses = r_val.get("detail", {}).get("horses", [])
                for horse in horses:
                    runner_id = horse.get("id")
                    if not runner_id:
                        continue
                        
                    running_comment = horse.get("running_comment_text")
                    incident_report = horse.get("incident_report_text")
                    
                    if running_comment:
                        reports.append({
                            "entity_type": "runner",
                            "entity_id": runner_id,
                            "report_type": "running_comment",
                            "report_text": running_comment,
                            "raw_json": json.dumps(horse)
                        })
                    
                    if incident_report:
                        reports.append({
                            "entity_type": "runner",
                            "entity_id": runner_id,
                            "report_type": "incident_report",
                            "report_text": incident_report,
                            "raw_json": json.dumps(horse)
                        })
        except Exception as e:
            logger.error(f"Error extracting text reports: {e}")
            
        return reports

    async def process_and_load(self, date_str: str, race_num: int):
        """
        執行完整的 Extract, Transform, Load 流程
        """
        # 1. Extract
        raw_data = await self.fetch_race_data(date_str, race_num)
        
        if raw_data.get("code") != 0:
            raise ValueError(f"API 回傳錯誤: {raw_data.get('message')}")
            
        outer_data = raw_data.get("data", {})
        inner_data = outer_data.get("data", {})
        races_dict = inner_data.get("races", {})
        
        # 取得當前請求場次的資料
        race_key = str(race_num)
        if race_key not in races_dict:
            raise ValueError(f"找不到場次 {race_num} 的資料")
            
        race_data = races_dict[race_key]
        detail = race_data.get("detail", {})
        horses = detail.get("horses", [])
        
        # 2. Transform IDs
        meeting_id = date_str
        # J18 API 存在 Bug，所有場次的 horses[]["id"] 可能都寫死成 "HV01" 或 "ST01"
        # 因此我們只取其地點碼 (索引 8-10)，並手動壓上正確的 race_num
        if horses and horses[0].get("id"):
            venue_code = horses[0]["id"][8:10] # 'HV' 或 'ST'
            race_id = f"{date_str.replace('-', '')}{venue_code}{int(race_num):02d}"
        else:
            race_id = f"{date_str.replace('-', '')}HV{int(race_num):02d}" # 預設格式
            
        text_reports = await self.extract_text_reports(raw_data, race_id)
        
        # 3. Load (寫入資料庫)
        if USE_SQLITE:
            return self._load_to_sqlite(raw_data, outer_data, inner_data, detail, horses, text_reports, meeting_id, race_id, date_str, race_num)
            
        if not self.db_pool:
            logger.warning("Mock mode: db_pool is None. 跳過資料庫寫入。")
            return {
                "status": "success_mock",
                "date": date_str,
                "race_num": race_num,
                "horses_count": len(horses),
                "extracted_text_reports_count": len(text_reports)
            }

        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                # 3.1 寫入 race_meetings
                await conn.execute('''
                    INSERT INTO race_meetings (meeting_id, racing_date, file_name, file_mtime, file_size, race_count, raw_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (meeting_id) DO UPDATE SET 
                        file_mtime = EXCLUDED.file_mtime,
                        file_size = EXCLUDED.file_size,
                        raw_json = EXCLUDED.raw_json
                ''', meeting_id, 
                     datetime.strptime(date_str, "%Y-%m-%d").date(), 
                     outer_data.get("file_name"), 
                     outer_data.get("file_mtime"), 
                     outer_data.get("file_size"), 
                     inner_data.get("race_count"), 
                     json.dumps(raw_data))

                # 3.2 寫入 races
                await conn.execute('''
                    INSERT INTO races (race_id, meeting_id, race_num, title, race_name, class, distance_text, distance_m, rating_text, course, track, ground, race_time_raw, raw_detail_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ON CONFLICT (race_id) DO UPDATE SET
                        raw_detail_json = EXCLUDED.raw_detail_json
                ''', race_id, meeting_id, race_num, detail.get("title"), detail.get("race_name"),
                     detail.get("class"), detail.get("distance"), self._safe_int(detail.get("distance", "").replace("米", "")),
                     detail.get("rating"), detail.get("course"), detail.get("track"), detail.get("ground"),
                     json.dumps(detail.get("times", [])), json.dumps(detail))

                # 3.3 寫入 runners (馬匹成績)
                for h in horses:
                    runner_id = h.get("id")
                    if not runner_id:
                        continue
                        
                    # 修正 J18 API 的 runner_id bug
                    brand_num = h.get("brandNum", "")
                    runner_id = f"{race_id}{brand_num}" if brand_num else h.get("id")

                    await conn.execute('''
                        INSERT INTO runners (
                            runner_id, race_id, horse_id, racing_horse_id, horse_no, brand_num, horse_name,
                            finish_order_raw, finish_order_num, final_time, jockey_name, trainer_name,
                            handicap_weight, bar_draw, runner_rating, runner_rating_delta,
                            horse_body_weight, horse_body_weight_delta, optimal_time, age, sex,
                            gear_raw, last_six_run_raw, bonus, scratched, raw_json
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
                            $17, $18, $19, $20, $21, $22, $23, $24, $25, $26
                        )
                        ON CONFLICT (runner_id) DO UPDATE SET raw_json = EXCLUDED.raw_json
                    ''',
                        runner_id, race_id, h.get("horse_id"), self._safe_int(h.get("racing_horse_id")),
                        self._safe_int(h.get("horse_no")), h.get("brandNum"), h.get("horse_name"),
                        str(h.get("finish_order")), self._safe_int(h.get("finish_order")), h.get("final_time"),
                        h.get("jockeyName"), h.get("trainerName"),
                        self._safe_numeric(h.get("handicapWeight")), self._safe_int(h.get("barDraw")),
                        self._safe_int(h.get("runnerRating")), self._safe_int(h.get("runnerRating_")),
                        self._safe_numeric(h.get("sceneWeight")), self._safe_numeric(h.get("horseWeight")),
                        h.get("optimalTime"), self._safe_int(h.get("age")), h.get("sex"),
                        h.get("gear"), h.get("lastSixRun"), self._safe_numeric(h.get("bonus")),
                        bool(h.get("scratched")), json.dumps(h)
                    )

                # 3.4 寫入 text_reports (AI 文字庫)
                for tr in text_reports:
                    await conn.execute('''
                        INSERT INTO text_reports (entity_type, entity_id, report_type, report_text, raw_json)
                        VALUES ($1, $2, $3, $4, $5)
                    ''', tr["entity_type"], tr["entity_id"], tr["report_type"], tr["report_text"], tr["raw_json"])

        logger.info(f"Successfully processed and loaded race {date_str} - Race {race_num}")
        return {
            "status": "success",
            "date": date_str,
            "race_num": race_num,
            "horses_count": len(horses),
            "extracted_text_reports_count": len(text_reports)
        }

    def _load_to_sqlite(self, raw_data, outer_data, inner_data, detail, horses, text_reports, meeting_id, race_id, date_str, race_num):
        """將資料寫入 SQLite (本地測試用)"""
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        
        try:
            # 3.1 寫入 race_meetings
            c.execute('''
                REPLACE INTO race_meetings (meeting_id, racing_date, file_name, file_mtime, file_size, race_count, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (meeting_id, date_str, outer_data.get("file_name"), outer_data.get("file_mtime"), 
                 outer_data.get("file_size"), inner_data.get("race_count"), json.dumps(raw_data)))

            # 3.2 寫入 races
            c.execute('''
                REPLACE INTO races (race_id, meeting_id, race_num, title, race_name, class, distance_text, distance_m, rating_text, course, track, ground, race_time_raw, raw_detail_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (race_id, meeting_id, race_num, detail.get("title"), detail.get("race_name"),
                 detail.get("class"), detail.get("distance"), self._safe_int(detail.get("distance", "").replace("米", "")),
                 detail.get("rating"), detail.get("course"), detail.get("track"), detail.get("ground"),
                 json.dumps(detail.get("times", [])), json.dumps(detail)))

            # 3.3 寫入 runners (馬匹成績)
            for h in horses:
                runner_id = h.get("id")
                if not runner_id:
                    continue
                    
                # 修正 J18 API 的 runner_id bug
                brand_num = h.get("brandNum", "")
                runner_id = f"{race_id}{brand_num}" if brand_num else h.get("id")

                # SQLite 的 ON CONFLICT 寫法需要有明確的 UNIQUE 限制
                # 這裡為了保證開發順利，我們改用更相容的 REPLACE INTO
                c.execute('''
                    REPLACE INTO runners (
                        runner_id, race_id, horse_id, racing_horse_id, horse_no, brand_num, horse_name,
                        finish_order_raw, finish_order_num, final_time, jockey_name, trainer_name,
                        handicap_weight, bar_draw, runner_rating, runner_rating_delta,
                        horse_body_weight, horse_body_weight_delta, optimal_time, age, sex,
                        gear_raw, last_six_run_raw, bonus, scratched, raw_json
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                ''', (
                    runner_id, race_id, h.get("horse_id"), self._safe_int(h.get("racing_horse_id")),
                    self._safe_int(h.get("horse_no")), h.get("brandNum"), h.get("horse_name"),
                    str(h.get("finish_order")), self._safe_int(h.get("finish_order")), h.get("final_time"),
                    h.get("jockeyName"), h.get("trainerName"),
                    self._safe_numeric(h.get("handicapWeight")), self._safe_int(h.get("barDraw")),
                    self._safe_int(h.get("runnerRating")), self._safe_int(h.get("runnerRating_")),
                    self._safe_numeric(h.get("sceneWeight")), self._safe_numeric(h.get("horseWeight")),
                    h.get("optimalTime"), self._safe_int(h.get("age")), h.get("sex"),
                    h.get("gear"), h.get("lastSixRun"), self._safe_numeric(h.get("bonus")),
                    1 if h.get("scratched") else 0, json.dumps(h)
                ))

            # 3.4 寫入 text_reports (AI 文字庫)
            for tr in text_reports:
                c.execute('''
                    INSERT INTO text_reports (entity_type, entity_id, report_type, report_text, raw_json)
                    VALUES (?, ?, ?, ?, ?)
                ''', (tr["entity_type"], tr["entity_id"], tr["report_type"], tr["report_text"], tr["raw_json"]))

            conn.commit()
            logger.info(f"[SQLite] Successfully processed and loaded race {date_str} - Race {race_num}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"[SQLite] Error saving to DB: {e}")
            raise
        finally:
            conn.close()
            
        return {
            "status": "success_sqlite",
            "date": date_str,
            "race_num": race_num,
            "horses_count": len(horses),
            "extracted_text_reports_count": len(text_reports)
        }
