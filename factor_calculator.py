import pandas as pd
import numpy as np
from datetime import datetime
from sqlalchemy import create_engine, text
import os
import json
import re
from typing import Optional
from config import ModelConfig
from bucket_utils import (
    make_bucket_id,
    make_band_bucket_id,
    normalize_person_name,
    synergy_name,
    horse_jockey_name,
    is_valid_bucket,
    is_valid_band_bucket,
    GLOBAL_BUCKET,
    distance_proximity_weight,
    distance_band,
    parse_bucket_parts,
)

# 為了讓 Pandas 方便讀寫，我們使用 SQLAlchemy
from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH
if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv("DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db")

class FactorCalculator:
    def __init__(self, target_date=None):
        """
        初始化因子計算器
        :param target_date: 計算因子的基準日，預設為今天。時間衰減將以此日為基準。
        """
        self.engine = create_engine(DATABASE_URL_SYNC)
        self.target_date = pd.to_datetime(target_date) if target_date else pd.to_datetime('today')

    def fetch_historical_data(self) -> pd.DataFrame:
        """從資料庫提取歷史出賽數據與賽事資訊"""
        # 直接把日期轉成字串，避免 SQLite/PostgreSQL 參數綁定的方言差異
        target_date_str = self.target_date.strftime("%Y-%m-%d")
        
        query = text(f"""
            SELECT 
                m.racing_date,
                r.race_id, r.course, r.track, r.distance_m, r.ground, r.class as race_class,
                ru.runner_id, ru.jockey_name, ru.trainer_name, ru.horse_name,
                ru.finish_order_num, ru.bar_draw as draw,
                ru.runner_rating, ru.win_probability_raw,
                ru.final_time, ru.raw_json
            FROM runners ru
            JOIN races r ON ru.race_id = r.race_id
            JOIN race_meetings m ON r.meeting_id = m.meeting_id
            WHERE ru.finish_order_num IS NOT NULL 
              AND r.distance_m IS NOT NULL
              AND m.racing_date < '{target_date_str}'
        """)
        
        # 使用 Pandas 讀取 SQL (不再需要傳 params)
        df = pd.read_sql(query, self.engine)
        if df.empty:
            return df

        df['racing_date'] = pd.to_datetime(df['racing_date'])
        df['jockey_name'] = df['jockey_name'].apply(normalize_person_name)
        df['trainer_name'] = df['trainer_name'].apply(normalize_person_name)
        df['horse_name'] = df['horse_name'].apply(normalize_person_name)
        df['class_num'] = df['race_class'].apply(self._parse_class_num)
        df['win_odds'] = df.apply(
            lambda r: self._parse_win_odds(r.get('raw_json'), r.get('win_probability_raw')),
            axis=1,
        )
        df['late_pos'] = df['raw_json'].apply(self._parse_late_sectional_position)

        # 細桶：Venue_Track_Distance（檔位等）
        df['bucket_id'] = df.apply(
            lambda row: make_bucket_id(
                race_id=row['race_id'],
                course=row['course'],
                track=row['track'],
                distance_m=row['distance_m'],
            ),
            axis=1,
        )
        # 粗桶：Venue_距離帶（騎師/練馬師/騎練）
        df['band_bucket_id'] = df.apply(
            lambda row: make_band_bucket_id(
                race_id=row['race_id'],
                course=row['course'],
                distance_m=row['distance_m'],
            ),
            axis=1,
        )
        df = df[df['bucket_id'].apply(is_valid_bucket) | df['band_bucket_id'].apply(is_valid_band_bucket)].copy()
        
        return df

    @staticmethod
    def _parse_class_num(race_class) -> Optional[int]:
        """第五班→5；Class 4→4；無法解析→None。"""
        if race_class is None or (isinstance(race_class, float) and np.isnan(race_class)):
            return None
        s = str(race_class)
        m = re.search(r"第([一二三四五六七八九十])班", s)
        if m:
            cmap = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            return cmap.get(m.group(1))
        m = re.search(r"(?:Class|班)\s*([1-5])", s, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"([1-5])\s*班", s)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _parse_win_odds(raw_json, win_probability_raw) -> Optional[float]:
        """轉成約當獨贏賠率；win_probability 若為百分比則 odds≈100/p。"""
        val = None
        if win_probability_raw is not None and str(win_probability_raw).strip() not in ("", "-", "None"):
            try:
                val = float(str(win_probability_raw).replace("%", "").strip())
            except ValueError:
                val = None
        if val is None and raw_json is not None:
            try:
                data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                wp = data.get("win_probability")
                if wp is not None and str(wp).strip() not in ("", "-", "None"):
                    val = float(str(wp).replace("%", "").strip())
            except (TypeError, ValueError, json.JSONDecodeError):
                val = None
        if val is None or val <= 0:
            return None
        # 百分比機率 → 賠率；若已是賠率（常見 >1 且小數）則直接用
        if val > 1:
            # 多數 J18 為百分比字串如 45
            return 100.0 / val
        return 1.0 / val

    @staticmethod
    def _parse_late_sectional_position(raw_json) -> Optional[int]:
        """取最後一個非空 stage 的 position（近似末段走位）。"""
        if raw_json is None:
            return None
        try:
            data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            sections = data.get("sections") or {}
            last_pos = None
            for key in ("stage_1", "stage_2", "stage_3", "stage_4", "stage_5", "stage_6"):
                stage = sections.get(key)
                if not stage:
                    continue
                pos = stage.get("position")
                if pos is None or str(pos).strip() in ("", "-", "N"):
                    continue
                try:
                    last_pos = int(float(pos))
                except (TypeError, ValueError):
                    continue
            return last_pos
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def calculate_base_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """計算單場賽事的原始得分 (Base Score)"""
        # 第一名得 WIN_WEIGHT，第二三四名得 PLACE_WEIGHT，其餘 0 分
        conditions = [
            (df['finish_order_num'] == 1),
            (df['finish_order_num'].isin([2, 3, 4]))
        ]
        choices = [ModelConfig.WIN_WEIGHT, ModelConfig.PLACE_WEIGHT]
        df['raw_score'] = np.select(conditions, choices, default=0.0)
        return df

    def apply_time_decay(self, df: pd.DataFrame, decay_rates: list) -> pd.DataFrame:
        """計算每場賽事的時間衰減權重"""
        days_diff = (self.target_date - df['racing_date']).dt.days
        
        # 根據 TIME_WINDOW_DAYS (預設 90 天) 計算該賽事屬於第幾個時間桶
        bucket_idx = (days_diff // ModelConfig.TIME_WINDOW_DAYS).astype(int)
        
        # 將超出衰減陣列長度的賽事權重設為最後一個值 (通常是 0)
        max_idx = len(decay_rates) - 1
        bucket_idx = bucket_idx.clip(upper=max_idx)
        
        # 映射衰減權重
        decay_map = dict(enumerate(decay_rates))
        df['time_weight'] = bucket_idx.map(decay_map)
        
        # 算出加權後的得分與出賽數 (1場出賽 * 時間權重)
        df['weighted_score'] = df['raw_score'] * df['time_weight']
        df['weighted_runs'] = 1.0 * df['time_weight']
        
        return df

    def apply_bayesian_smoothing(self, grouped_df: pd.DataFrame, prior_c: float) -> pd.DataFrame:
        """
        貝葉斯平滑處理
        Adjusted_Score = (真實加權總分 + C * 總體平均得分) / (真實加權出賽數 + C)
        """
        # 計算總體平均得分 (所有人在這個 Bucket 的平均水準)
        global_avg = grouped_df['weighted_score'].sum() / (grouped_df['weighted_runs'].sum() + 1e-9)
        
        # 套用公式
        grouped_df['adjusted_score'] = (
            (grouped_df['weighted_score'] + prior_c * global_avg) / 
            (grouped_df['weighted_runs'] + prior_c)
        )
        return grouped_df

    def calculate_entity_factor(
        self,
        df: pd.DataFrame,
        entity_col: str,
        decay_rates: list,
        smooth_c: float,
        global_bucket: bool = False,
        use_distance_band: bool = False,
    ) -> pd.DataFrame:
        """計算特定實體因子。
        - global_bucket：人馬合作 GLOBAL
        - use_distance_band：騎/練/騎練用 Venue_距離帶粗桶
        - 否則用細桶 Venue_Track_Distance
        """
        temp_df = df.copy()
        if global_bucket:
            temp_df['bucket_id'] = GLOBAL_BUCKET
        elif use_distance_band:
            if 'band_bucket_id' not in temp_df.columns:
                temp_df['band_bucket_id'] = temp_df.apply(
                    lambda row: make_band_bucket_id(
                        race_id=row.get('race_id'),
                        course=row.get('course'),
                        distance_m=row.get('distance_m'),
                    ),
                    axis=1,
                )
            temp_df['bucket_id'] = temp_df['band_bucket_id']
        temp_df = self.apply_time_decay(temp_df, decay_rates)

        grouped = temp_df.groupby(['bucket_id', entity_col]).agg({
            'weighted_score': 'sum',
            'weighted_runs': 'sum',
            'raw_score': 'count',
            'finish_order_num': [
                ('wins', lambda x: (x == 1).sum()),
                ('places', lambda x: x.isin([2, 3, 4]).sum())
            ]
        })

        grouped.columns = ['weighted_score', 'weighted_runs', 'actual_runs', 'wins', 'places']
        grouped = grouped.reset_index()
        grouped = grouped[grouped['weighted_runs'] > 0]

        result = []
        for bucket, group in grouped.groupby('bucket_id'):
            smoothed = self.apply_bayesian_smoothing(group.copy(), smooth_c)
            result.append(smoothed)

        if not result:
            return pd.DataFrame()

        final_df = pd.concat(result, ignore_index=True)
        final_df['z_score'] = final_df.groupby('bucket_id')['adjusted_score'].transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-9)
        )
        return final_df

    def calculate_horse_jockey_factor(self, df: pd.DataFrame) -> pd.DataFrame:
        """人馬合作：全域 bucket=GLOBAL，不分賽道距離。"""
        temp = df.copy()
        temp['horse_jockey_name'] = temp.apply(
            lambda r: horse_jockey_name(r['horse_name'], r['jockey_name']), axis=1
        )
        out = self.calculate_entity_factor(
            temp,
            'horse_jockey_name',
            ModelConfig.HORSE_JOCKEY_DECAY,
            ModelConfig.HORSE_JOCKEY_SMOOTH_C,
            global_bucket=True,
        )
        if out.empty:
            return out
        out['factor_type'] = 'HORSE_JOCKEY'
        return out.rename(columns={'horse_jockey_name': 'entity_name'})

    def ensure_nlp_result_column(self) -> None:
        """為 text_reports 補上 nlp_result（Postgres / SQLite 皆可）。"""
        with self.engine.begin() as conn:
            if USE_SQLITE:
                cols = pd.read_sql("PRAGMA table_info(text_reports)", conn)
                names = cols['name'].tolist() if not cols.empty else []
                if 'nlp_result' not in names:
                    conn.execute(text("ALTER TABLE text_reports ADD COLUMN nlp_result TEXT"))
            else:
                conn.execute(text(
                    "ALTER TABLE text_reports ADD COLUMN IF NOT EXISTS nlp_result TEXT"
                ))

    @staticmethod
    def is_trivial_report(report_text) -> bool:
        """空白或「無特別報告」等無補償價值文字，不呼叫 LLM。"""
        if report_text is None or (isinstance(report_text, float) and np.isnan(report_text)):
            return True
        t = str(report_text).strip()
        if not t or len(t) < 4:
            return True
        # 去掉標點後比對
        compact = re.sub(r"[\s。．.！!？?，,、；;：:\"'「」『』（）()【】\[\]]+", "", t)
        trivial_set = {
            "無特別報告",
            "沒有特別報告",
            "無報告",
            "沒有報告",
            "Nil",
            "NIL",
            "N/A",
            "NA",
            "无特别报告",
        }
        if compact in trivial_set:
            return True
        if re.fullmatch(r"無特別報告.*", t):
            return True
        return False

    @staticmethod
    def skipped_nlp_payload(reason: str = "skipped: trivial/empty") -> dict:
        return {
            "has_excuse": False,
            "excuse_stage": "none",
            "severity": 0.0,
            "reason": reason,
            "skipped": True,
        }

    def load_unprocessed_reports(self, limit: int = 10, skip_trivial: bool = True) -> pd.DataFrame:
        """讀取尚未 LLM 解析的賽後報告（可略過無內容）。"""
        self.ensure_nlp_result_column()
        # 多取一些再於 Python 過濾，避免 SQL 難表達「無特別報告」
        fetch_n = max(limit * 5, limit + 50) if skip_trivial else limit
        q = text("""
            SELECT id, entity_type, entity_id, report_type, report_text
            FROM text_reports
            WHERE nlp_result IS NULL
              AND report_text IS NOT NULL
              AND LENGTH(TRIM(report_text)) > 0
            ORDER BY id
            LIMIT :lim
        """)
        try:
            df = pd.read_sql(q, self.engine, params={"lim": int(fetch_n)})
        except Exception as e:
            print(f"load_unprocessed_reports failed: {e}")
            return pd.DataFrame()
        if df.empty:
            return df
        if skip_trivial:
            df = df[~df["report_text"].apply(self.is_trivial_report)].copy()
        return df.head(limit).reset_index(drop=True)

    def mark_trivial_reports_skipped(self, report_ids=None, limit: int = 500) -> int:
        """把空白／無特別報告直接寫入 skipped nlp_result，不呼叫 LLM。"""
        self.ensure_nlp_result_column()
        if report_ids is not None:
            ids = [int(x) for x in report_ids]
            if not ids:
                return 0
            frames = []
            for i in range(0, len(ids), 400):
                chunk = ids[i:i + 400]
                id_list = ",".join(str(x) for x in chunk)
                frames.append(pd.read_sql(
                    f"SELECT id, report_text FROM text_reports WHERE nlp_result IS NULL AND id IN ({id_list})",
                    self.engine,
                ))
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        else:
            df = pd.read_sql(text("""
                SELECT id, report_text FROM text_reports
                WHERE nlp_result IS NULL
                ORDER BY id
                LIMIT :lim
            """), self.engine, params={"lim": int(limit)})

        if df.empty:
            return 0
        n = 0
        payload = json.dumps(self.skipped_nlp_payload(), ensure_ascii=False)
        with self.engine.begin() as conn:
            for _, row in df.iterrows():
                if not self.is_trivial_report(row["report_text"]):
                    continue
                conn.execute(
                    text("UPDATE text_reports SET nlp_result = :payload WHERE id = :id"),
                    {"payload": payload, "id": int(row["id"])},
                )
                n += 1
        return n

    def load_reports_for_upcoming_race(
        self,
        race_id: str,
        lookback_days: int = 360,
        only_unprocessed: bool = True,
    ) -> pd.DataFrame:
        """
        只取「本場排位馬匹」在 lookback 內的歷史報告。
        以品牌號（L100）優先對齊，其次正規化馬名。
        """
        self.ensure_nlp_result_column()
        try:
            upcoming = pd.read_sql(
                text("""
                    SELECT horse_no, horse_name, brand_num
                    FROM upcoming_runners
                    WHERE race_id = :rid
                    ORDER BY horse_no
                """),
                self.engine,
                params={"rid": race_id},
            )
        except Exception:
            # brand_num 欄位可能不存在
            upcoming = pd.read_sql(
                text("""
                    SELECT horse_no, horse_name
                    FROM upcoming_runners
                    WHERE race_id = :rid
                    ORDER BY horse_no
                """),
                self.engine,
                params={"rid": race_id},
            )

        if upcoming.empty:
            return pd.DataFrame()

        brands = set()
        names = set()
        for _, row in upcoming.iterrows():
            hn = str(row.get("horse_name") or "")
            bn = row.get("brand_num")
            if bn is not None and str(bn).strip() and str(bn).strip().lower() not in ("none", "nan"):
                brands.add(str(bn).strip().upper())
            m = re.search(r"\(([A-Z]\d+)\)", hn.upper())
            if m:
                brands.add(m.group(1))
            names.add(normalize_person_name(hn))

        # 歷史 runners：品牌號或馬名對得上
        hist = pd.read_sql(text("""
            SELECT ru.runner_id, ru.horse_name, ru.brand_num, m.racing_date
            FROM runners ru
            JOIN races r ON ru.race_id = r.race_id
            JOIN race_meetings m ON r.meeting_id = m.meeting_id
            WHERE ru.finish_order_num IS NOT NULL
        """), self.engine)
        if hist.empty:
            return pd.DataFrame()

        hist["racing_date"] = pd.to_datetime(hist["racing_date"])
        cutoff = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=int(lookback_days))
        hist = hist[hist["racing_date"] >= cutoff].copy()
        hist["horse_name_norm"] = hist["horse_name"].apply(normalize_person_name)
        hist["brand_norm"] = hist["brand_num"].astype(str).str.strip().str.upper()
        hist.loc[hist["brand_norm"].isin(["", "NONE", "NAN", "NAT"]), "brand_norm"] = None

        mask = hist["horse_name_norm"].isin(names)
        if brands:
            mask = mask | hist["brand_norm"].isin(brands)
        matched_runners = hist.loc[mask, "runner_id"].astype(str).unique().tolist()
        if not matched_runners:
            return pd.DataFrame()

        # 分批 IN，避免參數過長
        frames = []
        chunk_size = 400
        for i in range(0, len(matched_runners), chunk_size):
            chunk = matched_runners[i:i + chunk_size]
            placeholders = ", ".join([f":id{j}" for j in range(len(chunk))])
            params = {f"id{j}": chunk[j] for j in range(len(chunk))}
            where_nlp = "AND nlp_result IS NULL" if only_unprocessed else ""
            q = text(f"""
                SELECT id, entity_type, entity_id, report_type, report_text, nlp_result
                FROM text_reports
                WHERE entity_type = 'runner'
                  AND entity_id IN ({placeholders})
                  {where_nlp}
                ORDER BY id
            """)
            try:
                frames.append(pd.read_sql(q, self.engine, params=params))
            except Exception as e:
                # SQLite 退回字串 IN
                ids_sql = ",".join([f"'{x}'" for x in chunk])
                q2 = f"""
                    SELECT id, entity_type, entity_id, report_type, report_text, nlp_result
                    FROM text_reports
                    WHERE entity_type = 'runner'
                      AND entity_id IN ({ids_sql})
                      {"AND nlp_result IS NULL" if only_unprocessed else ""}
                    ORDER BY id
                """
                try:
                    frames.append(pd.read_sql(q2, self.engine))
                except Exception as e2:
                    print(f"load_reports_for_upcoming_race failed: {e} / {e2}")

        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["id"])
        out["is_trivial"] = out["report_text"].apply(self.is_trivial_report)
        out["needs_llm"] = (~out["is_trivial"]) & (
            out["nlp_result"].isna() if "nlp_result" in out.columns else True
        )
        return out

    def save_nlp_result(self, report_id: int, result: dict) -> None:
        payload = json.dumps(result, ensure_ascii=False)
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE text_reports SET nlp_result = :payload WHERE id = :id"),
                {"payload": payload, "id": int(report_id)},
            )

    def nlp_status(self) -> dict:
        """NLP 解析進度摘要。"""
        self.ensure_nlp_result_column()
        try:
            row = pd.read_sql(text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(nlp_result) AS done,
                    COUNT(*) FILTER (WHERE nlp_result IS NULL) AS pending
                FROM text_reports
                WHERE report_text IS NOT NULL AND LENGTH(TRIM(report_text)) > 0
            """), self.engine).iloc[0]
            return {
                "total": int(row["total"]),
                "done": int(row["done"]),
                "pending": int(row["pending"]),
            }
        except Exception:
            # SQLite 無 FILTER；退回兩次查詢
            try:
                total = pd.read_sql(
                    "SELECT COUNT(*) AS n FROM text_reports WHERE report_text IS NOT NULL",
                    self.engine,
                ).iloc[0]["n"]
                done = pd.read_sql(
                    "SELECT COUNT(*) AS n FROM text_reports WHERE nlp_result IS NOT NULL",
                    self.engine,
                ).iloc[0]["n"]
                return {"total": int(total), "done": int(done), "pending": int(total) - int(done)}
            except Exception as e:
                return {"total": 0, "done": 0, "pending": 0, "error": str(e)}

    def load_excuse_map(self) -> dict:
        """
        runner_id -> 最佳受阻結果（severity 最高；同 severity 取較重 stage）。
        需先跑 LLM 把 nlp_result 寫回 text_reports。
        """
        self.ensure_nlp_result_column()
        try:
            df = pd.read_sql(text("""
                SELECT entity_id, nlp_result
                FROM text_reports
                WHERE nlp_result IS NOT NULL
                  AND entity_type = 'runner'
            """), self.engine)
        except Exception as e:
            print(f"load_excuse_map failed: {e}")
            return {}

        stage_rank = {"none": 0, "early": 1, "middle": 2, "late": 3}
        best = {}
        for _, row in df.iterrows():
            try:
                obj = json.loads(row["nlp_result"]) if isinstance(row["nlp_result"], str) else row["nlp_result"]
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(obj, dict) or not obj.get("has_excuse"):
                continue
            sev = float(obj.get("severity") or 0.0)
            stage = str(obj.get("excuse_stage") or "none").lower()
            rid = str(row["entity_id"])
            prev = best.get(rid)
            if prev is None or sev > prev["severity"] or (
                sev == prev["severity"] and stage_rank.get(stage, 0) > stage_rank.get(prev["excuse_stage"], 0)
            ):
                best[rid] = {
                    "has_excuse": True,
                    "excuse_stage": stage,
                    "severity": sev,
                    "reason": obj.get("reason", ""),
                }
        return best

    def apply_nlp_excuse_boost(self, df: pd.DataFrame, excuse_map: dict = None) -> pd.DataFrame:
        """
        將 NLP 受阻結果併入 raw_score（白皮書 Phase 4 簡化實作）：
        - 已有入位分：依 stage 乘數與 severity 放大
        - 未入位：給予部分虛擬入位分（ capped ）
        需 runners.runner_id 才能對上 text_reports.entity_id。
        """
        out = df.copy()
        if "raw_score" not in out.columns:
            out = self.calculate_base_score(out)
        if excuse_map is None:
            excuse_map = self.load_excuse_map()
        if not excuse_map:
            out["excuse_applied"] = False
            out["excuse_stage"] = None
            out["excuse_severity"] = 0.0
            return out

        # 確保有 runner_id：歷史查詢若缺則從 race_id + brand 拼不了，這裡從 DB 補
        if "runner_id" not in out.columns:
            try:
                ids = pd.read_sql(
                    "SELECT runner_id, race_id, horse_name FROM runners WHERE finish_order_num IS NOT NULL",
                    self.engine,
                )
                ids["horse_name"] = ids["horse_name"].apply(normalize_person_name)
                out = out.merge(ids, on=["race_id", "horse_name"], how="left")
            except Exception as e:
                print(f"attach runner_id failed: {e}")
                out["excuse_applied"] = False
                return out

        mult_map = {
            "early": float(ModelConfig.EXCUSE_MULTIPLIER_EARLY),
            "middle": float(ModelConfig.EXCUSE_MULTIPLIER_MIDDLE),
            "late": float(ModelConfig.EXCUSE_MULTIPLIER_LATE),
        }
        late_cap = float(ModelConfig.EXCUSE_MULTIPLIER_LATE)
        place_w = float(ModelConfig.PLACE_WEIGHT)

        applied = []
        stages = []
        sevs = []
        new_scores = []
        for _, row in out.iterrows():
            rid = row.get("runner_id")
            info = excuse_map.get(str(rid)) if pd.notna(rid) else None
            base = float(row["raw_score"])
            if not info:
                applied.append(False)
                stages.append(None)
                sevs.append(0.0)
                new_scores.append(base)
                continue
            sev = float(info.get("severity") or 0.0)
            stage = str(info.get("excuse_stage") or "none")
            mult = mult_map.get(stage, 1.0)
            if base > 0:
                boosted = base * (1.0 + (mult - 1.0) * sev)
            else:
                # 未入位：給「虛擬入位分」，上限略低於真實 PLACE
                boosted = place_w * sev * (mult / late_cap) * 0.85
            applied.append(True)
            stages.append(stage)
            sevs.append(sev)
            new_scores.append(float(boosted))

        out["raw_score"] = new_scores
        out["excuse_applied"] = applied
        out["excuse_stage"] = stages
        out["excuse_severity"] = sevs
        return out

    def apply_class_drop_boost(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        白皮書 Phase 4 降班三條件（簡化實作）：
        須同時滿足才對「降班當仗」加 CLASS_DROP_BONUS，並略抬升近三仗未入位分。
        1) 今仗班次數字 > 近三仗（降班）
        2) 近三仗平均名次 > 7，且平均獨贏賠率 < 15
        3) 近三仗至少一場末段走位列全場前 30%
        """
        out = df.copy()
        if "raw_score" not in out.columns:
            out = self.calculate_base_score(out)
        out["class_drop_applied"] = False
        if "horse_name" not in out.columns or "class_num" not in out.columns:
            return out

        field_size = out.groupby("race_id")["horse_name"].transform("count")
        out["_field_size"] = field_size

        bonus = float(ModelConfig.CLASS_DROP_BONUS)
        place_w = float(ModelConfig.PLACE_WEIGHT)

        pieces = []
        for horse, g in out.groupby("horse_name", sort=False):
            g = g.sort_values("racing_date").copy()
            drop_flags = []
            for i in range(len(g)):
                if i < 3:
                    drop_flags.append(False)
                    continue
                prior = g.iloc[i - 3:i]
                cur = g.iloc[i]
                cur_cls = cur.get("class_num")
                prior_cls = prior["class_num"].dropna()
                if pd.isna(cur_cls) or prior_cls.empty:
                    drop_flags.append(False)
                    continue
                # 條件1：今仗班次數字更大（例如 4→5）
                if float(cur_cls) <= float(prior_cls.mean()):
                    drop_flags.append(False)
                    continue
                # 條件2：劣績但市場未棄
                avg_fin = float(prior["finish_order_num"].mean())
                odds = prior["win_odds"].dropna()
                avg_odds = float(odds.mean()) if not odds.empty else None
                if avg_fin <= 7 or avg_odds is None or avg_odds >= 15:
                    drop_flags.append(False)
                    continue
                # 條件3：末段走位前 30%
                strong_late = False
                for _, pr in prior.iterrows():
                    lp = pr.get("late_pos")
                    fs = pr.get("_field_size") or 0
                    if pd.notna(lp) and fs and float(lp) <= max(1.0, float(fs) * 0.30):
                        strong_late = True
                        break
                drop_flags.append(bool(strong_late))

            g["class_drop_applied"] = drop_flags
            scores = g["raw_score"].astype(float).tolist()
            for i, flag in enumerate(drop_flags):
                if not flag:
                    continue
                scores[i] = scores[i] + bonus
                for j in range(max(0, i - 3), i):
                    if scores[j] <= 0:
                        scores[j] = place_w * 0.35
            g["raw_score"] = scores
            pieces.append(g)

        if not pieces:
            return out
        result = pd.concat(pieces, ignore_index=True)
        if "_field_size" in result.columns:
            result = result.drop(columns=["_field_size"])
        return result

    def calculate_horse_factor(self, df: pd.DataFrame = None, apply_nlp: bool = True) -> pd.DataFrame:
        """馬匹近績：距離帶粗桶；可選套用 NLP 受阻補償與降班修正後再算 Z。"""
        if df is None or df.empty:
            df = self.fetch_historical_data()
        if df.empty:
            return pd.DataFrame()

        work = df.copy()
        if "raw_score" not in work.columns:
            work = self.calculate_base_score(work)
        if apply_nlp:
            work = self.apply_nlp_excuse_boost(work)
        work = self.apply_class_drop_boost(work)

        work["horse_name_clean"] = work["horse_name"].fillna("未知馬匹").astype(str)
        out = self.calculate_entity_factor(
            work,
            "horse_name_clean",
            ModelConfig.HORSE_DECAY,
            ModelConfig.HORSE_SMOOTH_C,
            use_distance_band=True,
        )
        if out.empty:
            return out
        out["factor_type"] = "HORSE"
        return out.rename(columns={"horse_name_clean": "entity_name"})

    def _jockey_z_lookup(self, jockey_scores: pd.DataFrame) -> dict:
        """(bucket_id, jockey_name) -> z_score；另建 jockey 跨桶平均作後備。"""
        by_bucket = {}
        by_name = {}
        if jockey_scores is None or jockey_scores.empty:
            return by_bucket, by_name
        for _, row in jockey_scores.iterrows():
            name = normalize_person_name(row['entity_name'])
            key = (str(row['bucket_id']), name)
            z = float(row['z_score'])
            by_bucket[key] = z
            by_name.setdefault(name, []).append(z)
        by_name_avg = {k: float(sum(v) / len(v)) for k, v in by_name.items()}
        return by_bucket, by_name_avg

    def lookup_jockey_z(self, jockey_name: str, bucket_id: str, by_bucket: dict, by_name_avg: dict):
        """
        層級回退：
        1) 精確鍵（粗桶 ST_SPRINT 或細桶 ST_A_1200）
        2) 若傳入細桶 → 轉成距離帶粗桶再查
        3) 同場地其他距離帶平均（可選）
        4) 該騎師跨桶平均
        """
        name = normalize_person_name(jockey_name)
        if not name:
            return None, None

        if (bucket_id, name) in by_bucket:
            return by_bucket[(bucket_id, name)], 'exact'

        venue, track, dist = parse_bucket_parts(bucket_id)
        # 細桶 → 粗桶
        if venue and dist:
            band_key = make_band_bucket_id(venue=venue, distance_m=dist)
            if (band_key, name) in by_bucket:
                return by_bucket[(band_key, name)], 'band'

        # 已是粗桶 ST_SPRINT
        parts = str(bucket_id).split("_")
        if len(parts) == 2 and parts[0] in ("ST", "HV"):
            venue = parts[0]
            zs = [
                z for (b, n), z in by_bucket.items()
                if n == name and b.startswith(f"{venue}_")
            ]
            if zs:
                return float(sum(zs) / len(zs)), 'venue_bands'

        if name in by_name_avg:
            return by_name_avg[name], 'global_avg'
        return None, None

    def score_partnership_near_distance(
        self,
        horse_name: str,
        jockey_name: str,
        target_distance_m,
        hist_df: pd.DataFrame,
    ):
        """
        人馬合作現場評分：仍用同一組合的全部歷史（不另開細桶），
        但對「接近今仗距離」的場次加權更高 → 平衡樣本數與距離相關性。
        回傳 dict: z_proxy, weighted_runs, actual_runs, source
        """
        if hist_df is None or hist_df.empty:
            return {'z_proxy': None, 'weighted_runs': 0.0, 'actual_runs': 0, 'source': 'no_hist'}

        horse = normalize_person_name(horse_name)
        jockey = normalize_person_name(jockey_name)
        pair = hist_df[
            (hist_df['horse_name'].apply(normalize_person_name) == horse)
            & (hist_df['jockey_name'].apply(normalize_person_name) == jockey)
        ].copy()
        if pair.empty:
            return {'z_proxy': None, 'weighted_runs': 0.0, 'actual_runs': 0, 'source': 'no_pair'}

        if 'raw_score' not in pair.columns:
            pair = self.calculate_base_score(pair)
        pair = self.apply_time_decay(pair, ModelConfig.HORSE_JOCKEY_DECAY)

        prox = pair['distance_m'].apply(lambda d: distance_proximity_weight(d, target_distance_m))
        pair = pair.copy()
        pair['w'] = pair['time_weight'] * prox
        pair = pair[pair['w'] > 0]
        if pair.empty:
            return {'z_proxy': None, 'weighted_runs': 0.0, 'actual_runs': 0, 'source': 'zero_weight'}

        w_runs = float(pair['w'].sum())
        w_score = float((pair['raw_score'] * pair['w']).sum())
        # 用全體 hist 的平均 raw 作 prior（簡化貝葉斯）
        prior_c = float(ModelConfig.HORSE_JOCKEY_SMOOTH_C)
        global_avg = float(hist_df['raw_score'].mean()) if 'raw_score' in hist_df.columns else 0.15
        adjusted = (w_score + prior_c * global_avg) / (w_runs + prior_c)

        # 轉成相對全域合作水準的粗 Z：用 adjusted 相對 prior
        z_proxy = (adjusted - global_avg) / max(abs(global_avg), 0.05)

        return {
            'z_proxy': float(z_proxy),
            'adjusted_score': float(adjusted),
            'weighted_runs': w_runs,
            'actual_runs': int(len(pair)),
            'source': 'near_distance_weighted',
        }

    def compute_jockey_upgrade_delta(
        self,
        horse_name: str,
        current_jockey: str,
        race_bucket: str,
        hist_df: pd.DataFrame,
        jockey_scores: pd.DataFrame,
        lookback: int = None,
    ):
        """
        白皮書 B 軌：Upgrade Delta = 今仗騎師 Z − 該駒近 N 仗前任騎師平均 Z。
        即使人馬無合作歷史，仍可給出換人信號分數。
        回傳 dict: delta, current_z, prev_avg_z, prev_jockeys, source
        """
        lookback = lookback if lookback is not None else ModelConfig.JOCKEY_LOOKBACK_RACES
        by_bucket, by_name_avg = self._jockey_z_lookup(jockey_scores)

        curr_z, curr_src = self.lookup_jockey_z(current_jockey, race_bucket, by_bucket, by_name_avg)
        if curr_z is None:
            return {
                'delta': None,
                'current_z': None,
                'prev_avg_z': None,
                'prev_jockeys': [],
                'source': 'no_current_jockey_z',
            }

        horse = normalize_person_name(horse_name)
        curr_j = normalize_person_name(current_jockey)
        if hist_df is None or hist_df.empty:
            return {
                'delta': None,
                'current_z': curr_z,
                'prev_avg_z': None,
                'prev_jockeys': [],
                'source': 'no_hist',
            }

        horse_runs = hist_df[hist_df['horse_name'].apply(normalize_person_name) == horse].copy()
        if horse_runs.empty:
            return {
                'delta': None,
                'current_z': curr_z,
                'prev_avg_z': None,
                'prev_jockeys': [],
                'source': 'horse_no_runs',
            }

        horse_runs = horse_runs.sort_values('racing_date', ascending=False)
        prev_rows = horse_runs.head(int(lookback))
        prev_zs = []
        prev_names = []
        for _, prow in prev_rows.iterrows():
            pj = normalize_person_name(prow['jockey_name'])
            # 同騎續配不算「前任」；仍納入平均以反映近期騎師水準也可——白皮書寫前任，排除今仗同一人較合理
            if pj == curr_j:
                continue
            pz, _ = self.lookup_jockey_z(pj, race_bucket, by_bucket, by_name_avg)
            if pz is not None:
                prev_zs.append(pz)
                prev_names.append(pj)

        if not prev_zs:
            return {
                'delta': None,
                'current_z': curr_z,
                'prev_avg_z': None,
                'prev_jockeys': prev_names,
                'source': 'no_prev_jockey_z',
            }

        prev_avg = float(sum(prev_zs) / len(prev_zs))
        return {
            'delta': float(curr_z - prev_avg),
            'current_z': float(curr_z),
            'prev_avg_z': prev_avg,
            'prev_jockeys': prev_names,
            'source': f'upgrade:{curr_src}',
        }

    @staticmethod
    def scale_upgrade_delta(delta: float) -> float:
        """
        將原始換人Δ（兩 Z 之差，常過大）飽和到與合作 Z 相近的尺度。
        adopted_B = CAP * tanh(delta / CAP)
        """
        import math
        if delta is None or (isinstance(delta, float) and math.isnan(delta)):
            return None
        cap = float(ModelConfig.UPGRADE_DELTA_CAP)
        if cap <= 0:
            return float(delta)
        return float(cap * math.tanh(float(delta) / cap))

    def adopt_horse_jockey_score(self, partnership_z, partnership_runs, raw_delta):
        """
        雙軌採用規則（熟識優先）：
        - 有合作 → 以 A 為主，並加熟識 prior；B 最多輕量混合
        - 無合作 → 僅用正規化 B，再乘 B_ONLY 折扣（換人訊號 < 已合作）
        """
        scaled_b = self.scale_upgrade_delta(raw_delta) if raw_delta is not None else None
        has_a = partnership_z is not None
        runs = int(partnership_runs) if partnership_runs is not None else 0
        prior = float(ModelConfig.HJ_PARTNERSHIP_PRIOR)

        if has_a and runs >= ModelConfig.HJ_MIN_RUNS_PURE_A:
            adopted = float(partnership_z) + prior
            return adopted, None if scaled_b is None else float(scaled_b), 'A:合作歷史(+熟識)'
        if has_a and scaled_b is not None:
            w = float(ModelConfig.HJ_SPARSE_B_BLEND)
            blended = (1.0 - w) * float(partnership_z) + w * float(scaled_b)
            adopted = blended + prior
            return float(adopted), float(scaled_b), f'A為主+熟識(出賽{runs})'
        if has_a:
            return float(partnership_z) + prior, None if scaled_b is None else float(scaled_b), 'A:合作歷史(+熟識)'
        if scaled_b is not None:
            discounted = float(scaled_b) * float(ModelConfig.UPGRADE_B_ONLY_SCALE)
            return discounted, float(scaled_b), 'B:換人Δ(正規化·無合作折扣)'
        return None, None, '無'

    def _assign_draw_group(self, draw: int) -> str:
        """將檔位 1-14 轉換為 4 個群組"""
        if pd.isna(draw):
            return "Unknown"
        d = int(draw)
        bounds = ModelConfig.DRAW_GROUP_BOUNDARIES
        if d <= bounds[0]: return "Inner"
        if d <= bounds[1]: return "Mid-Inner"
        if d <= bounds[2]: return "Mid-Outer"
        return "Outer"

    def calculate_draw_factor(self, df: pd.DataFrame) -> pd.DataFrame:
        """計算檔位與場地偏差因子"""
        temp_df = df.copy()
        
        # 1. 將檔位群組化
        temp_df['draw_group'] = temp_df['draw'].apply(self._assign_draw_group)
        
        # 過濾無效檔位
        temp_df = temp_df[temp_df['draw_group'] != "Unknown"]
        
        # 2. 檔位不像人為因素那樣快速衰減，我們賦予長效權重 (過去一年)
        # 不使用原有的 JOCKEY_DECAY，改用固定權重或極慢衰減
        # 這裡簡化處理：直接不衰減或極慢衰減，讓場地偏差基於大數據
        temp_df['time_weight'] = 1.0 
        temp_df['weighted_score'] = temp_df['raw_score'] * temp_df['time_weight']
        temp_df['weighted_runs'] = 1.0 * temp_df['time_weight']
        
        # 3. 按 Bucket 與 Draw Group 進行聚合
        grouped = temp_df.groupby(['bucket_id', 'draw_group']).agg({
            'weighted_score': 'sum',
            'weighted_runs': 'sum',
            'raw_score': 'count',
            'finish_order_num': [
                ('wins', lambda x: (x == 1).sum()),
                ('places', lambda x: x.isin([2, 3, 4]).sum())
            ]
        })
        
        grouped.columns = ['weighted_score', 'weighted_runs', 'actual_runs', 'wins', 'places']
        grouped = grouped.reset_index()
        
        grouped = grouped[grouped['weighted_runs'] > 0]
        
        # 4. 貝葉斯平滑 (檔位樣本通常很大，C 可以設大一點)
        result = []
        for bucket, group in grouped.groupby('bucket_id'):
            smoothed = self.apply_bayesian_smoothing(group.copy(), ModelConfig.DRAW_SMOOTH_C)
            result.append(smoothed)
            
        if not result:
            return pd.DataFrame()
            
        final_df = pd.concat(result, ignore_index=True)
        
        # 5. Z-Score (代表該檔位在該場地的優劣勢)
        final_df['z_score'] = final_df.groupby('bucket_id')['adjusted_score'].transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-9)
        )
        
        return final_df

    def extract_sectional_positions(self, df: pd.DataFrame) -> pd.DataFrame:
        """從 raw_json 中提取分段走位數據 (早段位置與追回名次)"""
        import json
        import numpy as np
        
        def parse_positions(raw_str):
            try:
                data = json.loads(raw_str)
                sections = data.get("sections", {})
                
                # 尋找早段位置 (Stage 1 或 Stage 2)
                early_pos = None
                for i in range(1, 4):
                    stage = sections.get(f"stage_{i}")
                    if stage and stage.get("position"):
                        try:
                            early_pos = int(stage["position"])
                            break
                        except ValueError:
                            pass
                            
                return early_pos if early_pos is not None else np.nan
            except Exception:
                return np.nan

        df['early_position'] = df['raw_json'].apply(parse_positions)
        
        # 計算追回名次 (Positions Gained) = 早段名次 - 最終名次
        # 如果早段第 10 名，最終第 2 名 => 追回 8 名 (後追力強)
        # 如果早段第 2 名，最終第 10 名 => 追回 -8 名 (力弱大敗)
        df['positions_gained'] = df['early_position'] - df['finish_order_num']
        
        # 標記跑法風格 (Running Style)
        # 1-4: 前領 (Front-Runner), 5-8: 居中 (Mid-Pack), 9+: 後追 (Closer)
        conditions = [
            (df['early_position'] <= 4),
            (df['early_position'] <= 8),
            (df['early_position'] > 8)
        ]
        choices = ['前領 (Front-Runner)', '居中 (Mid-Pack)', '後追 (Closer)']
        df['running_style'] = np.select(conditions, choices, default='未知 (Unknown)')
        
        return df

    def extract_time_and_fsr(self, df: pd.DataFrame) -> pd.DataFrame:
        """提取完成時間與末段時間，計算速度指數與 FSR"""
        import json
        
        def time_to_seconds(t_str):
            if not isinstance(t_str, str) or not t_str:
                return np.nan
            parts = t_str.split(':')
            try:
                if len(parts) == 2:
                    return float(parts[0]) * 60 + float(parts[1])
                return float(t_str)
            except ValueError:
                return np.nan

        def get_l400m_time(raw_str):
            try:
                data = json.loads(raw_str)
                sections = data.get("sections", {})
                
                # 尋找最後一個非 null 的 stage 的 sectional_time
                last_time = None
                for i in range(6, 0, -1):
                    stage = sections.get(f"stage_{i}")
                    if stage and stage.get("sectional_time"):
                        last_time = stage["sectional_time"]
                        break
                        
                return time_to_seconds(last_time)
            except Exception:
                return np.nan

        df['final_time_sec'] = df['final_time'].apply(time_to_seconds)
        df['l400m_time_sec'] = df['raw_json'].apply(get_l400m_time)
        
        # 計算平均速度 (m/s) 與 末段速度 (m/s)
        # 假設 L400m 距離為 400 米
        df['avg_speed'] = df['distance_m'] / df['final_time_sec']
        df['l400m_speed'] = 400.0 / df['l400m_time_sec']
        
        # 計算 FSR (Finishing Speed Ratio)
        df['fsr'] = (df['avg_speed'] / df['l400m_speed']) * 100.0
        
        # ==========================================
        # 計算 Speed Figure (絕對時間標準化)
        # ==========================================
        # 1. 計算 Par Time (同場地、同賽道、同距離、同班次的平均時間)
        par_times = df.groupby(['course', 'track', 'distance_m', 'race_class'])['final_time_sec'].transform('mean')
        df['time_delta'] = par_times - df['final_time_sec'] # 正數代表比平均快
        
        # 2. 計算 Daily Track Variant (當日場地偏差)
        # 同一天同場地的平均 time_delta
        daily_variant = df.groupby(['racing_date', 'course', 'track'])['time_delta'].transform('mean')
        
        # 3. 速度指數 (Speed Figure) = 自身時間差 - 當日場地偏差
        df['speed_figure'] = df['time_delta'] - daily_variant
        
        return df

    def save_factor_scores(self, *factor_dfs) -> int:
        """將因子分數寫入 factor_scores（先清再寫，避免舊 bucket 殘留）。"""
        frames = [f for f in factor_dfs if f is not None and not f.empty]
        if not frames:
            return 0

        combined = pd.concat(frames, ignore_index=True)
        required = ['factor_type', 'bucket_id', 'entity_name', 'actual_runs',
                    'weighted_runs', 'adjusted_score', 'z_score']
        for col in required:
            if col not in combined.columns:
                raise ValueError(f"factor score missing column: {col}")

        out = combined[required].copy()
        out['entity_name'] = out['entity_name'].astype(str)
        out['calculated_at'] = datetime.utcnow().isoformat(sep=' ', timespec='seconds')

        with self.engine.begin() as conn:
            # 只覆蓋本次有計算的 factor_type，保留未來其他類型空間
            types = tuple(sorted(out['factor_type'].unique().tolist()))
            if len(types) == 1:
                conn.execute(text("DELETE FROM factor_scores WHERE factor_type = :t"), {"t": types[0]})
            else:
                conn.execute(
                    text(f"DELETE FROM factor_scores WHERE factor_type IN {types}")
                )
            out.to_sql('factor_scores', conn, if_exists='append', index=False)

        return len(out)

    def load_factor_scores(self, factor_types=None) -> pd.DataFrame:
        """從資料庫讀取已落庫的因子分數。"""
        try:
            if factor_types:
                types = ",".join(f"'{t}'" for t in factor_types)
                query = f"SELECT * FROM factor_scores WHERE factor_type IN ({types})"
            else:
                query = "SELECT * FROM factor_scores"
            return pd.read_sql(query, self.engine)
        except Exception as e:
            print(f"load_factor_scores failed: {e}")
            return pd.DataFrame()

    def run_all_factors(self, persist: bool = True, apply_nlp: bool = True):
        """執行核心因子計算；persist=True 時寫入 factor_scores。"""
        print("Fetching historical data...")
        df = self.fetch_historical_data()
        if df.empty:
            print("No historical data found. Please run batch crawler first.")
            return None, None, None, None, None, None
            
        df = self.calculate_base_score(df)
        
        print("Calculating Jockey Factor (distance-band buckets)...")
        jockey_df = self.calculate_entity_factor(
            df, 'jockey_name', 
            ModelConfig.JOCKEY_DECAY, 
            ModelConfig.JOCKEY_SMOOTH_C,
            use_distance_band=True,
        )
        jockey_df['factor_type'] = 'JOCKEY'
        jockey_df = jockey_df.rename(columns={'jockey_name': 'entity_name'})
        
        print("Calculating Trainer Factor (distance-band buckets)...")
        trainer_df = self.calculate_entity_factor(
            df, 'trainer_name', 
            ModelConfig.TRAINER_DECAY, 
            ModelConfig.TRAINER_SMOOTH_C,
            use_distance_band=True,
        )
        trainer_df['factor_type'] = 'TRAINER'
        trainer_df = trainer_df.rename(columns={'trainer_name': 'entity_name'})
        
        print("Calculating Synergy Factor (distance-band buckets)...")
        df['synergy_name'] = df.apply(
            lambda r: synergy_name(r['jockey_name'], r['trainer_name']), axis=1
        )
        synergy_df = self.calculate_entity_factor(
            df, 'synergy_name', 
            ModelConfig.SYNERGY_DECAY, 
            ModelConfig.SYNERGY_SMOOTH_C,
            use_distance_band=True,
        )
        synergy_df['factor_type'] = 'SYNERGY'
        synergy_df = synergy_df.rename(columns={'synergy_name': 'entity_name'})
        
        print("Calculating Draw Factor...")
        draw_df = self.calculate_draw_factor(df)
        draw_df['factor_type'] = 'DRAW'
        draw_df = draw_df.rename(columns={'draw_group': 'entity_name'})

        print("Calculating Horse-Jockey Factor (GLOBAL)...")
        hj_df = self.calculate_horse_jockey_factor(df)

        print("Calculating Horse recent-form (distance-band + NLP/class-drop)...")
        horse_df = self.calculate_horse_factor(df, apply_nlp=apply_nlp)

        if persist:
            n = self.save_factor_scores(
                jockey_df, trainer_df, synergy_df, draw_df, hj_df, horse_df
            )
            print(f"Saved {n} factor score rows to factor_scores.")

        return jockey_df, trainer_df, synergy_df, draw_df, hj_df, horse_df

if __name__ == "__main__":
    calc = FactorCalculator()
    j, t, s, d, hj, h = calc.run_all_factors(persist=True)
    if j is not None:
        print("\n=== Jockey Factor Preview (Top 5 Z-Score) ===")
        print(j.sort_values('z_score', ascending=False).head(5)[['bucket_id', 'entity_name', 'actual_runs', 'adjusted_score', 'z_score']])
        print("\nSample buckets:", sorted(j['bucket_id'].unique())[:10])
        if hj is not None and not hj.empty:
            print("HJ GLOBAL rows:", len(hj))
        if h is not None and not h.empty:
            print("HORSE band rows:", len(h), "buckets:", sorted(h['bucket_id'].unique()))
