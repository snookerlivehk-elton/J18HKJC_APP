"""
覆蓋度持份者合成器（COVERAGE_STAKEHOLDER_HANDBOOK）。

effective = value * base_weight * coverage
total = Σ effective（不做權重重正規化）
model_coverage = Σ(w·c) / Σ(w)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from config import ModelConfig


@dataclass
class Stakeholder:
    key: str
    value: float
    present: bool
    coverage: float
    base_weight: float

    def effective(self) -> float:
        if not self.present:
            return 0.0
        c = _clamp01(self.coverage)
        return float(self.value) * float(self.base_weight) * c

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["coverage"] = _clamp01(self.coverage)
        d["effective"] = self.effective()
        return d


def _clamp01(x: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def make_stakeholder(
    key: str,
    value: float,
    *,
    present: bool,
    coverage: float,
    base_weight: float,
) -> Stakeholder:
    return Stakeholder(
        key=str(key),
        value=float(value) if present else 0.0,
        present=bool(present),
        coverage=_clamp01(coverage if present else coverage),
        base_weight=float(base_weight),
    )


def miss_coverage(default: Optional[float] = None) -> float:
    if default is not None:
        return _clamp01(default)
    return _clamp01(getattr(ModelConfig, "COVERAGE_MISS_DEFAULT", 0.0))


def hit_coverage() -> float:
    return 1.0


def coverage_from_ratio(parsed_ratio: float, *, floor: Optional[float] = None) -> float:
    """部分覆蓋：比例映射到 [floor, 1]；0 → floor（若 ratio>0）或 0。"""
    r = _clamp01(parsed_ratio)
    fl = _clamp01(
        floor
        if floor is not None
        else getattr(ModelConfig, "COVERAGE_PARTIAL_FLOOR", 0.15)
    )
    if r <= 0.0:
        return 0.0
    if r >= 1.0:
        return 1.0
    return max(fl, r)


def compose_total(
    stakeholders: Sequence[Stakeholder],
) -> Tuple[float, float, Dict[str, Dict[str, Any]]]:
    """
    回傳 (total_score, model_coverage, breakdown)。
    model_coverage = Σ(w·c) / Σ(w)；無持份者時 coverage=0。
    """
    breakdown: Dict[str, Dict[str, Any]] = {}
    total = 0.0
    w_sum = 0.0
    wc_sum = 0.0
    for s in stakeholders:
        eff = s.effective()
        total += eff
        w = float(s.base_weight)
        c = _clamp01(s.coverage)
        w_sum += abs(w)
        wc_sum += abs(w) * c
        breakdown[s.key] = s.to_dict()
    model_cov = (wc_sum / w_sum) if w_sum > 1e-12 else 0.0
    return float(total), float(model_cov), breakdown


def legacy_total_from_parts(
    *,
    z_jockey: float,
    z_trainer: float,
    z_synergy: float,
    z_draw: float,
    z_horse: float,
    z_pace: float,
    z_speed: float,
    sg_form: float,
    sg_energy: float,
    sg_delta: float,
    i_form: float = 0.0,
    i_speed: float = 0.0,
    include_interference: bool = False,
) -> float:
    """舊式滿權重加總（coverage 全當 1；干擾僅在 stakeholder 正式模式另計）。"""
    total = (
        z_jockey * ModelConfig.WEIGHT_JOCKEY
        + z_trainer * ModelConfig.WEIGHT_TRAINER
        + z_synergy * ModelConfig.WEIGHT_SYNERGY
        + z_draw * ModelConfig.WEIGHT_DRAW
        + z_horse * ModelConfig.WEIGHT_RECENT_FORM
        + z_pace * ModelConfig.WEIGHT_PACE
        + z_speed * ModelConfig.WEIGHT_SPEED_FIGURE
        + sg_form * ModelConfig.WEIGHT_SG_FORM
        + sg_energy * ModelConfig.WEIGHT_SG_ENERGY
        + sg_delta * ModelConfig.WEIGHT_SG_DELTA
    )
    if include_interference:
        total += i_form * float(getattr(ModelConfig, "WEIGHT_INTERFERENCE_FORM", 0.0))
        total += i_speed * float(getattr(ModelConfig, "WEIGHT_INTERFERENCE_SPEED", 0.0))
    return float(total)


def coverage_mode() -> str:
    return str(getattr(ModelConfig, "COVERAGE_MODE", "off") or "off").lower()


def interference_mode() -> str:
    return str(getattr(ModelConfig, "INTERFERENCE_MODE", "legacy") or "legacy").lower()


def pick_score_for_ranking(
    *,
    legacy_score: float,
    coverage_score: float,
    mode: Optional[str] = None,
) -> float:
    """
    off / shadow → 用 legacy 排序；on → 用 coverage 合成分。
    shadow 時呼叫端應同時保留兩分供對照。
    """
    m = (mode or coverage_mode()).lower()
    if m == "on":
        return float(coverage_score)
    return float(legacy_score)
