"""指数评选：同一套赔率快照上的多种前六排序。

入围指名次 1、2、3（冠亚季），不是马会位置派彩口径。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PICK_LIMIT = 6
MID_SHARE_LO = 0.08
MID_SHARE_HI = 0.25

STRATEGY_SPECS: List[Tuple[str, str, str]] = [
    ("win_hot", "独赢热门", "独赢占比最高的 6 匹，也就是现在最被押注的热门。"),
    ("model", "模型份额", "按 J18 模型份额取前 6。没有模型快照时留空。"),
    ("fused", "模型乘AI", "模型份额与赛前 AI 合成份额取前 6。"),
    ("diverge", "模型与大市背离", "模型排名明显好过独赢赔率排名的马优先。"),
    ("timeline", "时间轴分段", "距开跑远用模型，临近开跑改看缩水与背离。"),
    ("place_gap", "独赢位置对不上", "同一刻位置占比明显高于独赢占比的马排前面。"),
    ("mid_band", "中间赔率带", "只留独赢隐含概率约 8% 到 25% 的马，再按临场新增占比排序。"),
    ("shorten", "赔率缩短", "现在赔率除以一段时间前的赔率，缩短最多的 6 匹。"),
    ("qin_lead", "连赢领先独赢", "连赢组合份额减去独赢份额，差值最高的 6 匹。"),
    ("gap_widen", "位置钱追上来", "位置占比减独赢占比的差距，扩大最多的 6 匹。"),
    ("new_low", "仍在压低赔率", "只留赔率仍处在这段时间新低的马，再按压低幅度排序。"),
    ("qin_partner", "大热连赢搭档", "当前独赢热门在连赢里金额最高的另外 6 个搭档。"),
    ("fct_lead", "二重彩放前面", "二重彩放在第一位的份额减去独赢份额。"),
]


def top_n(scores: Mapping[int, Optional[float]], n: int = PICK_LIMIT) -> List[int]:
    rows = [(no, float(sc)) for no, sc in scores.items() if sc is not None]
    rows.sort(key=lambda item: (-item[1], item[0]))
    return [no for no, _ in rows[:n]]


def implied_shares(odds_by_no: Mapping[int, Optional[float]]) -> Dict[int, float]:
    inv: Dict[int, float] = {}
    for no, odds in odds_by_no.items():
        if odds is None:
            continue
        try:
            value = float(odds)
        except (TypeError, ValueError):
            continue
        if value <= 1.0:
            continue
        inv[int(no)] = 1.0 / value
    total = sum(inv.values())
    if total <= 0:
        return {}
    return {no: weight / total for no, weight in inv.items()}


def _combo_shares(combos: Mapping[Tuple[int, ...], Optional[float]]) -> Dict[Tuple[int, ...], float]:
    inv: Dict[Tuple[int, ...], float] = {}
    for key, odds in combos.items():
        if odds is None:
            continue
        try:
            value = float(odds)
        except (TypeError, ValueError):
            continue
        if value <= 1.0:
            continue
        inv[tuple(int(x) for x in key)] = 1.0 / value
    total = sum(inv.values())
    if total <= 0:
        return {}
    return {key: weight / total for key, weight in inv.items()}


def _active(horses: Sequence[Mapping]) -> List[Mapping]:
    out = []
    for horse in horses:
        if horse.get("scratched"):
            continue
        try:
            int(horse.get("no"))
        except (TypeError, ValueError):
            continue
        out.append(horse)
    return out


def _odds_map(horses: Sequence[Mapping], key: str) -> Dict[int, Optional[float]]:
    out: Dict[int, Optional[float]] = {}
    for horse in _active(horses):
        no = int(horse["no"])
        raw = horse.get(key)
        if raw is None or raw == "":
            out[no] = None
            continue
        try:
            out[no] = float(raw)
        except (TypeError, ValueError):
            out[no] = None
    return out


def _model_map(horses: Sequence[Mapping], key: str) -> Dict[int, Optional[float]]:
    return _odds_map(horses, key)


def _rank_map(scores: Mapping[int, Optional[float]]) -> Dict[int, int]:
    ordered = top_n(scores, n=max(len(scores), 1))
    return {no: idx + 1 for idx, no in enumerate(ordered)}


def _shorten_ratio(horse: Mapping, prev_by_no: Mapping[int, Mapping]) -> Optional[float]:
    """小于 1 表示赔率变短。没有上一笔时，用马会给出的下跌百分比。"""
    no = int(horse["no"])
    try:
        now = float(horse.get("win_odds"))
    except (TypeError, ValueError):
        return None
    if now <= 1.0:
        return None
    prev = prev_by_no.get(no) or {}
    try:
        before = float(prev.get("win_odds"))
    except (TypeError, ValueError):
        before = None
    if before and before > 1.0:
        return now / before
    try:
        drop = float(horse.get("win_drop") or 0)
    except (TypeError, ValueError):
        drop = 0.0
    if 0 < drop < 95:
        return 1.0 - drop / 100.0
    return None


def _norm(scores: Mapping[int, Optional[float]]) -> Dict[int, float]:
    vals = [float(v) for v in scores.values() if v is not None]
    if not vals:
        return {}
    lo, hi = min(vals), max(vals)
    out: Dict[int, float] = {}
    for no, raw in scores.items():
        if raw is None:
            continue
        if hi == lo:
            out[int(no)] = 1.0
        else:
            out[int(no)] = (float(raw) - lo) / (hi - lo)
    return out


def strategy_picks(
    strategy_id: str,
    horses: Sequence[Mapping],
    *,
    qin_odds: Optional[Mapping[Tuple[int, int], Optional[float]]] = None,
    fct_odds: Optional[Mapping[Tuple[int, int], Optional[float]]] = None,
    prev_horses: Optional[Sequence[Mapping]] = None,
    odds_history: Optional[Mapping[int, Sequence[float]]] = None,
    minutes_to_post: Optional[float] = None,
    limit: int = PICK_LIMIT,
) -> List[int]:
    active = _active(horses)
    win_odds = _odds_map(active, "win_odds")
    place_odds = _odds_map(active, "place_odds")
    win_share = implied_shares(win_odds)
    place_share = implied_shares(place_odds)
    model = _model_map(active, "model_share")
    fused = _model_map(active, "fused_share")
    prev_by_no = {}
    if prev_horses:
        for horse in _active(prev_horses):
            prev_by_no[int(horse["no"])] = horse
    prev_win = implied_shares(_odds_map(list(prev_by_no.values()), "win_odds")) if prev_by_no else {}
    prev_place = implied_shares(_odds_map(list(prev_by_no.values()), "place_odds")) if prev_by_no else {}

    if strategy_id == "win_hot":
        return top_n(win_share, limit)
    if strategy_id == "model":
        return top_n(model, limit)
    if strategy_id == "fused":
        use = fused if any(v is not None for v in fused.values()) else model
        return top_n(use, limit)
    if strategy_id == "diverge":
        if not any(v is not None for v in model.values()) or not win_share:
            return []
        model_rank = _rank_map(model)
        odds_rank = _rank_map(win_share)
        gap = {
            no: float(odds_rank.get(no, 99) - model_rank.get(no, 99))
            for no in model_rank
            if no in odds_rank
        }
        return top_n(gap, limit)
    if strategy_id == "place_gap":
        gap = {}
        for no, p_share in place_share.items():
            w_share = win_share.get(no)
            if w_share is None:
                continue
            gap[no] = p_share - w_share
        return top_n(gap, limit)
    if strategy_id == "mid_band":
        scores = {}
        for no, share in win_share.items():
            if share < MID_SHARE_LO or share > MID_SHARE_HI:
                continue
            prev = prev_win.get(no)
            scores[no] = share - prev if prev is not None else share
        return top_n(scores, limit)
    if strategy_id == "shorten":
        scores = {}
        for horse in active:
            ratio = _shorten_ratio(horse, prev_by_no)
            if ratio is None:
                continue
            scores[int(horse["no"])] = -ratio
        return top_n(scores, limit)
    if strategy_id == "gap_widen":
        scores = {}
        for no, p_share in place_share.items():
            w_share = win_share.get(no)
            if w_share is None:
                continue
            now_gap = p_share - w_share
            if no not in prev_place or no not in prev_win:
                continue
            scores[no] = now_gap - (prev_place[no] - prev_win[no])
        return top_n(scores, limit)
    if strategy_id == "new_low":
        scores = {}
        history = odds_history or {}
        for horse in active:
            no = int(horse["no"])
            try:
                now = float(horse.get("win_odds"))
            except (TypeError, ValueError):
                continue
            if now <= 1.0:
                continue
            series = [float(x) for x in history.get(no, []) if x and float(x) > 1.0]
            window = series + [now]
            if len(window) < 2:
                continue
            if now > min(window) + 1e-9:
                continue
            base = window[0]
            scores[no] = -(now / base)
        return top_n(scores, limit)
    if strategy_id == "qin_lead":
        return _qin_lead(win_share, qin_odds or {}, limit)
    if strategy_id == "qin_partner":
        return _qin_partners(win_share, qin_odds or {}, limit)
    if strategy_id == "fct_lead":
        return _fct_lead(win_share, fct_odds or {}, limit)
    if strategy_id == "timeline":
        return _timeline(
            active,
            win_share=win_share,
            model=model,
            fused=fused,
            prev_by_no=prev_by_no,
            minutes_to_post=minutes_to_post,
            limit=limit,
        )
    return []


def _qin_lead(win_share: Mapping[int, float], qin_odds: Mapping, limit: int) -> List[int]:
    shares = _combo_shares({tuple(sorted(k)): v for k, v in qin_odds.items()})
    if not shares:
        return []
    acc: Dict[int, float] = {}
    for (a, b), share in shares.items():
        acc[a] = acc.get(a, 0.0) + share
        acc[b] = acc.get(b, 0.0) + share
    scores = {no: total - win_share.get(no, 0.0) for no, total in acc.items()}
    return top_n(scores, limit)


def _qin_partners(win_share: Mapping[int, float], qin_odds: Mapping, limit: int) -> List[int]:
    if not win_share:
        return []
    fav = top_n(win_share, 1)
    if not fav:
        return []
    hot = fav[0]
    shares = _combo_shares({tuple(sorted(k)): v for k, v in qin_odds.items()})
    scores: Dict[int, float] = {}
    for (a, b), share in shares.items():
        if hot not in (a, b):
            continue
        other = b if a == hot else a
        scores[other] = share
    return top_n(scores, limit)


def _fct_lead(win_share: Mapping[int, float], fct_odds: Mapping, limit: int) -> List[int]:
    shares = _combo_shares({(int(k[0]), int(k[1])): v for k, v in fct_odds.items()})
    if not shares:
        return []
    acc: Dict[int, float] = {}
    for (first, _second), share in shares.items():
        acc[first] = acc.get(first, 0.0) + share
    scores = {no: total - win_share.get(no, 0.0) for no, total in acc.items()}
    return top_n(scores, limit)


def _timeline(
    active: Sequence[Mapping],
    *,
    win_share: Mapping[int, float],
    model: Mapping[int, Optional[float]],
    fused: Mapping[int, Optional[float]],
    prev_by_no: Mapping[int, Mapping],
    minutes_to_post: Optional[float],
    limit: int,
) -> List[int]:
    base = fused if any(v is not None for v in fused.values()) else model
    base_n = _norm(base)
    shorten_scores = {}
    for horse in active:
        ratio = _shorten_ratio(horse, prev_by_no)
        if ratio is None:
            continue
        shorten_scores[int(horse["no"])] = -ratio
    short_n = _norm(shorten_scores)
    diverge = {}
    if any(v is not None for v in model.values()) and win_share:
        model_rank = _rank_map(model)
        odds_rank = _rank_map(win_share)
        diverge = {
            no: float(odds_rank.get(no, 99) - model_rank.get(no, 99))
            for no in model_rank
            if no in odds_rank
        }
    div_n = _norm(diverge)
    mins = minutes_to_post
    if mins is None or mins > 30:
        w_model, w_short, w_div = 1.0, 0.0, 0.0
    elif mins > 15:
        w_model, w_short, w_div = 0.6, 0.4, 0.0
    else:
        w_model, w_short, w_div = 0.35, 0.25, 0.40
    nos = set(base_n) | set(short_n) | set(div_n)
    if not nos and win_share:
        return top_n(win_share, limit)
    scores = {
        no: w_model * base_n.get(no, 0.0)
        + w_short * short_n.get(no, 0.0)
        + w_div * div_n.get(no, 0.0)
        for no in nos
    }
    return top_n(scores, limit)


def all_picks(horses: Sequence[Mapping], **kwargs) -> Dict[str, List[int]]:
    return {
        spec[0]: strategy_picks(spec[0], horses, **kwargs)
        for spec in STRATEGY_SPECS
    }


def finish_marks(
    picks: Sequence[int], finishes: Mapping[int, Optional[int]]
) -> List[Optional[int]]:
    marks: List[Optional[int]] = []
    for no in picks:
        try:
            pos = int(finishes.get(int(no)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            marks.append(None)
            continue
        marks.append(pos if pos in (1, 2, 3) else None)
    return marks


def placed_count(picks: Sequence[int], finishes: Mapping[int, Optional[int]]) -> int:
    return sum(1 for mark in finish_marks(picks, finishes) if mark in (1, 2, 3))


def hit_rate(placed: int, picks: int) -> Optional[float]:
    if picks <= 0:
        return None
    return placed / picks
