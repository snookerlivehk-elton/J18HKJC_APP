"""
Form AI 獨立推介／排名（不混入模型權重）。

排名鍵：ai_combo = ai_score × confidence
爭勝／入圍規則與模型軌道對齊，方便並排比較與命中統計。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from factor_calibration import place_cutoff


def compute_ai_combo(ai_score: Any, confidence: Any) -> Optional[float]:
    try:
        if ai_score is None or (isinstance(ai_score, float) and pd.isna(ai_score)):
            return None
        sc = float(ai_score)
        cf = 0.0 if confidence is None or (isinstance(confidence, float) and pd.isna(confidence)) else float(confidence)
        return round(sc * cf, 4)
    except (TypeError, ValueError):
        return None


def win_pick_count(values: Sequence[float], *, ratio: float = 0.70) -> int:
    """與模型勝率相同：第二名 ≥ 第一名 × ratio 則並列爭勝 2 匹。"""
    if not values:
        return 0
    if len(values) == 1:
        return 1
    v0, v1 = float(values[0]), float(values[1])
    if v0 > 0 and v1 >= v0 * ratio:
        return 2
    return 1


def sort_by_ai_combo(rows: List[dict]) -> List[dict]:
    """
    rows 需含 horse_no；可選 ai_score / confidence / ai_combo。
    無 combo 的列排最後。同分：信心高 → ai_score 高。
    """
    enriched = []
    for r in rows:
        d = dict(r)
        combo = d.get("ai_combo")
        if combo is None:
            combo = compute_ai_combo(d.get("ai_score"), d.get("confidence"))
        d["ai_combo"] = combo
        enriched.append(d)

    def key(d: dict):
        c = d.get("ai_combo")
        if c is None:
            return (1, 0.0, 0.0, 0.0)
        cf = float(d.get("confidence") or 0)
        sc = float(d.get("ai_score") or 0)
        return (0, -float(c), -cf, -sc)

    return sorted(enriched, key=key)


def build_ai_picks(
    rows: List[dict],
    *,
    n_runners: Optional[int] = None,
) -> Dict[str, Any]:
    """
    回傳獨立 AI 推介：
      win / place: slim list
      place_cutoff / win_n
      available: 是否至少有一匹有 combo
    """
    ranked = sort_by_ai_combo(rows)
    with_ai = [r for r in ranked if r.get("ai_combo") is not None]
    n = n_runners if n_runners is not None else len(ranked)
    place_n = place_cutoff(n)
    if not with_ai:
        return {
            "available": False,
            "win_n": 0,
            "place_cutoff": place_n,
            "win": [],
            "place": [],
            "ranked": ranked,
        }

    combos = [float(r["ai_combo"]) for r in with_ai]
    win_n = win_pick_count(combos)
    win = with_ai[:win_n]
    place = with_ai[:place_n]

    def slim(r: dict) -> dict:
        return {
            "horse_no": r.get("horse_no"),
            "horse_name": r.get("horse_name") or r.get("馬名"),
            "ai_score": r.get("ai_score"),
            "confidence": r.get("confidence"),
            "ai_combo": r.get("ai_combo"),
            "pred_rank": r.get("pred_rank"),
            "model_win_prob": r.get("model_win_prob"),
        }

    return {
        "available": True,
        "win_n": win_n,
        "place_cutoff": place_n,
        "win": [slim(r) for r in win],
        "place": [slim(r) for r in place],
        "ranked": ranked,
    }


def ai_map_from_dataframe(ai_df: Optional[pd.DataFrame]) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    if ai_df is None or ai_df.empty:
        return out
    for _, a in ai_df.iterrows():
        try:
            hno = int(a["horse_no"])
        except (TypeError, ValueError):
            continue
        sc = float(a["ai_score"]) if pd.notna(a.get("ai_score")) else None
        cf = float(a["confidence"]) if pd.notna(a.get("confidence")) else None
        out[hno] = {
            "ai_score": sc,
            "confidence": cf,
            "ai_combo": compute_ai_combo(sc, cf),
            "summary": a.get("summary"),
        }
    return out
