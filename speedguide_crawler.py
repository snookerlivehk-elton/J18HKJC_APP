"""
HKJC Speed Guide（速勢能量）爬蟲

資料來源（官方頁面 JS 實際呼叫的 CMS JSON，非 HTML 表格）：
  https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current/sg_index
  https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current/sg_race_{N}

官方說明：速勢能量／狀態評級通常於賽日前一日中午左右上架。
寫入 upcoming_speedguide，runner_id 與排位表一致：{YYYYMMDD}{ST|HV}{RR}_{馬號}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)  # 本機 .env 優先於殘留 shell USE_SQLITE=true
except ImportError:
    pass

CMS_BASE = "https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current"
CMS_INDEX = f"{CMS_BASE}/sg_index"
CMS_RACE = f"{CMS_BASE}/sg_race_{{race_no}}"


def _json_loads_bom(text: str | bytes) -> Any:
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    else:
        text = text.lstrip("\ufeff")
    return json.loads(text)


def _parse_float(val) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace(",", "")
    if not s or s in ("-", "—", "N/A", "n/a"):
        return None
    # HKJC delta 可能帶 + 號
    if s.startswith("+"):
        s = s[1:]
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else None


def _course_code(racecourse: str) -> str:
    t = (racecourse or "").strip().lower()
    if "sha tin" in t or "沙田" in (racecourse or ""):
        return "ST"
    if "happy valley" in t or "跑馬地" in (racecourse or ""):
        return "HV"
    u = (racecourse or "").strip().upper()
    if u in ("ST", "HV"):
        return u
    return u or "ST"


def _parse_index_date(racedate_str: str) -> Optional[str]:
    """Index 例：'06/09/2026 5:55 PM' → '2026/09/06'"""
    if not racedate_str:
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", racedate_str.strip())
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y:04d}/{mo:02d}/{d:02d}"


class HKJCSpeedGuideCrawler:
    def __init__(self, db_path: str = "j18_local.db"):
        self.db_path = db_path
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://racing.hkjc.com/zh-hk/local/info/speedpro/speedguide?raceno=1",
        }

    def init_db(self):
        """SQLite 本機表（Postgres 以 schema.sql / 既有表為準）。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
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
            """
        )
        conn.commit()
        conn.close()

    async def fetch_json(self, client: httpx.AsyncClient, url: str) -> Optional[Any]:
        try:
            print(f"GET {url}")
            resp = await client.get(url, headers=self.headers, timeout=45.0)
            resp.raise_for_status()
            return _json_loads_bom(resp.content)
        except Exception as e:
            print(f"抓取失敗 {url}: {e}")
            return None

    def parse_race_payload(
        self,
        payload: dict,
        date_str: str,
        course: str,
        race_num: int,
    ) -> Tuple[str, List[dict]]:
        """從 sg_race_N JSON 抽出馬匹列。優先 zh-hk。"""
        block = payload.get("zh-hk") or payload.get("en-us") or payload
        if not isinstance(block, dict):
            return "", []

        info = block.get("RaceInfoEng") or block.get("RaceInfoChi") or {}
        if info.get("Racecourse"):
            course = _course_code(str(info["Racecourse"]))
        if info.get("Date"):
            parsed = _parse_index_date(str(info["Date"]))
            if parsed:
                date_str = parsed

        race_id = f"{date_str.replace('/', '')}{course}{race_num:02d}"
        runners_out: List[dict] = []

        for row in block.get("SpeedPRO") or []:
            if not isinstance(row, dict):
                continue
            if row.get("scratched") in (True, "true", "True", 1, "1"):
                continue
            horse_no = int(str(row.get("runnernumber") or "0").strip() or 0)
            if horse_no <= 0:
                continue

            fitness = row.get("fitnessrating")
            form_rating = None if fitness is None else str(fitness).strip()

            energy = _parse_float(row.get("speedproenergy"))
            delta = _parse_float(row.get("speedproenergydifference"))
            energy_req = _parse_float(row.get("energyrequired"))

            compact = {
                "name_chi": row.get("name_chi") or row.get("name"),
                "name_eng": row.get("name_eng") or row.get("name"),
                "brandno": row.get("brandno"),
                "draw": row.get("draw"),
                "fitnessrating": form_rating,
                "speedproenergy": energy,
                "speedproenergydifference": delta,
                "energyrequired": energy_req,
                "bestatdistance": row.get("bestatdistance"),
                "bestlast12months": row.get("bestlast12months"),
                "lastrun": row.get("lastrun"),
            }

            runners_out.append(
                {
                    "horse_no": horse_no,
                    "form_rating": form_rating,
                    "speed_energy": energy,
                    "speed_energy_delta": delta,
                    "raw_json": compact,
                }
            )

        return race_id, runners_out

    def save_to_db(self, race_id: str, runners_data: List[dict]):
        if not runners_data:
            return

        # 直接讀環境（勿依賴 etl_pipeline 模組載入當下的快取預設值）
        use_sqlite = os.getenv("USE_SQLITE", "true").lower() == "true"
        sqlite_path = os.getenv("SQLITE_DB_PATH", "j18_local.db")

        if use_sqlite:
            conn = sqlite3.connect(sqlite_path)
            cursor = conn.cursor()
            try:
                for r in runners_data:
                    runner_id = f"{race_id}_{r['horse_no']}"
                    raw = r.get("raw_json")
                    raw_s = json.dumps(raw, ensure_ascii=False) if raw is not None else None
                    cursor.execute(
                        """
                        INSERT INTO upcoming_speedguide
                        (runner_id, race_id, horse_no, form_rating, speed_energy,
                         speed_energy_delta, raw_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(runner_id) DO UPDATE SET
                          form_rating=excluded.form_rating,
                          speed_energy=excluded.speed_energy,
                          speed_energy_delta=excluded.speed_energy_delta,
                          raw_json=excluded.raw_json,
                          created_at=CURRENT_TIMESTAMP
                        """,
                        (
                            runner_id,
                            race_id,
                            r["horse_no"],
                            r["form_rating"],
                            r["speed_energy"],
                            r["speed_energy_delta"],
                            raw_s,
                        ),
                    )
                conn.commit()
                print(f"成功儲存 Speedguide: {race_id} ({len(runners_data)} 匹) [SQLite]")
            except Exception as e:
                print(f"SQLite 寫入失敗: {e}")
                conn.rollback()
            finally:
                conn.close()
            return

        import psycopg2

        db_url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_SYNC")
        if not db_url:
            print("找不到 DATABASE_URL，無法寫入 PostgreSQL。")
            return
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        conn = None
        try:
            conn = psycopg2.connect(db_url)
            cursor = conn.cursor()
            for r in runners_data:
                runner_id = f"{race_id}_{r['horse_no']}"
                raw = r.get("raw_json")
                raw_s = json.dumps(raw, ensure_ascii=False) if raw is not None else None
                cursor.execute(
                    """
                    INSERT INTO upcoming_speedguide
                    (runner_id, race_id, horse_no, form_rating, speed_energy,
                     speed_energy_delta, raw_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(runner_id) DO UPDATE SET
                      form_rating=EXCLUDED.form_rating,
                      speed_energy=EXCLUDED.speed_energy,
                      speed_energy_delta=EXCLUDED.speed_energy_delta,
                      raw_json=EXCLUDED.raw_json,
                      created_at=NOW()
                    """,
                    (
                        runner_id,
                        race_id,
                        r["horse_no"],
                        r["form_rating"],
                        r["speed_energy"],
                        r["speed_energy_delta"],
                        raw_s,
                    ),
                )
            conn.commit()
            print(f"成功儲存 Speedguide: {race_id} ({len(runners_data)} 匹) [PostgreSQL]")
        except Exception as e:
            print(f"PostgreSQL 寫入失敗: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    async def crawl_all_races(
        self,
        date_str: Optional[str] = None,
        course: Optional[str] = None,
        race_nos: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        抓取當前 SpeedPro meeting 全部場次。
        date_str / course 僅作核對；實際 race_id 以 CMS JSON 為準。
        """
        self.init_db()
        summary: Dict[str, Any] = {
            "index_racedate": None,
            "index_lastupdate": None,
            "course": None,
            "races_ok": 0,
            "runners_ok": 0,
            "race_ids": [],
            "warnings": [],
        }

        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
            index = await self.fetch_json(client, CMS_INDEX)
            if not index or not isinstance(index, dict):
                print("無法取得 sg_index（可能尚未上架 Speed Guide）。")
                summary["warnings"].append("sg_index missing")
                return summary

            summary["index_lastupdate"] = index.get("lastupdatetime")
            summary["index_racedate"] = index.get("racedate")
            cms_date = _parse_index_date(str(index.get("racedate") or ""))
            if date_str and cms_date and date_str.replace("-", "/") != cms_date:
                msg = f"指定日期 {date_str} 與 CMS racedate {cms_date} 不同，將以 CMS 為準。"
                print(f"⚠ {msg}")
                summary["warnings"].append(msg)
            effective_date = cms_date or (date_str.replace("-", "/") if date_str else None)
            if not effective_date:
                summary["warnings"].append("cannot parse racedate")
                print("無法解析賽日日期。")
                return summary

            races_meta = index.get("zh-hk") or index.get("en-us") or []
            if not races_meta:
                print("sg_index 無場次列表。")
                summary["warnings"].append("empty race list")
                return summary

            for item in races_meta:
                await asyncio.sleep(1.5)
                try:
                    race_num = int(str(item.get("race")).strip())
                except (TypeError, ValueError):
                    continue
                if race_nos and race_num not in race_nos:
                    continue

                url = CMS_RACE.format(race_no=race_num)
                payload = await self.fetch_json(client, url)
                if not payload:
                    print(f"第 {race_num} 場無資料，略過。")
                    continue

                race_id, runners = self.parse_race_payload(
                    payload, effective_date, course or "ST", race_num
                )
                if not runners:
                    print(f"第 {race_num} 場解析 0 匹馬。")
                    continue

                block = payload.get("zh-hk") or payload.get("en-us") or {}
                info = block.get("RaceInfoEng") or {}
                detected = _course_code(str(info.get("Racecourse") or course or "ST"))
                summary["course"] = detected
                if course and course.upper() != detected:
                    w = f"第 {race_num} 場場地 CMS={detected} 與指定 {course} 不同"
                    print(f"⚠ {w}")
                    summary["warnings"].append(w)

                self.save_to_db(race_id, runners)
                summary["races_ok"] += 1
                summary["runners_ok"] += len(runners)
                summary["race_ids"].append(race_id)

        print(
            f"完成：{summary['races_ok']} 場、{summary['runners_ok']} 匹；"
            f"CMS 更新 {summary['index_lastupdate']}；賽日 {summary['index_racedate']}"
        )
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="J18 Speedguide 速勢能量爬蟲（CMS JSON）")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="可選核對用 YYYY/MM/DD（實際以 CMS sg_index 為準）",
    )
    parser.add_argument(
        "--course",
        type=str,
        default=None,
        help="可選核對用 ST 或 HV（實際以 CMS RaceInfo 為準）",
    )
    parser.add_argument(
        "--races",
        type=str,
        default=None,
        help="可選，逗號分隔場次，如 1,2,3；預設全部",
    )
    args = parser.parse_args()
    race_list = None
    if args.races:
        race_list = [int(x.strip()) for x in args.races.split(",") if x.strip()]

    crawler = HKJCSpeedGuideCrawler()
    asyncio.run(crawler.crawl_all_races(args.date, args.course, race_list))
