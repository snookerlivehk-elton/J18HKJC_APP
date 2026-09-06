"""
場內評分：以分差比率瓜分 100%（非負、加總=1）。

d_i = s_i − min(s)  →  P_i = d_i / Σd
全場同分 → 均分。

推介：依份額與相對頭馬／累積份額動態取 2～5 匹；過弱可略過。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from config import ModelConfig


def scores_to_share_probs(scores) -> np.ndarray:
    """任意實數分數 → 場內非負份額（加總=1）。"""
    arr = np.asarray(scores, dtype=float)
    if arr.size == 0:
        return arr
    if arr.size == 1:
        return np.array([1.0], dtype=float)
    finite = np.isfinite(arr)
    if not finite.any():
        return np.full(arr.size, 1.0 / arr.size)
    # 缺值當場內最低（不搶份額）
    fill = float(np.nanmin(arr[finite]))
    x = np.where(finite, arr, fill)
    d = x - float(np.min(x))
    s = float(d.sum())
    if s <= 1e-12:
        return np.full(arr.size, 1.0 / arr.size)
    return d / s


def scores_to_win_probs_share(scores) -> np.ndarray:
    """別名：總分 → 模型勝率（分差瓜分）。"""
    return scores_to_share_probs(scores)


def select_picks_by_share(
    probs: Sequence[float],
    *,
    max_n: Optional[int] = None,
    min_n: Optional[int] = None,
    min_share: Optional[float] = None,
    rel_to_leader: Optional[float] = None,
    cumulative_cap: Optional[float] = None,
) -> int:
    """
    依已排序（高→低）的份額陣列，回傳應推介幾匹。
    規則：至少 min_n；之後若低於 min_share 且低於頭馬×rel 則停；
    或累積份額達 cap 且已達 min_n 則停；最多 max_n。
    """
    p = [float(x) for x in probs if x is not None and np.isfinite(float(x))]
    if not p:
        return 0
    max_n = int(max_n if max_n is not None else getattr(ModelConfig, "PICK_MAX", 5))
    min_n = int(min_n if min_n is not None else getattr(ModelConfig, "PICK_MIN", 2))
    min_share = float(
        min_share if min_share is not None else getattr(ModelConfig, "PICK_MIN_SHARE", 0.07)
    )
    rel = float(
        rel_to_leader
        if rel_to_leader is not None
        else getattr(ModelConfig, "PICK_REL_TO_LEADER", 0.45)
    )
    cap = float(
        cumulative_cap
        if cumulative_cap is not None
        else getattr(ModelConfig, "PICK_CUMULATIVE_CAP", 0.78)
    )
    max_n = max(1, min(max_n, len(p)))
    min_n = max(1, min(min_n, max_n))

    leader = p[0]
    n = 1
    cum = p[0]
    for i in range(1, max_n):
        pi = p[i]
        # 未滿下限：仍納入（除非份額幾乎為 0）
        if i < min_n:
            if pi <= 1e-12 and leader > 1e-9:
                break
            n = i + 1
            cum += pi
            continue
        # 過弱：低於絕對門檻且遠低頭馬 → 停
        if pi < min_share and (leader <= 1e-12 or pi < leader * rel):
            break
        n = i + 1
        cum += pi
        if cum >= cap:
            break
    return n


def win_pick_count_from_shares(probs: Sequence[float], *, ratio: float = 0.70) -> int:
    """爭勝：1 匹；第二名 ≥ 頭馬×ratio 則 2。"""
    p = [float(x) for x in probs]
    if not p:
        return 0
    if len(p) == 1:
        return 1
    if p[0] > 0 and p[1] >= p[0] * ratio:
        return 2
    return 1


def attach_share_pct(
    rows: List[dict],
    score_key: str,
    *,
    out_prob_key: str = "share",
    out_pct_key: str = "share_pct",
) -> List[dict]:
    """就地寫入場內份額；缺分的列份額為 None，不參與瓜分。"""
    idxs = []
    vals = []
    for i, r in enumerate(rows):
        v = r.get(score_key)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(fv):
            continue
        idxs.append(i)
        vals.append(fv)
    for r in rows:
        r[out_prob_key] = None
        r[out_pct_key] = None
    if not vals:
        return rows
    shares = scores_to_share_probs(vals)
    for i, sh in zip(idxs, shares):
        rows[i][out_prob_key] = float(sh)
        rows[i][out_pct_key] = round(float(sh) * 100.0, 1)
    return rows
