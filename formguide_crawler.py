"""
HKJC Form Guide（賽績指引）爬蟲 — CMS JSON

資料來源（與 Speed Guide 同族，非 HTML）：
  https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current/fg_index
  https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current/fg_race_{N}

寫入 upcoming_formguide：form_text（近績短評彙整）+ raw_json。
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
    load_dotenv(override=True)
except ImportError:
    pass

CMS_BASE = "https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current"
CMS_INDEX = f"{CMS_BASE}/fg_index"
CMS_RACE = f"{CMS_BASE}/fg_race_{{race_no}}"


def _json_loads_bom(text: str | bytes) -> Any:
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    else:
        text = text.lstrip("\ufeff")
    return json.loads(text)


def _course_code(racecourse: str) -> str:
    t = (racecourse or "").strip().lower()
    if "sha tin" in t or "沙田" in (racecourse or ""):
        return "ST"
    if "happy valley" in t or "跑馬地" in (racecourse or ""):
        return "HV"
    u = (racecourse or "").strip().upper()
    return u if u in ("ST", "HV") else (u or "ST")


def _parse_index_date(racedate_str: str) -> Optional[str]:
    if not racedate_str:
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", racedate_str.strip())
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y:04d}/{mo:02d}/{d:02d}"


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def build_form_text(row: dict, max_runs: int = 5) -> str:
    """把近績 records 拼成可給 LLM／展示的文字。"""
    parts = []
    name = row.get("horse_chi") or row.get("horse_eng") or row.get("horse") or ""
    if name:
        parts.append(f"馬名：{name}")
    top = (row.get("comments_chi") or row.get("comments_eng") or "").strip()
    if top:
        parts.append(f"官方短評：{_strip_html(top)}")

    for rec in (row.get("runnerrecords") or [])[:max_runs]:
        if not isinstance(rec, dict):
            continue
        date = rec.get("racedate") or ""
        course = rec.get("racecourse") or ""
        dist = rec.get("dist") or ""
        fp = rec.get("fp") or ""
        energy = str(rec.get("energy") or "").strip()
        pace = _strip_html(rec.get("pace_chi") or rec.get("pace_eng") or "")
        comment = _strip_html(rec.get("comments_chi") or rec.get("comments_eng") or "")
        incident = _strip_html(rec.get("incident_chi") or rec.get("incident_eng") or "")
        body = comment
        if pace and pace not in comment:
            body = f"{pace} {comment}".strip()
        line = f"[{date} {course}{dist}m 第{fp}名 能量{energy}] {body}"
        if incident:
            line += f" 事件：{incident}"
        parts.append(line)
    return "\n".join(parts)


class HKJCFormGuideCrawler:
    def __init__(self, db_path: str = "j18_local.db"):
        self.db_path = db_path
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://racing.hkjc.com/zh-hk/local/info/speedpro/formguide?raceno=1",
        }

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upcoming_formguide (
                runner_id TEXT PRIMARY KEY,
                race_id TEXT,
                horse_no INTEGER,
                form_text TEXT,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # 舊表可能無 raw_json
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(upcoming_formguide)")]
            if "raw_json" not in cols:
                conn.execute("ALTER TABLE upcoming_formguide ADD COLUMN raw_json TEXT")
        except Exception:
            pass
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
        self, payload: dict, date_str: str, course: str, race_num: int
    ) -> Tuple[str, List[dict]]:
        # fg_race 可能頂層直接是 race block，或包在 zh-hk
        block = payload
        if "SpeedPRO" not in block and isinstance(payload.get("zh-hk"), dict):
            block = payload["zh-hk"]
        if "SpeedPRO" not in block and isinstance(payload.get("en-us"), dict):
            block = payload["en-us"]

        info = block.get("RaceInfoEng") or block.get("RaceInfoChi") or {}
        if info.get("Racecourse"):
            course = _course_code(str(info["Racecourse"]))
        if info.get("Date"):
            parsed = _parse_index_date(str(info["Date"]))
            if parsed:
                date_str = parsed

        race_id = f"{date_str.replace('/', '')}{course}{race_num:02d}"
        out: List[dict] = []
        for row in block.get("SpeedPRO") or []:
            if not isinstance(row, dict):
                continue
            if row.get("scratched") in (True, "true", "True", 1, "1"):
                continue
            try:
                horse_no = int(str(row.get("runnerno") or row.get("runnernumber") or "0").strip() or 0)
            except ValueError:
                continue
            if horse_no <= 0:
                continue
            form_text = build_form_text(row)
            compact = {
                "horse_chi": row.get("horse_chi"),
                "horse_eng": row.get("horse_eng"),
                "brandno": row.get("brandno"),
                "draw": row.get("draw"),
                "fitnessrating": row.get("fitnessrating"),
                "jockey_chi": row.get("jockey_chi"),
                "trainer_chi": row.get("trainer_chi"),
                "comments_chi": row.get("comments_chi"),
                "runnerrecords": row.get("runnerrecords"),
            }
            out.append(
                {
                    "horse_no": horse_no,
                    "form_text": form_text,
                    "raw_json": compact,
                }
            )
        return race_id, out

    def save_to_db(self, race_id: str, runners_data: List[dict]):
        if not runners_data:
            return
        use_sqlite = os.getenv("USE_SQLITE", "true").lower() == "true"
        sqlite_path = os.getenv("SQLITE_DB_PATH", "j18_local.db")

        if use_sqlite:
            conn = sqlite3.connect(sqlite_path)
            try:
                for r in runners_data:
                    runner_id = f"{race_id}_{r['horse_no']}"
                    raw_s = json.dumps(r.get("raw_json"), ensure_ascii=False)
                    conn.execute(
                        """
                        INSERT INTO upcoming_formguide
                        (runner_id, race_id, horse_no, form_text, raw_json)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(runner_id) DO UPDATE SET
                          form_text=excluded.form_text,
                          raw_json=excluded.raw_json,
                          created_at=CURRENT_TIMESTAMP
                        """,
                        (runner_id, race_id, r["horse_no"], r["form_text"], raw_s),
                    )
                conn.commit()
                print(f"成功儲存 Formguide: {race_id} ({len(runners_data)} 匹) [SQLite]")
            finally:
                conn.close()
            return

        import psycopg2

        db_url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_SYNC")
        if not db_url:
            print("找不到 DATABASE_URL")
            return
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        # 確保 raw_json 欄
        conn = psycopg2.connect(db_url)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS upcoming_formguide (
                    runner_id VARCHAR(50) PRIMARY KEY,
                    race_id VARCHAR(50),
                    horse_no INT,
                    form_text TEXT,
                    raw_json JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "ALTER TABLE upcoming_formguide ADD COLUMN IF NOT EXISTS raw_json JSONB"
            )
            for r in runners_data:
                runner_id = f"{race_id}_{r['horse_no']}"
                raw_s = json.dumps(r.get("raw_json"), ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO upcoming_formguide
                    (runner_id, race_id, horse_no, form_text, raw_json)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(runner_id) DO UPDATE SET
                      form_text=EXCLUDED.form_text,
                      raw_json=EXCLUDED.raw_json,
                      created_at=NOW()
                    """,
                    (runner_id, race_id, r["horse_no"], r["form_text"], raw_s),
                )
            conn.commit()
            print(f"成功儲存 Formguide: {race_id} ({len(runners_data)} 匹) [PostgreSQL]")
        except Exception as e:
            print(f"PostgreSQL 寫入失敗: {e}")
            conn.rollback()
        finally:
            conn.close()

    async def crawl_all_races(
        self,
        date_str: Optional[str] = None,
        course: Optional[str] = None,
        race_nos: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        self.init_db()
        summary: Dict[str, Any] = {
            "races_ok": 0,
            "runners_ok": 0,
            "race_ids": [],
            "warnings": [],
        }
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
            index = await self.fetch_json(client, CMS_INDEX)
            if not index or not isinstance(index, dict):
                summary["warnings"].append("fg_index missing")
                print("無法取得 fg_index")
                return summary

            cms_date = _parse_index_date(str(index.get("racedate") or ""))
            effective = cms_date or (date_str.replace("-", "/") if date_str else None)
            if not effective:
                summary["warnings"].append("no date")
                return summary

            races_meta = index.get("zh-hk") or index.get("en-us") or []
            for item in races_meta:
                await asyncio.sleep(1.2)
                try:
                    race_num = int(str(item.get("race")).strip())
                except (TypeError, ValueError):
                    continue
                if race_nos and race_num not in race_nos:
                    continue
                payload = await self.fetch_json(client, CMS_RACE.format(race_no=race_num))
                if not payload:
                    continue
                race_id, runners = self.parse_race_payload(
                    payload, effective, course or "ST", race_num
                )
                if not runners:
                    continue
                self.save_to_db(race_id, runners)
                summary["races_ok"] += 1
                summary["runners_ok"] += len(runners)
                summary["race_ids"].append(race_id)

        print(f"完成 Formguide：{summary['races_ok']} 場、{summary['runners_ok']} 匹")
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="J18 Formguide 賽績指引爬蟲（CMS JSON）")
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--course", type=str, default=None)
    parser.add_argument("--races", type=str, default=None)
    args = parser.parse_args()
    race_list = None
    if args.races:
        race_list = [int(x.strip()) for x in args.races.split(",") if x.strip()]
    asyncio.run(HKJCFormGuideCrawler().crawl_all_races(args.date, args.course, race_list))
