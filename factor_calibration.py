"""
賽前預測快照 → 賽後 J18 賽果結算 → 各因子／總分／勝率／AI／融合命中統計。

流程：
  1. snapshot_meeting(racing_date, course)  — 賽前寫入 prediction_snapshots
     （含 ai_*／fused_share／ad_pick_rank；AI／融合不混入模型權重）
  2. settle_pending() — 用 runners 回填 finish_order_num＋settle_win_odds
  3. evaluate_settled() — 各訊號 WIN／PLA／WQ／T3／T4
  4. evaluate_ad_promo_hits() — 廣告融合推介四項宣傳命中（高賠／T3／T4）

命中規則（每場、每訊號）：
  - 推介列：該訊號分數 → 場內份額 → select_picks_by_share（與賽日推介一致）
  - WIN：推介頭兩位任一跑第 1
  - PLA：推介頭兩位任一跑入前 3
  - WQ：推介頭兩位恰為冠、亞（不論順序）
  - T3：全部推介馬（不論先後）覆蓋冠亞季
  - T4：全部推介馬覆蓋冠亞季殿
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

import pandas as pd
from sqlalchemy import text, create_engine

from config import ModelConfig
from factor_calculator import FactorCalculator
from inference_engine import InferenceEngine, scores_to_win_probs
from score_share import scores_to_share_probs, select_picks_by_share
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
    # 第三軌：模型×AI 融合推介（社交／廣告用；不寫入因子總分）
    ("融合推介", "fused_share", None),
]


# 位置命中（PLA）：推介頭兩位命中名次上限
PLA_FINISH_MAX = 3


def place_cutoff(n_runners: int) -> int:
    """歷史／展示用入圍前 4；場內少於 4 匹則取全場。命中統計 PLA 改用前 3。"""
    n = int(n_runners or 0)
    if n <= 0:
        return 4
    return min(4, n)


def evaluate_pool_hits(
    top2_finishes: Sequence[int],
    all_pick_finishes: Sequence[int],
) -> Dict[str, bool]:
    """
    依推介頭兩位／全部推介名次判斷五類命中。
    finishes 為實際名次（1=冠…）；缺名次者不應傳入。
    """
    top2 = [int(x) for x in top2_finishes if x is not None]
    all_f = [int(x) for x in all_pick_finishes if x is not None]
    top2_set = set(top2)
    all_set = set(all_f)
    return {
        "win": 1 in top2_set,
        "pla": any(f <= PLA_FINISH_MAX for f in top2),
        "wq": len(top2) >= 2 and top2_set == {1, 2},
        "t3": {1, 2, 3}.issubset(all_set),
        "t4": {1, 2, 3, 4}.issubset(all_set),
    }


def ranked_picks_for_signal(g: pd.DataFrame, col: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    依訊號欄位場內份額排序，回傳 (推介頭兩位, 全部推介列)。
    推介隻數與賽日速覽相同：select_picks_by_share。
    """
    if g.empty or col not in g.columns:
        empty = g.iloc[0:0].copy()
        return empty, empty
    work = g.copy()
    scores = pd.to_numeric(work[col], errors="coerce").to_numpy(dtype=float)
    shares = scores_to_share_probs(scores)
    work["_share"] = shares
    # 穩定排序：份額高優先；同分以馬號較小為先（可重現）
    work = work.sort_values(
        by=["_share", "horse_no"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    share_list = [float(x) for x in work["_share"].tolist()]
    if not share_list:
        empty = work.iloc[0:0]
        return empty, empty
    pick_n = int(select_picks_by_share(share_list))
    pick_n = max(0, min(pick_n, len(work)))
    if pick_n <= 0:
        # 保底：至少取頭兩位（或全場）供 WIN／PLA／WQ
        pick_n = min(2, len(work))
    all_picks = work.head(pick_n)
    top2 = all_picks.head(min(2, len(all_picks)))
    return top2, all_picks


DDL_PG = """
CREATE TABLE IF NOT EXISTS prediction_snapshot_batches (
    batch_id VARCHAR(64) PRIMARY KEY,
    racing_date DATE NOT NULL,
    course VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    settled_at TIMESTAMPTZ,
    note TEXT,
    provisional BOOLEAN DEFAULT FALSE,
    snapshot_kind VARCHAR(20) DEFAULT 'primary',
    revision_of VARCHAR(64)
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
    fused_share NUMERIC,
    ad_pick_rank INT,
    settle_win_odds NUMERIC,
    model_coverage NUMERIC,
    coverage_json TEXT,
    provisional BOOLEAN DEFAULT FALSE,
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
    note TEXT,
    provisional INTEGER DEFAULT 0,
    snapshot_kind TEXT DEFAULT 'primary',
    revision_of TEXT
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
    fused_share REAL,
    ad_pick_rank INTEGER,
    settle_win_odds REAL,
    model_coverage REAL,
    coverage_json TEXT,
    provisional INTEGER DEFAULT 0,
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
            self._ensure_coverage_snapshot_columns(conn)

    def _ensure_ai_snapshot_columns(self, conn):
        """既有庫補欄：AI 獨立軌道（不影響舊快照結算）。"""
        cols = ("ai_score", "confidence", "ai_combo", "fused_share", "ad_pick_rank", "settle_win_odds")
        for col in cols:
            try:
                if USE_SQLITE:
                    typ = "INTEGER" if col == "ad_pick_rank" else "REAL"
                    conn.execute(text(f"ALTER TABLE prediction_snapshots ADD COLUMN {col} {typ}"))
                else:
                    pg_t = "INT" if col == "ad_pick_rank" else "NUMERIC"
                    conn.execute(
                        text(
                            f"ALTER TABLE prediction_snapshots "
                            f"ADD COLUMN IF NOT EXISTS {col} {pg_t}"
                        )
                    )
            except Exception:
                pass

    def _ensure_coverage_snapshot_columns(self, conn):
        """既有庫補欄：coverage／provisional／revision。"""
        snap_cols = (
            ("model_coverage", "NUMERIC", "REAL"),
            ("coverage_json", "TEXT", "TEXT"),
            ("provisional", "BOOLEAN DEFAULT FALSE", "INTEGER DEFAULT 0"),
        )
        for col, pg_t, sq_t in snap_cols:
            try:
                if USE_SQLITE:
                    conn.execute(text(f"ALTER TABLE prediction_snapshots ADD COLUMN {col} {sq_t}"))
                else:
                    conn.execute(
                        text(
                            f"ALTER TABLE prediction_snapshots "
                            f"ADD COLUMN IF NOT EXISTS {col} {pg_t}"
                        )
                    )
            except Exception:
                pass
        batch_cols = (
            ("provisional", "BOOLEAN DEFAULT FALSE", "INTEGER DEFAULT 0"),
            ("snapshot_kind", "VARCHAR(20) DEFAULT 'primary'", "TEXT DEFAULT 'primary'"),
            ("revision_of", "VARCHAR(64)", "TEXT"),
        )
        for col, pg_t, sq_t in batch_cols:
            try:
                if USE_SQLITE:
                    conn.execute(
                        text(f"ALTER TABLE prediction_snapshot_batches ADD COLUMN {col} {sq_t}")
                    )
                else:
                    conn.execute(
                        text(
                            f"ALTER TABLE prediction_snapshot_batches "
                            f"ADD COLUMN IF NOT EXISTS {col} {pg_t}"
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
        *,
        revision_of: Optional[str] = None,
        snapshot_kind: str = "primary",
        force_provisional: Optional[bool] = None,
    ) -> dict:
        """
        對 upcoming 賽日全部場次跑 predict_race，寫入一批快照。
        racing_date: YYYY-MM-DD；省略則取 upcoming 最新一日。
        revision_of: 若指定，建立 revision 批次（不覆寫原 batch）。
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
        kind = "revision" if revision_of else (snapshot_kind or "primary")
        batch_id = f"{racing_date.replace('-', '')}{course}_{uuid4().hex[:8]}"
        if kind == "revision":
            batch_id = f"{racing_date.replace('-', '')}{course}_r{uuid4().hex[:6]}"

        from form_ai_analyst import FormAIAnalyst
        from form_ai_picks import attach_fused_shares_to_snapshot_rows, compute_ai_combo
        from ad_promo_hits import attach_ad_pick_ranks_to_snapshot_rows

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
        meta_reasons = []
        any_provisional = False
        ad_race_items = []
        for _, race in races.iterrows():
            rid = race["race_id"]
            pred, _info, meta = self.infer.predict_race(rid)
            if pred is None or pred.empty:
                continue
            if isinstance(meta, dict):
                if meta.get("provisional"):
                    any_provisional = True
                for r in meta.get("provisional_reasons") or []:
                    if r not in meta_reasons:
                        meta_reasons.append(r)
            ai_map = ai_by_race.get(str(rid), {})
            ad_race_items.append(
                {
                    "race_id": str(rid),
                    "race_info": _info if _info is not None else race,
                    "pred_df": pred.copy(),
                    "ai_map": ai_map,
                }
            )
            for _, p in pred.iterrows():
                hno = int(p["馬號"])
                sc, cf, combo = ai_map.get(hno, (None, None, None))
                cov = p.get("模型覆蓋")
                try:
                    cov_f = float(cov) if cov is not None and pd.notna(cov) else None
                except (TypeError, ValueError):
                    cov_f = None
                reasons = str(p.get("provisional_reasons") or "")
                row_prov = bool(reasons.strip()) or bool(
                    force_provisional if force_provisional is not None else False
                )
                if row_prov:
                    any_provisional = True
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
                        "fused_share": None,
                        "ad_pick_rank": None,
                        "settle_win_odds": None,
                        "model_coverage": cov_f,
                        "coverage_json": p.get("coverage_json"),
                        "provisional": row_prov,
                        "finish_order_num": None,
                    }
                )

        if not rows:
            return {"ok": False, "error": "預測結果為空（請先重算 factor_scores）"}

        attach_fused_shares_to_snapshot_rows(rows)
        attach_ad_pick_ranks_to_snapshot_rows(rows)

        allow_prov = bool(getattr(ModelConfig, "SNAPSHOT_ALLOW_PROVISIONAL", True))
        if force_provisional is not None:
            batch_provisional = bool(force_provisional)
        else:
            batch_provisional = bool(any_provisional) if allow_prov else False

        note_bits = [note or ("revision snapshot" if kind == "revision" else "pre-race snapshot")]
        if batch_provisional and meta_reasons:
            note_bits.append("provisional:" + ",".join(meta_reasons))
        note_final = " | ".join(note_bits)

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO prediction_snapshot_batches
                    (batch_id, racing_date, course, note, provisional, snapshot_kind, revision_of)
                    VALUES (:batch_id, :racing_date, :course, :note, :provisional, :snapshot_kind, :revision_of)
                    """
                ),
                {
                    "batch_id": batch_id,
                    "racing_date": racing_date,
                    "course": course,
                    "note": note_final,
                    "provisional": batch_provisional,
                    "snapshot_kind": kind,
                    "revision_of": revision_of,
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
                            ai_score, confidence, ai_combo, fused_share, ad_pick_rank,
                            model_coverage, coverage_json, provisional,
                            finish_order_num
                        ) VALUES (
                            :batch_id, :race_id, :horse_no, :horse_name, :jockey_name, :trainer_name, :draw,
                            :z_jockey, :z_trainer, :z_synergy, :z_draw, :z_horse, :z_pace, :z_speed,
                            :sg_contrib, :total_score, :model_win_prob, :pred_rank,
                            :ai_score, :confidence, :ai_combo, :fused_share, :ad_pick_rank,
                            :model_coverage, :coverage_json, :provisional,
                            :finish_order_num
                        )
                        """
                    ),
                    r,
                )

        n_ai = sum(1 for r in rows if r.get("ai_combo") is not None)
        out = {
            "ok": True,
            "batch_id": batch_id,
            "racing_date": racing_date,
            "course": course,
            "n_rows": len(rows),
            "n_races": int(races["race_id"].nunique()),
            "n_with_ai": n_ai,
            "provisional": batch_provisional,
            "snapshot_kind": kind,
            "revision_of": revision_of,
            "provisional_reasons": meta_reasons,
        }

        # 快照成功後自動產出廣告海報（模型＋AI 各一）
        if bool(getattr(ModelConfig, "AD_OUTPUT_ON_SNAPSHOT", True)) and ad_race_items:
            try:
                from ad_poster import default_output_dir, generate_ads_for_meeting_predictions

                ad_out = generate_ads_for_meeting_predictions(
                    batch_id=batch_id,
                    race_items=ad_race_items,
                    output_root=default_output_dir(),
                    racing_date=str(racing_date)[:10],
                    course=str(course),
                )
                out["ad_output"] = ad_out
            except Exception as e:
                out["ad_output"] = {"ok": False, "error": str(e)}

        return out

    def revise_snapshot(
        self,
        racing_date: str,
        course: str,
        *,
        base_batch_id: Optional[str] = None,
        note: str = "",
    ) -> dict:
        """
        資料到位後追加 revision 快照（不覆寫已結算／原 primary）。
        未指定 base_batch_id 時取該賽日最新 primary／任一最新 batch。
        """
        batches = self.list_batches()
        if batches.empty:
            return {"ok": False, "error": "尚無快照可修訂"}
        d = racing_date.replace("/", "-")[:10]
        c = str(course).upper()
        sub = batches[
            (batches["racing_date"].astype(str).str[:10] == d)
            & (batches["course"].astype(str).str.upper() == c)
        ]
        if sub.empty:
            return {"ok": False, "error": f"找不到 {d} {c} 的快照"}
        if base_batch_id:
            base = base_batch_id
        else:
            if "snapshot_kind" in sub.columns:
                prim = sub[sub["snapshot_kind"].fillna("primary").astype(str) == "primary"]
            else:
                prim = sub
            use = prim if not prim.empty else sub
            unsettled = use[use["settled_at"].isna()] if "settled_at" in use.columns else use
            pick = unsettled if not unsettled.empty else use
            base = str(pick.iloc[0]["batch_id"])
        return self.snapshot_meeting(
            racing_date=d,
            course=c,
            note=note or f"revision of {base}",
            revision_of=base,
            snapshot_kind="revision",
            force_provisional=False,
        )

    # ---------- 賽後結算 ----------
    def settle_pending(self) -> dict:
        """
        對未結算 batch：若 historical runners 已有該 race_id 名次，則回填 finish_order_num。
        匹配優先 race_id+horse_no（避免中英馬名不一致），再 fallback 正規化馬名。
        當 batch 內每場 ≥50% 馬有名次時，標記 settled_at。
        """
        batches = pd.read_sql(
            text(
                "SELECT batch_id, racing_date, course FROM prediction_snapshot_batches "
                "WHERE settled_at IS NULL ORDER BY racing_date"
            ),
            self.engine,
        )
        if batches.empty:
            return {
                "ok": True,
                "settled_batches": [],
                "updated_rows": 0,
                "message": "沒有未結算的快照 batch",
            }

        updated = 0
        settled = []
        waiting_results = []
        match_stats = []
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
                waiting_results.append(batch_id)
                continue

            from bucket_utils import normalize_person_name

            results = results.copy()
            results["horse_no"] = pd.to_numeric(results["horse_no"], errors="coerce")
            results["horse_key"] = results["horse_name"].apply(normalize_person_name)
            # 英文名大小寫不敏感
            results["horse_key_l"] = results["horse_key"].str.lower()

            snaps = snaps.copy()
            snaps["horse_no"] = pd.to_numeric(snaps["horse_no"], errors="coerce")
            snaps["horse_key"] = snaps["horse_name"].apply(normalize_person_name)
            snaps["horse_key_l"] = snaps["horse_key"].str.lower()

            finish_by_id: dict = {}
            odds_by_id: dict = {}
            matched_by_no = matched_by_name = 0

            result_cols = ["race_id", "horse_no", "finish_order_num", "settle_win_odds"]
            if "settle_win_odds" not in results.columns:
                results["settle_win_odds"] = None

            # 1) race_id + horse_no（主路徑：中英馬名不一致時仍可配）
            by_no = snaps.merge(
                results[result_cols].dropna(subset=["horse_no"]),
                on=["race_id", "horse_no"],
                how="left",
                suffixes=("", "_r"),
            )
            for _, row in by_no.iterrows():
                if pd.isna(row.get("finish_order_num")):
                    continue
                sid = int(row["id"])
                finish_by_id[sid] = int(row["finish_order_num"])
                if pd.notna(row.get("settle_win_odds")):
                    odds_by_id[sid] = float(row["settle_win_odds"])
                matched_by_no += 1

            # 2) fallback：race_id + 正規化馬名（大小寫不敏感）
            still = snaps[~snaps["id"].astype(int).isin(finish_by_id)].copy()
            if not still.empty:
                by_name = still.merge(
                    results[
                        ["race_id", "horse_key_l", "finish_order_num", "settle_win_odds"]
                    ].dropna(subset=["horse_key_l"]),
                    on=["race_id", "horse_key_l"],
                    how="left",
                    suffixes=("", "_r"),
                )
                for _, row in by_name.iterrows():
                    if pd.isna(row.get("finish_order_num")):
                        continue
                    rid = int(row["id"])
                    if rid in finish_by_id:
                        continue
                    finish_by_id[rid] = int(row["finish_order_num"])
                    if pd.notna(row.get("settle_win_odds")):
                        odds_by_id[rid] = float(row["settle_win_odds"])
                    matched_by_name += 1

            with self.engine.begin() as conn:
                for sid, fin in finish_by_id.items():
                    odds = odds_by_id.get(sid)
                    if odds is None:
                        conn.execute(
                            text(
                                "UPDATE prediction_snapshots SET finish_order_num = :f "
                                "WHERE id = :id"
                            ),
                            {"f": int(fin), "id": int(sid)},
                        )
                    else:
                        conn.execute(
                            text(
                                "UPDATE prediction_snapshots "
                                "SET finish_order_num = :f, settle_win_odds = :o "
                                "WHERE id = :id"
                            ),
                            {"f": int(fin), "o": float(odds), "id": int(sid)},
                        )
                    updated += 1

            unmatched = int(len(snaps) - len(finish_by_id))
            match_stats.append(
                {
                    "batch_id": batch_id,
                    "snap_rows": int(len(snaps)),
                    "matched_by_no": int(matched_by_no),
                    "matched_by_name": int(matched_by_name),
                    "unmatched": unmatched,
                }
            )

            # 檢查是否整批可結算
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
                if (left["filled"] / left["n"] >= 0.5).all():
                    self._mark_settled(batch_id)
                    settled.append(batch_id)

        msg = f"更新 {updated} 列；新結算 {len(settled)} batch"
        if waiting_results:
            msg += f"；尚待賽果 {len(waiting_results)} batch（先同步 jjjc／J18 名次）"
        if match_stats and updated == 0 and not settled:
            sample = match_stats[0]
            msg += (
                f"；配對失敗（例 `{sample['batch_id']}`："
                f"no={sample['matched_by_no']} name={sample['matched_by_name']} "
                f"未配={sample['unmatched']}）。"
                "若賽果為英文名、快照為中文名，請更新後重試（已改優先馬號配對）。"
            )

        return {
            "ok": True,
            "settled_batches": settled,
            "updated_rows": updated,
            "waiting_results": waiting_results,
            "match_stats": match_stats,
            "message": msg,
        }

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
        from ad_promo_hits import parse_runner_win_odds

        placeholders = ", ".join([f":r{i}" for i in range(len(race_ids))])
        params = {f"r{i}": rid for i, rid in enumerate(race_ids)}
        try:
            q = text(
                f"""
                SELECT ru.race_id, ru.horse_no, ru.horse_name, ru.finish_order_num,
                       ru.win_probability_raw, ru.raw_json
                FROM runners ru
                WHERE ru.race_id IN ({placeholders})
                  AND ru.finish_order_num IS NOT NULL
                """
            )
            df = pd.read_sql(q, self.engine, params=params)
        except Exception:
            q = text(
                f"""
                SELECT ru.race_id, ru.horse_no, ru.horse_name, ru.finish_order_num
                FROM runners ru
                WHERE ru.race_id IN ({placeholders})
                  AND ru.finish_order_num IS NOT NULL
                """
            )
            df = pd.read_sql(q, self.engine, params=params)
            if not df.empty:
                df = df.copy()
                df["settle_win_odds"] = None
            return df
        if df.empty:
            return df
        df = df.copy()
        df["settle_win_odds"] = [
            parse_runner_win_odds(w, raw)
            for w, raw in zip(
                df.get("win_probability_raw", [None] * len(df)),
                df.get("raw_json", [None] * len(df)),
            )
        ]
        return df

    def evaluate_ad_promo_hits(
        self,
        batch_ids: Optional[List[str]] = None,
        only_settled: bool = True,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
        """
        廣告融合推介賽後宣傳命中。

        Returns
        -------
        race_df : 每場四項命中標記＋推介摘要
        summary : 各原則命中場次數／比率
        meta
        """
        from ad_promo_hits import (
            AD_QIN_ODDS_GT,
            AD_WIN_ODDS_MIN,
            ad_pick_max,
            attach_ad_pick_ranks_to_snapshot_rows,
            evaluate_ad_race_hits,
        )

        batches = self.list_batches()
        if batches.empty:
            return pd.DataFrame(), pd.DataFrame(), {"error": "尚無快照。"}

        if batch_ids:
            use = batches[batches["batch_id"].isin(batch_ids)]
        elif only_settled:
            use = batches[batches["settled_at"].notna()]
        else:
            use = batches[batches["n_filled"] > 0]

        if use.empty:
            return pd.DataFrame(), pd.DataFrame(), {
                "error": "尚無已結算快照。",
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
        snaps = snaps[snaps["finish_order_num"].notna()].copy()
        if snaps.empty:
            return pd.DataFrame(), pd.DataFrame(), {"error": "快照尚未回填名次"}

        # 舊快照無 ad_pick_rank：用 fused_share 即時重建（不寫回）
        if "ad_pick_rank" not in snaps.columns or snaps["ad_pick_rank"].isna().all():
            rows = snaps.to_dict(orient="records")
            if "fused_share" not in snaps.columns or snaps["fused_share"].isna().all():
                from form_ai_picks import attach_fused_shares_to_snapshot_rows

                attach_fused_shares_to_snapshot_rows(rows)
            attach_ad_pick_ranks_to_snapshot_rows(rows)
            snaps = pd.DataFrame(rows)

        # 補賠率（已有名次但缺 settle_win_odds）
        if "settle_win_odds" not in snaps.columns:
            snaps["settle_win_odds"] = None
        need_odds = snaps["settle_win_odds"].isna()
        if need_odds.any():
            race_ids = snaps.loc[need_odds, "race_id"].astype(str).unique().tolist()
            results = self._fetch_results_for_races(race_ids)
            if not results.empty:
                odds_map = {
                    (str(r.race_id), int(r.horse_no)): r.settle_win_odds
                    for r in results.itertuples()
                    if pd.notna(r.horse_no) and r.settle_win_odds is not None
                }
                for idx in snaps.index[need_odds]:
                    key = (str(snaps.at[idx, "race_id"]), int(snaps.at[idx, "horse_no"]))
                    if key in odds_map:
                        snaps.at[idx, "settle_win_odds"] = odds_map[key]

        batch_dates = {
            str(r.batch_id): str(r.racing_date)[:10]
            for r in use.itertuples()
        }
        batch_courses = {
            str(r.batch_id): str(r.course or "")
            for r in use.itertuples()
        }

        race_rows = []
        counts = {
            "win_odds7": 0,
            "qin_odds10": 0,
            "t3_cover": 0,
            "t4_cover": 0,
            "any_promo": 0,
        }
        scored = 0
        for (bid, rid), g in snaps.groupby(["batch_id", "race_id"]):
            picks = g[g["ad_pick_rank"].notna()].copy()
            if picks.empty:
                continue
            picks = picks.sort_values("ad_pick_rank", kind="mergesort")
            finishes = picks["finish_order_num"].astype(int).tolist()
            odds = [
                None if pd.isna(x) else float(x)
                for x in picks.get("settle_win_odds", pd.Series([None] * len(picks))).tolist()
            ]
            top2 = (picks["ad_pick_rank"].astype(int) <= 2).tolist()
            hits = evaluate_ad_race_hits(
                pick_finishes=finishes,
                pick_odds=odds,
                top2_mask=top2,
            )
            scored += 1
            for k in counts:
                if hits.get(k):
                    counts[k] += 1
            pick_labels = [
                f"{int(r.ad_pick_rank)}:{int(r.horse_no)} {r.horse_name or ''}".strip()
                for r in picks.itertuples()
            ]
            race_rows.append(
                {
                    "賽日": batch_dates.get(str(bid), ""),
                    "場地": batch_courses.get(str(bid), ""),
                    "batch_id": bid,
                    "race_id": rid,
                    "推介數": int(len(picks)),
                    "推介": " / ".join(pick_labels),
                    "WIN≥7": hits["win_odds7"],
                    "冠亞+賠>10": hits["qin_odds10"],
                    "T3覆蓋": hits["t3_cover"],
                    "T4覆蓋": hits["t4_cover"],
                    "可宣傳": hits["any_promo"],
                }
            )

        race_df = pd.DataFrame(race_rows)
        if not race_df.empty:
            race_df = race_df.sort_values(
                by=["可宣傳", "賽日", "race_id"],
                ascending=[False, False, True],
            ).reset_index(drop=True)

        summary = pd.DataFrame(
            [
                {
                    "原則": "1. 頭兩位獨贏且賠率≥7",
                    "代碼": "WIN_ODDS7",
                    "命中場次": counts["win_odds7"],
                    "有效場次": scored,
                    "命中率%": round(100.0 * counts["win_odds7"] / scored, 2) if scored else 0.0,
                    "門檻": f"獨贏賠率≥{AD_WIN_ODDS_MIN:g}",
                },
                {
                    "原則": "2. 覆蓋冠亞且其中一匹賠率>10",
                    "代碼": "QIN_ODDS10",
                    "命中場次": counts["qin_odds10"],
                    "有效場次": scored,
                    "命中率%": round(100.0 * counts["qin_odds10"] / scored, 2) if scored else 0.0,
                    "門檻": f"獨贏賠率>{AD_QIN_ODDS_GT:g}",
                },
                {
                    "原則": "3. 覆蓋冠亞季（不計賠率）",
                    "代碼": "T3_COVER",
                    "命中場次": counts["t3_cover"],
                    "有效場次": scored,
                    "命中率%": round(100.0 * counts["t3_cover"] / scored, 2) if scored else 0.0,
                    "門檻": "—",
                },
                {
                    "原則": "4. 覆蓋 Top4 全部（不計賠率）",
                    "代碼": "T4_COVER",
                    "命中場次": counts["t4_cover"],
                    "有效場次": scored,
                    "命中率%": round(100.0 * counts["t4_cover"] / scored, 2) if scored else 0.0,
                    "門檻": "—",
                },
            ]
        )
        meta = {
            "n_batches": len(ids),
            "batch_ids": ids,
            "n_races_scored": scored,
            "n_promo_races": counts["any_promo"],
            "ad_pick_max": ad_pick_max(),
            "note": (
                "基於賽前鎖定的廣告融合推介（最多 "
                f"{ad_pick_max()} 匹）× 賽後名次／獨贏賠率。"
            ),
        }
        return race_df, summary, meta

    # ---------- 列表／統計 ----------
    def list_batches(self) -> pd.DataFrame:
        try:
            return pd.read_sql(
                text(
                    """
                    SELECT b.batch_id, b.racing_date, b.course, b.created_at, b.settled_at, b.note,
                           b.provisional, b.snapshot_kind, b.revision_of,
                           COUNT(s.id) AS n_rows,
                           SUM(CASE WHEN s.finish_order_num IS NOT NULL THEN 1 ELSE 0 END) AS n_filled
                    FROM prediction_snapshot_batches b
                    LEFT JOIN prediction_snapshots s ON b.batch_id = s.batch_id
                    GROUP BY b.batch_id, b.racing_date, b.course, b.created_at, b.settled_at, b.note,
                             b.provisional, b.snapshot_kind, b.revision_of
                    ORDER BY b.racing_date DESC, b.created_at DESC
                    """
                ),
                self.engine,
            )
        except Exception:
            # 舊庫尚無 provisional 欄
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
        對已結算（或指定）快照：每場每訊號依場內份額選推介，
        統計 WIN／PLA／WQ／T3／T4 命中率。
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

        n_runners = snaps.groupby(["batch_id", "race_id"])["horse_no"].transform("count")
        snaps["n_runners"] = n_runners
        race_keys = snaps.groupby(["batch_id", "race_id"]).ngroups
        n_races = int(race_keys)
        avg_runners = float(
            snaps.groupby(["batch_id", "race_id"]).size().mean()
        )
        # 隨機基準：頭兩位獨贏 ≈ 2/n；連贏（冠亞恰為該兩匹）≈ 2/(n(n-1))
        baseline_win = min(1.0, 2.0 / avg_runners) if avg_runners else 0.0
        baseline_wq = (
            2.0 / (avg_runners * (avg_runners - 1.0))
            if avg_runners and avg_runners > 1
            else 0.0
        )

        rows = []
        for label, col, _w in SIGNAL_DEFS:
            win_hits = pla_hits = wq_hits = t3_hits = t4_hits = 0
            scored_races = 0
            sum_pick_n = 0
            for _, g in snaps.groupby(["batch_id", "race_id"]):
                if g["finish_order_num"].isna().all():
                    continue
                if col not in g.columns:
                    continue
                vals = pd.to_numeric(g[col], errors="coerce")
                # SG 可能全 0（賽前無 Speed Guide）— 跳過不計有效場次
                if col == "sg_contrib" and vals.fillna(0).abs().lt(1e-12).all():
                    continue
                # AI 獨立軌道：該場無人有 AI 則跳過
                if col == "ai_combo" and vals.isna().all():
                    continue
                # 融合軌：該場全無 fused_share 則跳過（舊快照）
                if col == "fused_share" and vals.isna().all():
                    continue
                top2, all_picks = ranked_picks_for_signal(g, col)
                if top2.empty:
                    continue
                scored_races += 1
                sum_pick_n += int(len(all_picks))
                hits = evaluate_pool_hits(
                    top2["finish_order_num"].astype(int).tolist(),
                    all_picks["finish_order_num"].astype(int).tolist(),
                )
                if hits["win"]:
                    win_hits += 1
                if hits["pla"]:
                    pla_hits += 1
                if hits["wq"]:
                    wq_hits += 1
                if hits["t3"]:
                    t3_hits += 1
                if hits["t4"]:
                    t4_hits += 1

            def _rate(h: int) -> float:
                return h / scored_races if scored_races else 0.0

            win_rate = _rate(win_hits)
            rows.append(
                {
                    "訊號": label,
                    "有效場次": scored_races,
                    "總場次": n_races,
                    "覆蓋率%": round(100.0 * scored_races / n_races, 1) if n_races else 0,
                    "平均推介數": round(sum_pick_n / scored_races, 2) if scored_races else 0.0,
                    "WIN命中": win_hits,
                    "WIN%": round(win_rate * 100, 2),
                    "PLA命中": pla_hits,
                    "PLA%": round(_rate(pla_hits) * 100, 2),
                    "WQ命中": wq_hits,
                    "WQ%": round(_rate(wq_hits) * 100, 2),
                    "T3命中": t3_hits,
                    "T3%": round(_rate(t3_hits) * 100, 2),
                    "T4命中": t4_hits,
                    "T4%": round(_rate(t4_hits) * 100, 2),
                    "隨機WIN基準%": round(baseline_win * 100, 2),
                    "WIN相對隨機": (
                        round(win_rate / baseline_win, 2) if baseline_win > 1e-9 else None
                    ),
                    "隨機WQ基準%": round(baseline_wq * 100, 2),
                }
            )

        stats = pd.DataFrame(rows)
        if not stats.empty:
            stats = stats.sort_values("WIN%", ascending=False).reset_index(drop=True)

        # coverage 分桶（綜合總分）
        cov_buckets = []
        if "model_coverage" in snaps.columns and snaps["model_coverage"].notna().any():
            def _bucket(c):
                try:
                    v = float(c)
                except (TypeError, ValueError):
                    return "未知"
                if v < 0.35:
                    return "低(<0.35)"
                if v < 0.70:
                    return "中(0.35–0.70)"
                return "高(≥0.70)"

            tmp = snaps.copy()
            race_cov = (
                tmp.groupby(["batch_id", "race_id"])["model_coverage"]
                .mean()
                .reset_index()
                .rename(columns={"model_coverage": "avg_cov"})
            )
            race_cov["bucket"] = race_cov["avg_cov"].map(_bucket)
            for bname, sub_keys in race_cov.groupby("bucket"):
                key_set = set(
                    zip(sub_keys["batch_id"].tolist(), sub_keys["race_id"].tolist())
                )
                win_hits = pla_hits = wq_hits = t3_hits = t4_hits = scored = 0
                for (bid, rid), g in snaps.groupby(["batch_id", "race_id"]):
                    if (bid, rid) not in key_set:
                        continue
                    if "total_score" not in g.columns:
                        continue
                    top2, all_picks = ranked_picks_for_signal(g, "total_score")
                    if top2.empty:
                        continue
                    scored += 1
                    hits = evaluate_pool_hits(
                        top2["finish_order_num"].astype(int).tolist(),
                        all_picks["finish_order_num"].astype(int).tolist(),
                    )
                    win_hits += int(hits["win"])
                    pla_hits += int(hits["pla"])
                    wq_hits += int(hits["wq"])
                    t3_hits += int(hits["t3"])
                    t4_hits += int(hits["t4"])
                cov_buckets.append(
                    {
                        "覆蓋桶": bname,
                        "有效場次": scored,
                        "WIN%": round(100.0 * win_hits / scored, 2) if scored else 0.0,
                        "PLA%": round(100.0 * pla_hits / scored, 2) if scored else 0.0,
                        "WQ%": round(100.0 * wq_hits / scored, 2) if scored else 0.0,
                        "T3%": round(100.0 * t3_hits / scored, 2) if scored else 0.0,
                        "T4%": round(100.0 * t4_hits / scored, 2) if scored else 0.0,
                    }
                )

        meta = {
            "n_batches": len(ids),
            "batch_ids": ids,
            "n_races": n_races,
            "avg_runners": avg_runners,
            "note": (
                "基於賽前快照 × 賽後名次。"
                "WIN/PLA/WQ＝推介頭兩位；T3/T4＝全部推介馬覆蓋名次席位。"
            ),
            "rules": {
                "win": "推介頭兩位任一第 1",
                "pla": f"推介頭兩位任一前 {PLA_FINISH_MAX}",
                "wq": "推介頭兩位恰為冠、亞",
                "t3": "全部推介覆蓋 1–3",
                "t4": "全部推介覆蓋 1–4",
            },
            "coverage_buckets": cov_buckets,
        }
        return stats, meta

    def evaluate_raceday_rankings(
        self,
        *,
        only_settled: bool = True,
        metric: str = "WIN%",
        top_n: int = 5,
        batch_ids: Optional[List[str]] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
        """
        總表 + 各賽日 Top-N 訊號排名（供用戶／管理端瀏覽頁）。

        Returns
        -------
        overall : evaluate_settled 彙總表
        day_top : 每賽日（日期×場地）依 metric 取前 top_n
        meta : 含 overall meta 與 day 數
        """
        overall, meta = self.evaluate_settled(
            batch_ids=batch_ids, only_settled=only_settled
        )
        if meta.get("error"):
            return pd.DataFrame(), pd.DataFrame(), meta

        batches = self.list_batches()
        if batches.empty:
            return overall, pd.DataFrame(), meta

        if batch_ids:
            use = batches[batches["batch_id"].isin(batch_ids)].copy()
        elif only_settled:
            use = batches[batches["settled_at"].notna()].copy()
        else:
            use = batches[batches["n_filled"] > 0].copy()

        if use.empty:
            return overall, pd.DataFrame(), {**meta, "n_days": 0}

        use["_d"] = use["racing_date"].astype(str).str[:10]
        metric_col = metric if metric in (
            "WIN%", "PLA%", "WQ%", "T3%", "T4%", "WIN相對隨機"
        ) else "WIN%"
        top_n = max(1, int(top_n))

        day_rows: List[dict] = []
        for (d, course), g in use.groupby(["_d", "course"], sort=True):
            ids = g["batch_id"].tolist()
            stats, day_meta = self.evaluate_settled(batch_ids=ids, only_settled=False)
            if stats.empty or metric_col not in stats.columns:
                continue
            ranked = stats.sort_values(
                by=[metric_col, "有效場次"],
                ascending=[False, False],
                kind="mergesort",
            ).head(top_n)
            for i, (_, r) in enumerate(ranked.iterrows(), start=1):
                day_rows.append(
                    {
                        "賽日": d,
                        "場地": course,
                        "排名": i,
                        "訊號": r.get("訊號"),
                        "WIN%": r.get("WIN%"),
                        "PLA%": r.get("PLA%"),
                        "WQ%": r.get("WQ%"),
                        "T3%": r.get("T3%"),
                        "T4%": r.get("T4%"),
                        "有效場次": r.get("有效場次"),
                        "覆蓋率%": r.get("覆蓋率%"),
                        "WIN相對隨機": r.get("WIN相對隨機"),
                        "排序指標": metric_col,
                        "場次數": day_meta.get("n_races"),
                    }
                )

        day_top = pd.DataFrame(day_rows)
        if not day_top.empty:
            day_top = day_top.sort_values(
                by=["賽日", "場地", "排名"], ascending=[False, True, True]
            ).reset_index(drop=True)

        out_meta = {
            **meta,
            "n_days": int(use.groupby(["_d", "course"]).ngroups),
            "rank_metric": metric_col,
            "top_n": top_n,
        }
        return overall, day_top, out_meta
