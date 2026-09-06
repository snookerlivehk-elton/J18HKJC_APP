"""
Form AI 獨立推介／排名（不混入模型權重）。

排名鍵：ai_combo = ai_score × confidence
顯示／推介：與模型相同，場內分差比率瓜分 100%（非負百分比）。
推介隻數：動態 2～5；信心不足可整場不推。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from config import ModelConfig
from factor_calibration import place_cutoff
from score_share import (
    attach_share_pct,
    select_picks_by_share,
    win_pick_count_from_shares,
)


def compute_ai_combo(ai_score: Any, confidence: Any) -> Optional[float]:
    try:
        if ai_score is None or (isinstance(ai_score, float) and pd.isna(ai_score)):
            return None
        sc = float(ai_score)
        cf = (
            0.0
            if confidence is None or (isinstance(confidence, float) and pd.isna(confidence))
            else float(confidence)
        )
        return round(sc * cf, 4)
    except (TypeError, ValueError):
        return None


def win_pick_count(values: Sequence[float], *, ratio: float = 0.70) -> int:
    """相容舊介面：對已排序數值（份額或 combo）爭勝 1～2。"""
    return win_pick_count_from_shares(values, ratio=ratio)


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
      win / place: slim list（place＝動態推介，最多 PICK_MAX）
      ai_share_pct 寫入 ranked
      available / skipped_low_confidence
    """
    ranked = sort_by_ai_combo(rows)
    attach_share_pct(ranked, "ai_combo", out_prob_key="ai_share", out_pct_key="ai_share_pct")
    with_ai = [r for r in ranked if r.get("ai_combo") is not None]
    n = n_runners if n_runners is not None else len(ranked)
    settle_place_n = place_cutoff(n)  # 結算入圍＝前 4
    max_pick = int(getattr(ModelConfig, "PICK_MAX", 5))
    min_conf = float(getattr(ModelConfig, "PICK_AI_MIN_CONFIDENCE", 0.30))
    min_share = float(getattr(ModelConfig, "PICK_AI_MIN_SHARE", 0.06))

    empty = {
        "available": False,
        "skipped_low_confidence": False,
        "win_n": 0,
        "place_cutoff": settle_place_n,
        "pick_n": 0,
        "win": [],
        "place": [],
        "ranked": ranked,
    }
    if not with_ai:
        return empty

    max_cf = max(float(r.get("confidence") or 0) for r in with_ai)
    if max_cf < min_conf:
        empty["skipped_low_confidence"] = True
        empty["available"] = False
        empty["message"] = f"AI 最高信心 {max_cf:.0%} ＜ {min_conf:.0%}，本場不推介"
        return empty

    # 有份額者依份額排序（與 combo 序通常一致；同分差時以份額為準）
    with_share = [r for r in with_ai if r.get("ai_share") is not None]
    with_share.sort(key=lambda r: (-float(r["ai_share"]), -float(r.get("confidence") or 0)))
    shares = [float(r["ai_share"]) for r in with_share]
    if not shares:
        return empty

    win_n = win_pick_count_from_shares(shares)
    pick_n = select_picks_by_share(shares, min_share=min_share)
    # 再濾：單匹份額過低且非爭勝 → 不納入推介列
    place = []
    for i, r in enumerate(with_share[:pick_n]):
        sh = float(r["ai_share"])
        if i < win_n or sh >= min_share or sh >= shares[0] * float(
            getattr(ModelConfig, "PICK_REL_TO_LEADER", 0.45)
        ):
            place.append(r)
    if not place:
        place = with_share[: max(1, win_n)]
    place = place[:max_pick]
    win = with_share[:win_n]

    def slim(r: dict) -> dict:
        return {
            "horse_no": r.get("horse_no"),
            "horse_name": r.get("horse_name") or r.get("馬名"),
            "ai_score": r.get("ai_score"),
            "confidence": r.get("confidence"),
            "ai_combo": r.get("ai_combo"),
            "ai_share": r.get("ai_share"),
            "ai_share_pct": r.get("ai_share_pct"),
            "pred_rank": r.get("pred_rank"),
            "model_win_prob": r.get("model_win_prob"),
        }

    return {
        "available": True,
        "skipped_low_confidence": False,
        "win_n": win_n,
        "place_cutoff": settle_place_n,
        "pick_n": len(place),
        "win": [slim(r) for r in win],
        "place": [slim(r) for r in place],
        "ranked": ranked,
        "message": None,
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
