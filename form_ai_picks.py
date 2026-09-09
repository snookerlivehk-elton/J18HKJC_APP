"""
Form AI 獨立推介／排名（不混入模型權重）。

排名鍵：ai_combo = ai_score × confidence
顯示／推介：與模型相同，場內分差比率瓜分 100%（非負百分比）。
推介隻數：動態 2～5；信心不足可整場不推。

另提供 build_fused_picks：模型×AI 第三軌（社交／廣告），不寫入因子總分。
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


def _as_prob(v: Any) -> Optional[float]:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        x = float(v)
        if not (x == x):  # NaN
            return None
        # 快照／UI 有時存 0–100 百分比
        if x > 1.0 + 1e-9:
            x = x / 100.0
        return max(0.0, x)
    except (TypeError, ValueError):
        return None


def build_fused_picks(
    rows: List[dict],
    *,
    n_runners: Optional[int] = None,
    alpha: Optional[float] = None,
    consensus_bonus: Optional[float] = None,
) -> Dict[str, Any]:
    """
    第三軌：模型份額 × AI 份額加權融合（不寫入因子總分）。

    P_fused = α·P_model + (1−α)·P_AI
    AI 整場不推／無 combo → 退回純模型。
    雙軌皆入推介列的馬可乘 consensus_bonus 後再正規化。
    """
    alpha = float(
        alpha if alpha is not None else getattr(ModelConfig, "FUSE_MODEL_ALPHA", 0.60)
    )
    alpha = min(1.0, max(0.0, alpha))
    bonus = float(
        consensus_bonus
        if consensus_bonus is not None
        else getattr(ModelConfig, "FUSE_CONSENSUS_BONUS", 1.15)
    )
    bonus = max(1.0, bonus)
    n = n_runners if n_runners is not None else len(rows)
    settle_place_n = place_cutoff(n)
    max_pick = int(getattr(ModelConfig, "PICK_MAX", 5))

    # 正規化列
    base: List[dict] = []
    for r in rows:
        d = dict(r)
        hno = d.get("horse_no")
        if hno is None and d.get("馬號") is not None:
            hno = d.get("馬號")
        try:
            d["horse_no"] = int(hno)
        except (TypeError, ValueError):
            continue
        if not d.get("horse_name"):
            d["horse_name"] = d.get("馬名")
        mp = d.get("model_win_prob")
        if mp is None:
            mp = d.get("模型勝率")
        d["model_win_prob"] = _as_prob(mp)
        if d.get("ai_combo") is None:
            d["ai_combo"] = compute_ai_combo(d.get("ai_score"), d.get("confidence"))
        base.append(d)

    empty = {
        "available": False,
        "fallback_model_only": False,
        "alpha": alpha,
        "win_n": 0,
        "place_cutoff": settle_place_n,
        "pick_n": 0,
        "win": [],
        "place": [],
        "ranked": base,
        "message": None,
    }
    if not base:
        return empty

    # 模型份額
    m_probs = []
    for r in base:
        p = r.get("model_win_prob")
        m_probs.append(0.0 if p is None else float(p))
    m_sum = sum(m_probs)
    if m_sum > 1e-12:
        m_shares = [x / m_sum for x in m_probs]
    else:
        # 無模型勝率 → 均分
        m_shares = [1.0 / len(base)] * len(base)

    ai_pack = build_ai_picks(base, n_runners=n)
    ai_ok = bool(ai_pack.get("available"))
    ai_share_by = {
        int(r["horse_no"]): float(r["ai_share"])
        for r in (ai_pack.get("ranked") or [])
        if r.get("horse_no") is not None and r.get("ai_share") is not None
    }

    if not ai_ok:
        fused = list(m_shares)
        empty_msg = ai_pack.get("message") or "AI 不可用，融合退回純模型"
        fallback = True
        a_eff = 1.0
    else:
        a_shares = [float(ai_share_by.get(int(r["horse_no"]), 0.0)) for r in base]
        a_sum = sum(a_shares)
        if a_sum > 1e-12:
            a_shares = [x / a_sum for x in a_shares]
        fused = [alpha * m + (1.0 - alpha) * a for m, a in zip(m_shares, a_shares)]
        fallback = False
        empty_msg = None
        a_eff = alpha

    # 雙軌共識加成（僅 AI 可用時）
    model_order = sorted(
        range(len(base)),
        key=lambda i: (-m_shares[i], int(base[i]["horse_no"])),
    )
    model_pick_n = select_picks_by_share([m_shares[i] for i in model_order])
    model_place_hnos = {
        int(base[i]["horse_no"]) for i in model_order[: max(1, model_pick_n)]
    }
    ai_place_hnos = {
        int(x["horse_no"])
        for x in (ai_pack.get("place") or [])
        if x.get("horse_no") is not None
    }
    if ai_ok and bonus > 1.0 + 1e-12:
        for i, r in enumerate(base):
            hno = int(r["horse_no"])
            if hno in model_place_hnos and hno in ai_place_hnos:
                fused[i] *= bonus

    f_sum = sum(fused)
    if f_sum > 1e-12:
        fused = [x / f_sum for x in fused]
    else:
        fused = [1.0 / len(base)] * len(base)

    ranked = []
    for r, fs, ms in zip(base, fused, m_shares):
        d = dict(r)
        d["fused_share"] = float(fs)
        d["fused_share_pct"] = round(float(fs) * 100.0, 2)
        d["model_share"] = float(ms)
        d["in_model_place"] = int(r["horse_no"]) in model_place_hnos
        d["in_ai_place"] = int(r["horse_no"]) in ai_place_hnos
        ranked.append(d)
    ranked.sort(
        key=lambda r: (-float(r["fused_share"]), int(r["horse_no"]))
    )
    shares = [float(r["fused_share"]) for r in ranked]
    win_n = win_pick_count_from_shares(shares)
    pick_n = select_picks_by_share(shares)
    place = ranked[: max(1, min(pick_n, max_pick, len(ranked)))]
    win = ranked[: max(1, min(win_n, len(ranked)))]

    def slim(r: dict) -> dict:
        return {
            "horse_no": r.get("horse_no"),
            "horse_name": r.get("horse_name"),
            "fused_share": r.get("fused_share"),
            "fused_share_pct": r.get("fused_share_pct"),
            "model_win_prob": r.get("model_win_prob"),
            "ai_combo": r.get("ai_combo"),
            "ai_share_pct": r.get("ai_share_pct"),
            "in_model_place": r.get("in_model_place"),
            "in_ai_place": r.get("in_ai_place"),
            "pred_rank": r.get("pred_rank"),
        }

    return {
        "available": True,
        "fallback_model_only": fallback,
        "alpha": a_eff,
        "win_n": win_n,
        "place_cutoff": settle_place_n,
        "pick_n": len(place),
        "win": [slim(r) for r in win],
        "place": [slim(r) for r in place],
        "ranked": ranked,
        "message": empty_msg,
    }


def attach_fused_shares_to_snapshot_rows(rows: List[dict]) -> None:
    """就地為快照列寫入 fused_share（依 race_id 分場計算）。"""
    from collections import defaultdict

    by_race: Dict[Any, List[dict]] = defaultdict(list)
    for r in rows:
        by_race[r.get("race_id")].append(r)
    for _rid, group in by_race.items():
        pack = build_fused_picks(group, n_runners=len(group))
        share_map = {
            int(x["horse_no"]): float(x["fused_share"])
            for x in (pack.get("ranked") or [])
            if x.get("horse_no") is not None and x.get("fused_share") is not None
        }
        for r in group:
            try:
                hno = int(r["horse_no"])
            except (TypeError, ValueError):
                r["fused_share"] = None
                continue
            r["fused_share"] = share_map.get(hno)

