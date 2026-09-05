"""
各因子／綜合分／模型勝率 — 獨立勝出與入圍命中統計。

口徑（v1）：
  用「現行 factor_scores」對近期已完賽歷史場次做回溯排名。
  適合比較因子相對強弱以調 WEIGHT_*；非嚴格無洩漏回測。
  Speed Guide 無歷史存檔，不納入本統計。

入圍：依場內頭數 — ≤6 匹取前 2；≥7 匹取前 3（近似港隊位置）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd
from sqlalchemy import text

from config import ModelConfig
from factor_calculator import FactorCalculator
from bucket_utils import (
    make_bucket_id,
    make_band_bucket_id,
    normalize_person_name,
    synergy_name,
)
from inference_engine import scores_to_win_probs


SIGNAL_DEFS = [
    ("騎師分", "jockey_z", "WEIGHT_JOCKEY"),
    ("練馬師分", "trainer_z", "WEIGHT_TRAINER"),
    ("騎練分", "synergy_z", "WEIGHT_SYNERGY"),
    ("檔位分", "draw_z", "WEIGHT_DRAW"),
    ("近績分", "horse_z", "WEIGHT_RECENT_FORM"),
    ("步速分", "pace_z", "WEIGHT_PACE"),
    ("速度分", "speed_z", "WEIGHT_SPEED_FIGURE"),
    ("綜合總分", "total_score", None),
    ("模型勝率", "model_win_prob", None),
]


def place_cutoff(n_runners: int) -> int:
    if n_runners <= 6:
        return 2
    return 3


@dataclass
class SignalStats:
    signal: str
    n_races: int
    n_scored: int
    win_hits: int
    place_hits: int
    baseline_win: float
    coverage: float

    @property
    def win_rate(self) -> float:
        return self.win_hits / self.n_scored if self.n_scored else 0.0

    @property
    def place_rate(self) -> float:
        return self.place_hits / self.n_scored if self.n_scored else 0.0

    def as_dict(self) -> dict:
        return {
            "訊號": self.signal,
            "有效場次": self.n_scored,
            "總場次": self.n_races,
            "覆蓋率%": round(self.coverage * 100, 1),
            "獨贏命中": self.win_hits,
            "獨贏率%": round(self.win_rate * 100, 2),
            "入圍命中": self.place_hits,
            "入圍率%": round(self.place_rate * 100, 2),
            "隨機獨贏基準%": round(self.baseline_win * 100, 2),
            "獨贏相對隨機": round(self.win_rate / self.baseline_win, 2)
            if self.baseline_win > 1e-9
            else None,
        }


class FactorCalibration:
    def __init__(self):
        self.calc = FactorCalculator()

    def fetch_recent_races(self, lookback_days: int = 90, max_races: int = 400) -> pd.DataFrame:
        q = text(
            f"""
            WITH ranked AS (
                SELECT
                    m.racing_date,
                    r.race_id,
                    r.course,
                    r.track,
                    r.distance_m,
                    ru.jockey_name,
                    ru.trainer_name,
                    ru.horse_name,
                    ru.finish_order_num,
                    ru.bar_draw AS draw,
                    COUNT(*) OVER (PARTITION BY r.race_id) AS n_runners
                FROM runners ru
                JOIN races r ON ru.race_id = r.race_id
                JOIN race_meetings m ON r.meeting_id = m.meeting_id
                WHERE ru.finish_order_num IS NOT NULL
                  AND r.distance_m IS NOT NULL
                  AND m.racing_date >= (CURRENT_DATE - INTERVAL '{int(lookback_days)} days')
                  AND m.racing_date < CURRENT_DATE
            )
            SELECT * FROM ranked
            WHERE n_runners >= 4
            ORDER BY racing_date DESC, race_id
            """
        )
        try:
            df = pd.read_sql(q, self.calc.engine)
        except Exception:
            df = self._fetch_recent_races_fallback(lookback_days)

        if df.empty:
            return df

        race_ids = df["race_id"].drop_duplicates().head(max_races).tolist()
        df = df[df["race_id"].isin(race_ids)].copy()
        return self._prepare_runners(df)

    def _fetch_recent_races_fallback(self, lookback_days: int) -> pd.DataFrame:
        q = text(
            """
            SELECT
                m.racing_date,
                r.race_id, r.course, r.track, r.distance_m,
                ru.jockey_name, ru.trainer_name, ru.horse_name,
                ru.finish_order_num, ru.bar_draw AS draw
            FROM runners ru
            JOIN races r ON ru.race_id = r.race_id
            JOIN race_meetings m ON r.meeting_id = m.meeting_id
            WHERE ru.finish_order_num IS NOT NULL
              AND r.distance_m IS NOT NULL
            """
        )
        df = pd.read_sql(q, self.calc.engine)
        if df.empty:
            return df
        df["racing_date"] = pd.to_datetime(df["racing_date"])
        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=lookback_days)
        today = pd.Timestamp.today().normalize()
        df = df[(df["racing_date"] >= cutoff) & (df["racing_date"] < today)]
        if df.empty:
            return df
        df["n_runners"] = df.groupby("race_id")["finish_order_num"].transform("count")
        return df[df["n_runners"] >= 4].copy()

    def _prepare_runners(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["racing_date"] = pd.to_datetime(df["racing_date"])
        df["jockey_name"] = df["jockey_name"].apply(normalize_person_name)
        df["trainer_name"] = df["trainer_name"].apply(normalize_person_name)
        df["horse_name"] = df["horse_name"].apply(normalize_person_name)
        df["fine_bucket"] = df.apply(
            lambda r: make_bucket_id(
                race_id=r["race_id"],
                course=r["course"],
                track=r["track"],
                distance_m=r["distance_m"],
            ),
            axis=1,
        )
        df["band_bucket"] = df.apply(
            lambda r: make_band_bucket_id(
                race_id=r["race_id"],
                course=r["course"],
                distance_m=r["distance_m"],
            ),
            axis=1,
        )
        df["synergy"] = df.apply(
            lambda r: synergy_name(r["jockey_name"], r["trainer_name"]), axis=1
        )
        df["draw_group"] = df["draw"].apply(self.calc._assign_draw_group)
        return df

    def _build_lookup(self) -> dict:
        scores = self.calc.load_factor_scores(
            factor_types=["JOCKEY", "TRAINER", "SYNERGY", "DRAW", "HORSE", "PACE", "SPEED"]
        )
        lookup = {}
        if scores is None or scores.empty:
            return lookup
        for _, row in scores.iterrows():
            key = (str(row["factor_type"]), str(row["bucket_id"]), str(row["entity_name"]))
            lookup[key] = float(row["z_score"])
        return lookup

    @staticmethod
    def _lz(lookup: dict, ft: str, bucket: str, name: str):
        key = (ft, bucket, name)
        if key in lookup:
            return lookup[key], True
        return 0.0, False

    def score_runners(self, df: pd.DataFrame, lookup: dict) -> pd.DataFrame:
        rows = []
        for _, r in df.iterrows():
            band = r["band_bucket"]
            fine = r["fine_bucket"]
            zj, hj = self._lz(lookup, "JOCKEY", band, r["jockey_name"])
            zt, ht = self._lz(lookup, "TRAINER", band, r["trainer_name"])
            zs, hs = self._lz(lookup, "SYNERGY", band, r["synergy"])
            zd, hd = self._lz(lookup, "DRAW", fine, r["draw_group"])
            zh, hh = self._lz(lookup, "HORSE", band, r["horse_name"])
            zp, hp = self._lz(lookup, "PACE", "GLOBAL", r["horse_name"])
            zv, hv = self._lz(lookup, "SPEED", "GLOBAL", r["horse_name"])

            total = (
                zj * ModelConfig.WEIGHT_JOCKEY
                + zt * ModelConfig.WEIGHT_TRAINER
                + zs * ModelConfig.WEIGHT_SYNERGY
                + zd * ModelConfig.WEIGHT_DRAW
                + zh * ModelConfig.WEIGHT_RECENT_FORM
                + zp * ModelConfig.WEIGHT_PACE
                + zv * ModelConfig.WEIGHT_SPEED_FIGURE
            )
            hit_n = int(hj) + int(ht) + int(hs) + int(hd) + int(hh) + int(hp) + int(hv)
            rows.append(
                {
                    **{c: r[c] for c in df.columns},
                    "jockey_z": zj,
                    "trainer_z": zt,
                    "synergy_z": zs,
                    "draw_z": zd,
                    "horse_z": zh,
                    "pace_z": zp,
                    "speed_z": zv,
                    "total_score": total,
                    "factor_hits": hit_n,
                }
            )

        out = pd.DataFrame(rows)
        if out.empty:
            return out

        probs = []
        for _, g in out.groupby("race_id", sort=False):
            p = scores_to_win_probs(
                g["total_score"].to_numpy(), ModelConfig.SOFTMAX_TEMPERATURE
            )
            probs.append(pd.Series(p, index=g.index))
        out["model_win_prob"] = pd.concat(probs).sort_index()
        return out

    def evaluate(
        self,
        lookback_days: int = 90,
        max_races: int = 400,
        min_factor_hits: int = 2,
    ) -> Tuple[pd.DataFrame, dict]:
        raw = self.fetch_recent_races(lookback_days=lookback_days, max_races=max_races)
        meta = {
            "lookback_days": lookback_days,
            "max_races": max_races,
            "n_runner_rows": len(raw),
            "n_races": int(raw["race_id"].nunique()) if not raw.empty else 0,
            "note": "現行 factor_scores 回溯；適合相對比較，非嚴格時點回測。不含 Speed Guide。",
        }
        if raw.empty:
            return pd.DataFrame(), meta

        lookup = self._build_lookup()
        if not lookup:
            meta["error"] = "factor_scores 為空"
            return pd.DataFrame(), meta

        scored = self.score_runners(raw, lookup)
        race_hit = scored.groupby("race_id")["factor_hits"].mean()
        ok_races = race_hit[race_hit >= min_factor_hits].index
        scored = scored[scored["race_id"].isin(ok_races)].copy()
        meta["n_races_after_filter"] = int(scored["race_id"].nunique())
        meta["avg_runners"] = (
            float(scored.groupby("race_id").size().mean()) if not scored.empty else 0.0
        )

        if scored.empty:
            return pd.DataFrame(), meta

        baseline = 1.0 / meta["avg_runners"] if meta["avg_runners"] else 0.0
        n_races = meta["n_races_after_filter"]
        stats: List[SignalStats] = []

        for label, col, _w in SIGNAL_DEFS:
            win_hits = place_hits = scored_races = 0
            for _, g in scored.groupby("race_id"):
                vals = pd.to_numeric(g[col], errors="coerce").fillna(0.0)
                if (vals.abs() < 1e-12).all():
                    continue
                scored_races += 1
                top_val = vals.max()
                contenders = g.loc[vals == top_val]
                finishes = contenders["finish_order_num"].astype(int)
                n = int(g["n_runners"].iloc[0]) if "n_runners" in g.columns else len(g)
                cut = place_cutoff(n)
                if (finishes == 1).any():
                    win_hits += 1
                if (finishes <= cut).any():
                    place_hits += 1

            stats.append(
                SignalStats(
                    signal=label,
                    n_races=n_races,
                    n_scored=scored_races,
                    win_hits=win_hits,
                    place_hits=place_hits,
                    baseline_win=baseline,
                    coverage=scored_races / n_races if n_races else 0.0,
                )
            )

        stats_df = pd.DataFrame([s.as_dict() for s in stats])
        if not stats_df.empty:
            stats_df = stats_df.sort_values("獨贏率%", ascending=False).reset_index(drop=True)
        return stats_df, meta
