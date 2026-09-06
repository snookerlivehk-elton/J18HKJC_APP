"""
賽前預測快照 → 賽後 J18 賽果結算 → 各因子／總分／勝率／AI 獨立軌道命中統計。

流程：
  1. snapshot_meeting(racing_date, course)  — 賽前寫入 prediction_snapshots
     （含 ai_score／confidence／ai_combo，不混入模型權重）
  2. settle_pending() — 用 runners.finish_order_num 回填，標記 batch settled
  3. evaluate_settled() — 按快照分數算各訊號獨贏／入圍率（含 AI評價×信心）

入圍：結算定義為前 4（場內少於 4 匹則取全場）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import uuid4

import pandas as pd
from sqlalchemy import text, create_engine

from config import ModelConfig
from factor_calculator import FactorCalculator
from inference_engine import InferenceEngine, scores_to_win_probs
from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH
import os

if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv(
        "DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db"
    )

SIGNAL_DEFS = [
    ("騎師分", "z_jockey", "WEIGHT_JOCKEY"),
    ("練馬師分", "z_trainer", "WEIGHT_TRAINER"),
    ("騎練分", "z_synergy", "WEIGHT_SYNERGY"),
    ("檔位分", "z_draw", "WEIGHT_DRAW"),
    ("近績分", "z_horse", "WEIGHT_RECENT_FORM"),
    ("步速分", "z_pace", "WEIGHT_PACE"),
    ("速度分", "z_speed", "WEIGHT_SPEED_FIGURE"),
    ("SG貢獻", "sg_contrib", None),
    ("綜合總分", "total_score", None),
    ("模型勝率", "model_win_prob", None),
    # 獨立軌道：Form AI 馬評（評價×信心），不混入模型權重
    ("AI評價×信心", "ai_combo", None),
]


def place_cutoff(n_runners: int) -> int:
    """結算入圍：前 4；場內少於 4 匹則取全場。"""
    n = int(n_runners or 0)
    if n <= 0:
        return 4
    return min(4, n)


DDL_PG = """
CREATE TABLE IF NOT EXISTS prediction_snapshot_batches (
    batch_id VARCHAR(64) PRIMARY KEY,
    racing_date DATE NOT NULL,
    course VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    settled_at TIMESTAMPTZ,
    note TEXT
);

CREATE TABLE IF NOT EXISTS prediction_snapshots (
    id SERIAL PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL REFERENCES prediction_snapshot_batches(batch_id) ON DELETE CASCADE,
    race_id VARCHAR(50) NOT NULL,
    horse_no INT NOT NULL,
    horse_name VARCHAR(100),
    jockey_name VARCHAR(50),
    trainer_name VARCHAR(50),
    draw INT,
    z_jockey NUMERIC,
    z_trainer NUMERIC,
    z_synergy NUMERIC,
    z_draw NUMERIC,
    z_horse NUMERIC,
    z_pace NUMERIC,
    z_speed NUMERIC,
    sg_contrib NUMERIC,
    total_score NUMERIC,
    model_win_prob NUMERIC,
    pred_rank INT,
    ai_score NUMERIC,
    confidence NUMERIC,
    ai_combo NUMERIC,
    finish_order_num INT,
    UNIQUE (batch_id, race_id, horse_no)
);
CREATE INDEX IF NOT EXISTS idx_pred_snap_race ON prediction_snapshots(race_id);
CREATE INDEX IF NOT EXISTS idx_pred_snap_batch ON prediction_snapshots(batch_id);
"""

DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS prediction_snapshot_batches (
    batch_id TEXT PRIMARY KEY,
    racing_date DATE NOT NULL,
    course TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    settled_at TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS prediction_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    race_id TEXT NOT NULL,
    horse_no INTEGER NOT NULL,
    horse_name TEXT,
    jockey_name TEXT,
    trainer_name TEXT,
    draw INTEGER,
    z_jockey REAL,
    z_trainer REAL,
    z_synergy REAL,
    z_draw REAL,
    z_horse REAL,
    z_pace REAL,
    z_speed REAL,
    sg_contrib REAL,
    total_score REAL,
    model_win_prob REAL,
    pred_rank INTEGER,
    ai_score REAL,
    confidence REAL,
    ai_combo REAL,
    finish_order_num INTEGER,
    UNIQUE (batch_id, race_id, horse_no),
    FOREIGN KEY (batch_id) REFERENCES prediction_snapshot_batches(batch_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pred_snap_race ON prediction_snapshots(race_id);
CREATE INDEX IF NOT EXISTS idx_pred_snap_batch ON prediction_snapshots(batch_id);
"""


