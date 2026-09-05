"""
HKJC 整季賽期表爬蟲。

資料來源（經典 ASPX，可解析 HTML）：
  https://racing.hkjc.com/racing/information/Chinese/Racing/Fixture.aspx
  參數 CalMonth / CalYear

寫入 fixtures；並為每個賽日初始化 meeting_pipeline 階段列。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from selectolax.parser import HTMLParser

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

FIXTURE_URL = "https://racing.hkjc.com/racing/information/Chinese/Racing/Fixture.aspx"

# 港季大約 9 月開季 → 翌年 7 月
MONTH_CN = {
    "一月": 1, "二月": 2, "三月": 3, "四月": 4, "五月": 5, "六月": 6,
    "七月": 7, "八月": 8, "九月": 9, "十月": 10, "十一月": 11, "十二月": 12,
}
WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _season_months(today: Optional[date] = None) -> List[Tuple[int, int]]:
    """回傳 (year, month) 列表：本季月份。"""
    today = today or date.today()
    # 若今天 >= 9 月，季年 = 今年；否則季年 = 去年
    season_start_year = today.year if today.month >= 9 else today.year - 1
    out = []
    for m in range(9, 13):
        out.append((season_start_year, m))
    for m in range(1, 8):
        out.append((season_start_year + 1, m))
    return out


def _parse_month_year_from_page(text: str, fallback_y: int, fallback_m: int) -> Tuple[int, int]:
    # 二0二六年九月 / 二〇二六年九月
    m = re.search(r"二[0〇]二([一二三四五六七八九〇零])年(十?[一二三四五六七八九]?月)", text)
    if m:
        y_map = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        year = 2020 + y_map.get(m.group(1), 6)
        mon_s = m.group(2)
        # normalize 十月/十一月/十二月/九月
        mon_map = {
            "一月": 1, "二月": 2, "三月": 3, "四月": 4, "五月": 5, "六月": 6,
            "七月": 7, "八月": 8, "九月": 9, "十月": 10, "十一月": 11, "十二月": 12,
        }
        month = mon_map.get(mon_s, fallback_m)
        return year, month
    m2 = re.search(r"(20\d{2})年\s*(\d{1,2})月", text)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    return fallback_y, fallback_m


def _course_from_img_src(src: str) -> Optional[str]:
    """相容經典 st.gif／hv.gif，以及新 CMS 路徑 st-ch／hv-ch。"""
    s = (src or "").lower().split("?")[0]
    name = s.rstrip("/").split("/")[-1]
    if name in ("st.gif", "st-ch", "st"):
        return "ST"
    if name in ("hv.gif", "hv-ch", "hv"):
        return "HV"
    if s.endswith("st.gif") or "/fixture/st" in s:
        return "ST"
    if s.endswith("hv.gif") or "/fixture/hv" in s:
        return "HV"
    return None


def parse_fixture_html(html: str, cal_year: int, cal_month: int) -> List[dict]:
    tree = HTMLParser(html)
    body_text = tree.body.text(strip=True) if tree.body else html
    year, month = _parse_month_year_from_page(body_text, cal_year, cal_month)

    meetings = []
    for im in tree.css("img"):
        src = im.attributes.get("src") or ""
        course = _course_from_img_src(src)
        if not course:
            continue

        td = im.parent
        for _ in range(10):
            if td is None:
                break
            if td.tag == "td":
                break
            td = td.parent
        if td is None or td.tag != "td":
            continue

        day = None
        for child in td.css("a, span, div, font, b, strong"):
            t = (child.text(strip=True) or "").strip()
            if re.fullmatch(r"[1-9]|[12]\d|3[01]", t):
                day = int(t)
                break
        if day is None:
            # 後援：避免 61400 誤判 — 要求後面不是數字
            tm = re.match(r"^([1-9]|[12]\d|3[01])(?!\d)", (td.text(strip=True) or ""))
            if tm:
                day = int(tm.group(1))
        if day is None:
            continue

        html_td = (td.html or "").lower()
        is_night = "night.gif" in html_td or "/fixture/night" in html_td
        is_dusk = "dusk.gif" in html_td or "/fixture/dusk" in html_td
        is_day = (
            "day.gif" in html_td
            or "/fixture/day" in html_td
            or (not is_night and not is_dusk)
        )
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        wd = WEEKDAY_CN[d.weekday()]
        meetings.append(
            {
                "racing_date": d.isoformat(),
                "course": course,
                "day_of_week": wd,
                "is_day_meeting": bool(is_day and not is_night),
                "session": "night" if is_night else ("dusk" if is_dusk else "day"),
            }
        )

    # 去重
    uniq = {}
    for m in meetings:
        uniq[(m["racing_date"], m["course"])] = m
    return list(uniq.values())


class HKJCFixtureCrawler:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://racing.hkjc.com/",
        }

    async def fetch_month(self, client: httpx.AsyncClient, year: int, month: int) -> str:
        params = {"CalMonth": str(month), "CalYear": str(year)}
        # 預設當月有時不需參數；仍帶參數較穩
        r = await client.get(FIXTURE_URL, headers=self.headers, params=params, timeout=30.0)
        r.raise_for_status()
        return r.text

    def save_fixtures(self, rows: List[dict]) -> int:
        from meeting_pipeline import MeetingPipeline

        pipe = MeetingPipeline()
        return pipe.upsert_fixtures(rows)

    async def crawl_season(self, today: Optional[date] = None) -> Dict[str, Any]:
        today = today or date.today()
        months = _season_months(today)
        all_rows: List[dict] = []
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
            # 無參數頁＝官網「當月」視圖；CalMonth=當月有時回空殼（2026-09 實證）
            try:
                print(f"抓取賽期（當月預設頁）…")
                html = await client.get(FIXTURE_URL, headers=self.headers, timeout=30.0)
                html.raise_for_status()
                rows = parse_fixture_html(html.text, today.year, today.month)
                print(f"  → {len(rows)} 個賽日")
                all_rows.extend(rows)
            except Exception as e:
                print(f"  預設頁失敗: {e}")

            for year, month in months:
                # 當月已由預設頁覆蓋；帶 CalMonth 的當月請求可能是空的，仍試一次作補漏
                await asyncio.sleep(1.0)
                try:
                    print(f"抓取賽期 {year}-{month:02d} …")
                    html = await self.fetch_month(client, year, month)
                    rows = parse_fixture_html(html, year, month)
                    print(f"  → {len(rows)} 個賽日")
                    all_rows.extend(rows)
                except Exception as e:
                    print(f"  失敗: {e}")

        # 去重
        uniq = {}
        for m in all_rows:
            uniq[(m["racing_date"], m["course"])] = m
        all_rows = list(uniq.values())

        n = self.save_fixtures(all_rows)
        print(f"完成：寫入／更新 {n} 筆 fixtures（解析到 {len(all_rows)}）")
        return {"ok": True, "parsed": len(all_rows), "saved": n, "rows": all_rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HKJC 整季賽期表爬蟲")
    args = parser.parse_args()
    crawler = HKJCFixtureCrawler()
    asyncio.run(crawler.crawl_season())
