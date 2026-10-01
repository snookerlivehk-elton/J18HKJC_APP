#!/usr/bin/env python3
"""Export HKJC racecard for a meeting day into racecard_board.html MEETING JSON."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "static" / "racecard_board.html"

sys.path.insert(0, str(ROOT))
from racecard_crawler import HKJCRaceCardCrawler  # noqa: E402
from bucket_utils import extract_race_class_label  # noqa: E402


def demo_odds(no: int, rating: int, race_num: int) -> tuple[float, float]:
    base = 2.0 + max(0, (70 - rating) * 0.2) + (no % 9) * 0.17 + (race_num % 5) * 0.05
    win = round(min(88.0, max(2.1, base)), 1)
    place = round(max(1.1, min(30.0, win * 0.32 + 0.6)), 1)
    return win, place


def parse_title_bits(html: str) -> dict:
    tree = HTMLParser(html)
    text = " ".join(d.text(strip=True) for d in (tree.css(".f_fs13") or []))
    time_m = re.search(r"(\d{2}:\d{2})", text)
    track_m = re.search(r'"([A-Z+]+)"\s*賽道', text) or re.search(r'"([A-Z+]+)"', text)
    dist_m = re.search(r"(\d+)\s*米", text)
    ground_m = re.search(r"(好地至?快?地?|好地|黏地至?快?地?|軟地)", text)
    return {
        "time": time_m.group(1) if time_m else "",
        "track": track_m.group(1) if track_m else "A",
        "distance": int(dist_m.group(1)) if dist_m else 0,
        "ground": ground_m.group(1) if ground_m else "好地",
        "raw": text,
    }


def runner_from_row(row, race_num: int) -> dict | None:
    tds = row.css("td")
    if len(tds) < 14:
        return None
    horse_no_text = tds[0].text(strip=True)
    if not horse_no_text.isdigit():
        return None
    no = int(horse_no_text)
    form6 = tds[1].text(strip=True).replace("-", "/")
    name = tds[3].text(strip=True)
    code = tds[4].text(strip=True)
    hw = tds[5].text(strip=True)
    jockey = tds[6].text(strip=True)
    jockey_allow = tds[7].text(strip=True) if len(tds) > 7 else ""
    if jockey_allow and jockey_allow not in ("", "-"):
        jockey = f"{jockey} ({jockey_allow})"
    draw_text = tds[8].text(strip=True)
    draw = int(draw_text) if draw_text.isdigit() else None
    trainer = tds[9].text(strip=True)
    rating = int(tds[11].text(strip=True)) if len(tds) > 11 and tds[11].text(strip=True).isdigit() else 0
    rd_text = tds[12].text(strip=True) if len(tds) > 12 else ""
    rtg_delta = ""
    if rd_text not in ("", "-"):
        try:
            n = int(rd_text.replace("+", ""))
            rtg_delta = ("+" if n > 0 else "") + str(n) if n != 0 else "0"
        except ValueError:
            rtg_delta = rd_text
    body_wt_text = tds[13].text(strip=True) if len(tds) > 13 else ""
    body_wt = int(body_wt_text) if body_wt_text.isdigit() else 0
    gear = tds[22].text(strip=True) if len(tds) > 22 else ""
    age_text = tds[16].text(strip=True) if len(tds) > 16 else ""
    age = int(age_text) if age_text.isdigit() else 0
    owner = tds[23].text(strip=True) if len(tds) > 23 else ""
    sire = tds[24].text(strip=True) if len(tds) > 24 else ""
    dam = tds[25].text(strip=True) if len(tds) > 25 else ""
    prize = (tds[19].text(strip=True) if len(tds) > 19 else "").replace(",", "")
    img = tds[2].css_first("img")
    silk = ""
    if img and img.attributes.get("src"):
        silk = img.attributes["src"]
        if silk.startswith("/"):
            silk = "https://racing.hkjc.com" + silk
    if not silk and code:
        silk = f"https://racing.hkjc.com/racing/content/Images/RaceColor/{code}.gif"
    win, place = demo_odds(no, rating, race_num)
    return {
        "no": no,
        "name": name,
        "draw": draw,
        "form6": form6,
        "recent": form6,
        "jockey": jockey,
        "trainer": trainer,
        "age": age,
        "rating": rating,
        "rtgDelta": rtg_delta,
        "hw": int(float(hw)) if hw.replace(".", "", 1).isdigit() else 0,
        "bodyWt": body_wt,
        "gear": gear,
        "owner": owner,
        "sire": sire,
        "dam": dam,
        "prize": prize or "0",
        "silk": silk,
        "scratched": False,
        "win": win,
        "place": place,
    }


async def build_meeting(date_str: str, course: str) -> dict:
    crawler = HKJCRaceCardCrawler()
    races = []
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        for race_num in range(1, 20):
            html = await crawler.fetch_race(client, date_str, course, race_num)
            if not html:
                break
            info, parsed = crawler.parse_race_info(html, date_str, course, race_num)
            if not info or not parsed:
                break
            title = parse_title_bits(html)
            tree = HTMLParser(html)
            table = tree.css_first("table.draggable")
            if not table:
                break
            runners = []
            for row in table.css("tbody tr"):
                r = runner_from_row(row, race_num)
                if r:
                    runners.append(r)
            if not runners:
                break
            cls = info.get("class") or extract_race_class_label(title["raw"])
            name = info.get("race_name") or f"第{race_num}場"
            meta = (
                f'{title["time"]} {name}　田草 "{title["track"]}" '
                f'{title["distance"]}米 {cls} {title["ground"]}'
            )
            races.append(
                {
                    "num": race_num,
                    "name": name,
                    "time": title["time"],
                    "meta": meta.strip(),
                    "runners": runners,
                }
            )
            print(f"race {race_num}: {name} ({len(runners)} runners)", flush=True)
    y, m, d = date_str.split("/")
    return {
        "date": f"{y}-{m}-{d}",
        "y": y,
        "m": m,
        "d": d,
        "weekday": "周四",
        "courseLabel": "沙田" if course == "ST" else "跑馬地",
        "liveSnapshot": True,
        "source": f"HKJC racecard {date_str} {course} snapshot (WIN/PLA odds demo until API)",
        "races": races,
    }


def patch_html(meeting: dict) -> None:
    text = HTML_PATH.read_text(encoding="utf-8")
    blob = json.dumps(meeting, ensure_ascii=False, separators=(",", ":"))
    text, n = re.subn(r"    let MEETING = \{.*?\};", f"    let MEETING = {blob};", text, count=1, flags=re.DOTALL)
    if n != 1:
        raise SystemExit("MEETING replace failed")
    first_meta = meeting["races"][0]["meta"]
    text = re.sub(r"let currentRace = \d+;", "let currentRace = 1;", text, count=1)
    text = re.sub(
        r'(<div id="raceMeta">)[^<]*(</div>)',
        rf"\1{first_meta}\2",
        text,
        count=1,
    )
    guard_fn = (
        "    function isLiveRacecardSnapshot() {\n"
        "      return !!(MEETING && MEETING.liveSnapshot);\n"
        "    }\n\n"
    )
    if "function isLiveRacecardSnapshot" not in text:
        text = text.replace(
            "    /* 測試用：追加第 20 場（20 匹），點場次「20」可預覽連贏橫滑 */\n",
            guard_fn + "    /* 測試用：追加第 20 場（20 匹），點場次「20」可預覽連贏橫滑 */\n",
            1,
        )
    for fn in (
        "ensureRace9Has14Runners",
        "ensureRace8Has8Runners",
        "ensureRace7Has6Runners",
        "ensureRace6Has10WithScratch7",
    ):
        needle = f"    function {fn}() {{\n"
        if needle in text and f"{fn}() {{\n      if (isLiveRacecardSnapshot()) return;" not in text:
            text = text.replace(
                needle,
                f"    function {fn}() {{\n      if (isLiveRacecardSnapshot()) return;\n",
                1,
            )
    HTML_PATH.write_text(text, encoding="utf-8")


async def main() -> None:
    date_str = sys.argv[1] if len(sys.argv) > 1 else "2026/10/01"
    course = sys.argv[2] if len(sys.argv) > 2 else "ST"
    meeting = await build_meeting(date_str, course)
    if not meeting["races"]:
        raise SystemExit("no races fetched")
    patch_html(meeting)
    print(f"patched {HTML_PATH} — {len(meeting['races'])} races", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