class FactorCalibration:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL_SYNC)
        self.calc = FactorCalculator()
        self.infer = InferenceEngine()
        self.ensure_tables()

    def ensure_tables(self):
        ddl = DDL_SQLITE if USE_SQLITE else DDL_PG
        with self.engine.begin() as conn:
            for stmt in ddl.split(";"):
                s = stmt.strip()
                if s:
                    conn.execute(text(s))
            self._ensure_ai_snapshot_columns(conn)

    def _ensure_ai_snapshot_columns(self, conn):
        """既有庫補欄：AI 獨立軌道（不影響舊快照結算）。"""
        cols = ("ai_score", "confidence", "ai_combo")
        for col in cols:
            try:
                if USE_SQLITE:
                    conn.execute(text(f"ALTER TABLE prediction_snapshots ADD COLUMN {col} REAL"))
                else:
                    conn.execute(
                        text(
                            f"ALTER TABLE prediction_snapshots "
                            f"ADD COLUMN IF NOT EXISTS {col} NUMERIC"
                        )
                    )
            except Exception:
                pass

    # ---------- 賽前快照 ----------
    def snapshot_meeting(
        self,
        racing_date: Optional[str] = None,
        course: Optional[str] = None,
        note: str = "",
    ) -> dict:
        """
        對 upcoming 賽日全部場次跑 predict_race，寫入一批快照。
        racing_date: YYYY-MM-DD；省略則取 upcoming 最新一日。
        """
        races = self.infer.get_upcoming_races()
        if races.empty:
            return {"ok": False, "error": "無 upcoming 賽事"}

        races = races.copy()
        races["_d"] = races["racing_date"].astype(str).str[:10]
        if racing_date:
            racing_date = racing_date.replace("/", "-")[:10]
            races = races[races["_d"] == racing_date]
        else:
            racing_date = races["_d"].max()
            races = races[races["_d"] == racing_date]

        if course:
            races = races[races["course"].astype(str).str.upper() == course.upper()]
        if races.empty:
            return {"ok": False, "error": f"找不到 {racing_date} {course or ''} 排位"}

        course = str(races.iloc[0]["course"])
        batch_id = f"{racing_date.replace('-', '')}{course}_{uuid4().hex[:8]}"

        from form_ai_analyst import FormAIAnalyst
        from form_ai_picks import compute_ai_combo

        ai_by_race: dict = {}
        try:
            analyst = FormAIAnalyst()
            for rid in races["race_id"].astype(str).unique():
                ai_by_race[rid] = {}
                try:
                    adf = analyst.load_ai_for_race(rid)
                    if adf is None or adf.empty:
                        continue
                    for _, a in adf.iterrows():
                        hno = int(a["horse_no"])
                        sc = float(a["ai_score"]) if pd.notna(a.get("ai_score")) else None
                        cf = float(a["confidence"]) if pd.notna(a.get("confidence")) else None
                        ai_by_race[rid][hno] = (sc, cf, compute_ai_combo(sc, cf))
                except Exception:
                    continue
        except Exception:
            ai_by_race = {}

        rows = []
        for _, race in races.iterrows():
            rid = race["race_id"]
            pred, _info, _meta = self.infer.predict_race(rid)
            if pred is None or pred.empty:
                continue
            ai_map = ai_by_race.get(str(rid), {})
            for _, p in pred.iterrows():
                hno = int(p["馬號"])
                sc, cf, combo = ai_map.get(hno, (None, None, None))
                rows.append(
                    {
                        "batch_id": batch_id,
                        "race_id": rid,
                        "horse_no": hno,
                        "horse_name": p.get("馬名"),
                        "jockey_name": p.get("騎師"),
                        "trainer_name": p.get("練馬師"),
                        "draw": int(p["檔位"]) if pd.notna(p.get("檔位")) else None,
                        "z_jockey": float(p.get("騎師分") or 0),
                        "z_trainer": float(p.get("練馬師分") or 0),
                        "z_synergy": float(p.get("騎練分") or 0),
                        "z_draw": float(p.get("檔位分") or 0),
                        "z_horse": float(p.get("近績分") or 0),
                        "z_pace": float(p.get("步速分") or 0),
                        "z_speed": float(p.get("速度分") or 0),
                        "sg_contrib": float(p.get("SG貢獻") or 0),
                        "total_score": float(p.get("總預測分") or 0),
                        "model_win_prob": float(p.get("模型勝率") or 0),
                        "pred_rank": int(p["預測排名"]) if pd.notna(p.get("預測排名")) else None,
                        "ai_score": sc,
                        "confidence": cf,
                        "ai_combo": combo,
                        "finish_order_num": None,
                    }
                )

        if not rows:
            return {"ok": False, "error": "預測結果為空（請先重算 factor_scores）"}

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO prediction_snapshot_batches
                    (batch_id, racing_date, course, note)
                    VALUES (:batch_id, :racing_date, :course, :note)
                    """
                ),
                {
                    "batch_id": batch_id,
                    "racing_date": racing_date,
                    "course": course,
                    "note": note or "pre-race snapshot",
                },
            )
            for r in rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO prediction_snapshots (
                            batch_id, race_id, horse_no, horse_name, jockey_name, trainer_name, draw,
                            z_jockey, z_trainer, z_synergy, z_draw, z_horse, z_pace, z_speed,
                            sg_contrib, total_score, model_win_prob, pred_rank,
                            ai_score, confidence, ai_combo, finish_order_num
                        ) VALUES (
                            :batch_id, :race_id, :horse_no, :horse_name, :jockey_name, :trainer_name, :draw,
                            :z_jockey, :z_trainer, :z_synergy, :z_draw, :z_horse, :z_pace, :z_speed,
                            :sg_contrib, :total_score, :model_win_prob, :pred_rank,
                            :ai_score, :confidence, :ai_combo, :finish_order_num
                        )
                        """
                    ),
                    r,
                )

        n_ai = sum(1 for r in rows if r.get("ai_combo") is not None)
        return {
            "ok": True,
            "batch_id": batch_id,
            "racing_date": racing_date,
            "course": course,
            "n_rows": len(rows),
            "n_races": int(races["race_id"].nunique()),
            "n_with_ai": n_ai,
        }

    # ---------- 賽後結算 ----------
    def settle_pending(self) -> dict:
        """
        對未結算 batch：若 historical runners 已有該 race_id 名次，則回填 finish_order_num。
        當 batch 內所有 race 都有至少一匹完賽名次時，標記 settled_at。
        """
        batches = pd.read_sql(
            text(
                "SELECT batch_id, racing_date, course FROM prediction_snapshot_batches "
                "WHERE settled_at IS NULL ORDER BY racing_date"
            ),
            self.engine,
        )
        if batches.empty:
            return {"ok": True, "settled_batches": [], "updated_rows": 0}

        updated = 0
        settled = []
        for _, b in batches.iterrows():
            batch_id = b["batch_id"]
            snaps = pd.read_sql(
                text(
                    "SELECT id, race_id, horse_no, horse_name FROM prediction_snapshots "
                    "WHERE batch_id = :b AND finish_order_num IS NULL"
                ),
                self.engine,
                params={"b": batch_id},
            )
            if snaps.empty:
                # 已全部填完名次
                self._mark_settled(batch_id)
                settled.append(batch_id)
                continue

            race_ids = snaps["race_id"].unique().tolist()
            results = self._fetch_results_for_races(race_ids)
            if results.empty:
                continue

            # 匹配：優先 race_id + horse_no；fallback race_id + 正規化馬名
            from bucket_utils import normalize_person_name

            results = results.copy()
            results["horse_key"] = results["horse_name"].apply(normalize_person_name)
            snaps = snaps.copy()
            snaps["horse_key"] = snaps["horse_name"].apply(normalize_person_name)

            # horse_no in historical may not match upcoming numbering — match by name
            merge = snaps.merge(
                results[["race_id", "horse_key", "finish_order_num"]],
                on=["race_id", "horse_key"],
                how="left",
                suffixes=("", "_res"),
            )

            with self.engine.begin() as conn:
                for _, row in merge.iterrows():
                    if pd.isna(row.get("finish_order_num")):
                        continue
                    conn.execute(
                        text(
                            "UPDATE prediction_snapshots SET finish_order_num = :f "
                            "WHERE id = :id"
                        ),
                        {"f": int(row["finish_order_num"]), "id": int(row["id"])},
                    )
                    updated += 1

            # 檢查是否整批可結算：每個 race_id 至少有完賽馬
            left = pd.read_sql(
                text(
                    "SELECT race_id, COUNT(*) AS n, "
                    "SUM(CASE WHEN finish_order_num IS NOT NULL THEN 1 ELSE 0 END) AS filled "
                    "FROM prediction_snapshots WHERE batch_id = :b GROUP BY race_id"
                ),
                self.engine,
                params={"b": batch_id},
            )
            if not left.empty and (left["filled"] > 0).all():
                # 要求多數馬有名次（≥50%）才算結算完成
                if (left["filled"] / left["n"] >= 0.5).all():
                    self._mark_settled(batch_id)
                    settled.append(batch_id)

        return {"ok": True, "settled_batches": settled, "updated_rows": updated}

    def _mark_settled(self, batch_id: str):
        with self.engine.begin() as conn:
            if USE_SQLITE:
                conn.execute(
                    text(
                        "UPDATE prediction_snapshot_batches SET settled_at = :t WHERE batch_id = :b"
                    ),
                    {"t": datetime.now(timezone.utc).isoformat(), "b": batch_id},
                )
            else:
                conn.execute(
                    text(
                        "UPDATE prediction_snapshot_batches SET settled_at = NOW() WHERE batch_id = :b"
                    ),
                    {"b": batch_id},
                )

    def _fetch_results_for_races(self, race_ids: List[str]) -> pd.DataFrame:
        if not race_ids:
            return pd.DataFrame()
        # SQLAlchemy 綁定 IN
        placeholders = ", ".join([f":r{i}" for i in range(len(race_ids))])
        params = {f"r{i}": rid for i, rid in enumerate(race_ids)}
        q = text(
            f"""
            SELECT ru.race_id, ru.horse_name, ru.finish_order_num
            FROM runners ru
            WHERE ru.race_id IN ({placeholders})
              AND ru.finish_order_num IS NOT NULL
            """
        )
        return pd.read_sql(q, self.engine, params=params)

    # ---------- 列表／統計 ----------
    def list_batches(self) -> pd.DataFrame:
        return pd.read_sql(
            text(
                """
                SELECT b.batch_id, b.racing_date, b.course, b.created_at, b.settled_at, b.note,
                       COUNT(s.id) AS n_rows,
                       SUM(CASE WHEN s.finish_order_num IS NOT NULL THEN 1 ELSE 0 END) AS n_filled
                FROM prediction_snapshot_batches b
                LEFT JOIN prediction_snapshots s ON b.batch_id = s.batch_id
                GROUP BY b.batch_id, b.racing_date, b.course, b.created_at, b.settled_at, b.note
                ORDER BY b.racing_date DESC, b.created_at DESC
                """
            ),
            self.engine,
        )

    def evaluate_settled(
        self,
        batch_ids: Optional[List[str]] = None,
        only_settled: bool = True,
    ) -> Tuple[pd.DataFrame, dict]:
        """
        對已結算（或指定）快照：每場每訊號取最高分馬，統計獨贏／入圍。
        """
        batches = self.list_batches()
        if batches.empty:
            return pd.DataFrame(), {"error": "尚無快照。請於賽前建立預測快照。"}

        if batch_ids:
            use = batches[batches["batch_id"].isin(batch_ids)]
        elif only_settled:
            use = batches[batches["settled_at"].notna()]
        else:
            use = batches[batches["n_filled"] > 0]

        if use.empty:
            return pd.DataFrame(), {
                "error": "尚無已結算快照。請等 J18 賽果入庫後執行「結算快照」。",
                "n_batches": 0,
            }

        ids = use["batch_id"].tolist()
        ph = ", ".join([f":b{i}" for i in range(len(ids))])
        params = {f"b{i}": bid for i, bid in enumerate(ids)}
        snaps = pd.read_sql(
            text(f"SELECT * FROM prediction_snapshots WHERE batch_id IN ({ph})"),
            self.engine,
            params=params,
        )
        # 只要有名次的列參與
        snaps = snaps[snaps["finish_order_num"].notna()].copy()
        if snaps.empty:
            return pd.DataFrame(), {"error": "快照尚未回填名次"}

        n_runners = snaps.groupby("race_id")["horse_no"].transform("count")
        snaps["n_runners"] = n_runners
        race_ids = snaps["race_id"].unique()
        n_races = len(race_ids)
        avg_runners = float(snaps.groupby("race_id").size().mean())
        baseline = 1.0 / avg_runners if avg_runners else 0.0

        rows = []
        for label, col, _w in SIGNAL_DEFS:
            win_hits = place_hits = scored_races = 0
            for _, g in snaps.groupby("race_id"):
                if g["finish_order_num"].isna().all():
                    continue
                if col not in g.columns:
                    continue
                vals = pd.to_numeric(g[col], errors="coerce")
                # SG 可能全 0（賽前無 Speed Guide）— 仍計入但覆蓋另計
                if col == "sg_contrib" and vals.fillna(0).abs().lt(1e-12).all():
                    continue
                # AI 獨立軌道：該場無人有 AI 則跳過（不計入有效場次）
                if col == "ai_combo" and vals.isna().all():
                    continue
                scored_races += 1
                vals_filled = vals.fillna(-1e18)
                top = vals_filled.max()
                contenders = g.loc[vals_filled == top]
                finishes = contenders["finish_order_num"].astype(int)
                cut = place_cutoff(int(g["n_runners"].iloc[0]))
                if (finishes == 1).any():
                    win_hits += 1
                if (finishes <= cut).any():
                    place_hits += 1

            win_rate = win_hits / scored_races if scored_races else 0.0
            place_rate = place_hits / scored_races if scored_races else 0.0
            rows.append(
                {
                    "訊號": label,
                    "有效場次": scored_races,
                    "總場次": n_races,
                    "覆蓋率%": round(100.0 * scored_races / n_races, 1) if n_races else 0,
                    "獨贏命中": win_hits,
                    "獨贏率%": round(win_rate * 100, 2),
                    "入圍命中": place_hits,
                    "入圍率%": round(place_rate * 100, 2),
                    "隨機獨贏基準%": round(baseline * 100, 2),
                    "獨贏相對隨機": round(win_rate / baseline, 2) if baseline > 1e-9 else None,
                }
            )

        stats = pd.DataFrame(rows)
        if not stats.empty:
            stats = stats.sort_values("獨贏率%", ascending=False).reset_index(drop=True)

        meta = {
            "n_batches": len(ids),
            "batch_ids": ids,
            "n_races": n_races,
            "avg_runners": avg_runners,
            "note": "基於賽前快照 × 賽後 J18 名次（無洩漏）。",
        }
        return stats, meta
