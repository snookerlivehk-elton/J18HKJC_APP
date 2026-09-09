"""
廣告推介賽後命中（宣傳素材篩選）。

賽前：快照鎖定融合推介列（最多 AD_OUTPUT_PICK_MAX＝4）為 ad_pick_rank。
賽後：回填名次＋獨贏賠率後，依四項原則標記可作宣傳的場次。

1) WIN_ODDS7  — 推介頭兩位命中獨贏，且冠軍最終獨贏賠率 ≥ 7
2) QIN_ODDS10 — 推介覆蓋冠＋亞，且其中一匹最終獨贏賠率 > 10
3) T3_COVER   — 推介覆蓋冠亞季（不計賠率）
4) T4_COVER   — 推介覆蓋 Top4 全部（不計賠率）
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from config import ModelConfig

# 宣傳命中門檻
AD_WIN_ODDS_MIN = 7.0
AD_QIN_ODDS_GT = 10.0


def ad_pick_max() -> int:
    return int(getattr(ModelConfig, "AD_OUTPUT_PICK_MAX", None) or getattr(ModelConfig, "PICK_MAX", 4) or 4)


def parse_runner_win_odds(win_probability_raw: Any, raw_json: Any) -> Optional[float]:
    """
    由 runners 欄位還原「小數獨贏賠率」。
    jjjc_results_sync 把 win_odds 寫進 win_probability_raw，並在 raw_json 保留 win_odds。
    """
    data = None
    if raw_json is not None:
        try:
            data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        except (TypeError, ValueError, json.JSONDecodeError):
            data = None
    if isinstance(data, dict):
        for key in ("win_odds", "winOdds", "odds"):
            if data.get(key) is None:
                continue
            try:
                o = float(str(data.get(key)).replace("%", "").strip())
            except (TypeError, ValueError):
                continue
            if o > 1.0:
                return o
        # jjjc 同步：win_probability_raw 實為賠率
        if str(data.get("synced_via") or "") == "jjjc_results_sync":
            if win_probability_raw is not None and str(win_probability_raw).strip() not in (
                "",
                "-",
                "None",
            ):
                try:
                    o = float(str(win_probability_raw).replace("%", "").strip())
                except (TypeError, ValueError):
                    o = None
                if o is not None and o > 1.0:
                    return o

    # 舊 J18：win_probability 百分比 → 約當賠率
    val = None
    if win_probability_raw is not None and str(win_probability_raw).strip() not in (
        "",
        "-",
        "None",
    ):
        try:
            val = float(str(win_probability_raw).replace("%", "").strip())
        except (TypeError, ValueError):
            val = None
    if val is None and isinstance(data, dict):
        wp = data.get("win_probability")
        if wp is not None and str(wp).strip() not in ("", "-", "None"):
            try:
                val = float(str(wp).replace("%", "").strip())
            except (TypeError, ValueError):
                val = None
    if val is None or val <= 0:
        return None
    if val > 1:
        return 100.0 / val
    return 1.0 / val


def evaluate_ad_race_hits(
    *,
    pick_finishes: Sequence[Optional[int]],
    pick_odds: Sequence[Optional[float]],
    top2_mask: Sequence[bool],
) -> Dict[str, bool]:
    """
    單場廣告推介命中。

    pick_finishes / pick_odds / top2_mask 等長，對應推介列（已排序）。
    top2_mask[i]=True 表示該匹屬推介頭兩位。
    """
    finishes = []
    odds = []
    is_top2 = []
    for f, o, t2 in zip(pick_finishes, pick_odds, top2_mask):
        if f is None:
            continue
        try:
            fi = int(f)
        except (TypeError, ValueError):
            continue
        finishes.append(fi)
        try:
            odds.append(float(o) if o is not None else None)
        except (TypeError, ValueError):
            odds.append(None)
        is_top2.append(bool(t2))

    finish_set = set(finishes)

    # 1) 頭兩位命中獨贏，且冠軍賠率 ≥ 7
    win_odds7 = False
    for fi, od, t2 in zip(finishes, odds, is_top2):
        if t2 and fi == 1 and od is not None and od >= AD_WIN_ODDS_MIN:
            win_odds7 = True
            break

    # 2) 覆蓋冠＋亞，且其中一匹賠率 > 10
    qin_odds10 = False
    if {1, 2}.issubset(finish_set):
        covered_odds = [
            od
            for fi, od in zip(finishes, odds)
            if fi in (1, 2) and od is not None
        ]
        if any(od > AD_QIN_ODDS_GT for od in covered_odds):
            qin_odds10 = True

    t3 = {1, 2, 3}.issubset(finish_set)
    t4 = {1, 2, 3, 4}.issubset(finish_set)

    return {
        "win_odds7": win_odds7,
        "qin_odds10": qin_odds10,
        "t3_cover": t3,
        "t4_cover": t4,
        "any_promo": win_odds7 or qin_odds10 or t3 or t4,
    }


def attach_ad_pick_ranks_to_snapshot_rows(rows: List[dict]) -> None:
    """就地寫入 ad_pick_rank（融合推介列，最多 4；非推介為 None）。"""
    from collections import defaultdict

    from form_ai_picks import build_fused_picks

    by_race: Dict[Any, List[dict]] = defaultdict(list)
    for r in rows:
        by_race[r.get("race_id")].append(r)
        r["ad_pick_rank"] = None

    max_n = ad_pick_max()
    for _rid, group in by_race.items():
        pack = build_fused_picks(group, n_runners=len(group))
        place = (pack.get("place") or [])[:max_n]
        rank_by = {}
        for i, p in enumerate(place, start=1):
            try:
                rank_by[int(p["horse_no"])] = i
            except (TypeError, ValueError, KeyError):
                continue
        for r in group:
            try:
                hno = int(r["horse_no"])
            except (TypeError, ValueError):
                continue
            r["ad_pick_rank"] = rank_by.get(hno)
