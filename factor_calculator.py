import pandas as pd
import numpy as np
from datetime import datetime
from sqlalchemy import create_engine, text
import os
from config import ModelConfig
from bucket_utils import (
    make_bucket_id,
    normalize_person_name,
    synergy_name,
    horse_jockey_name,
    is_valid_bucket,
    GLOBAL_BUCKET,
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
                ru.jockey_name, ru.trainer_name, ru.horse_name, ru.finish_order_num, ru.bar_draw as draw,
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

        # 標準分桶：Venue_Track_Distance（例如 HV_C+3_1650）
        df['bucket_id'] = df.apply(
            lambda row: make_bucket_id(
                race_id=row['race_id'],
                course=row['course'],
                track=row['track'],
                distance_m=row['distance_m'],
            ),
            axis=1,
        )
        df = df[df['bucket_id'].apply(is_valid_bucket)].copy()
        
        return df

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
    ) -> pd.DataFrame:
        """計算特定實體因子。global_bucket=True 時不分場地距離（人馬合作）。"""
        temp_df = df.copy()
        if global_bucket:
            temp_df['bucket_id'] = GLOBAL_BUCKET
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

    def run_all_factors(self, persist: bool = True):
        """執行核心因子計算；persist=True 時寫入 factor_scores。"""
        print("Fetching historical data...")
        df = self.fetch_historical_data()
        if df.empty:
            print("No historical data found. Please run batch crawler first.")
            return None, None, None, None
            
        df = self.calculate_base_score(df)
        
        print("Calculating Jockey Factor...")
        jockey_df = self.calculate_entity_factor(
            df, 'jockey_name', 
            ModelConfig.JOCKEY_DECAY, 
            ModelConfig.JOCKEY_SMOOTH_C
        )
        jockey_df['factor_type'] = 'JOCKEY'
        jockey_df = jockey_df.rename(columns={'jockey_name': 'entity_name'})
        
        print("Calculating Trainer Factor...")
        trainer_df = self.calculate_entity_factor(
            df, 'trainer_name', 
            ModelConfig.TRAINER_DECAY, 
            ModelConfig.TRAINER_SMOOTH_C
        )
        trainer_df['factor_type'] = 'TRAINER'
        trainer_df = trainer_df.rename(columns={'trainer_name': 'entity_name'})
        
        print("Calculating Synergy Factor...")
        df['synergy_name'] = df.apply(
            lambda r: synergy_name(r['jockey_name'], r['trainer_name']), axis=1
        )
        synergy_df = self.calculate_entity_factor(
            df, 'synergy_name', 
            ModelConfig.SYNERGY_DECAY, 
            ModelConfig.SYNERGY_SMOOTH_C
        )
        synergy_df['factor_type'] = 'SYNERGY'
        synergy_df = synergy_df.rename(columns={'synergy_name': 'entity_name'})
        
        print("Calculating Draw Factor...")
        draw_df = self.calculate_draw_factor(df)
        draw_df['factor_type'] = 'DRAW'
        draw_df = draw_df.rename(columns={'draw_group': 'entity_name'})

        print("Calculating Horse-Jockey Factor (GLOBAL)...")
        hj_df = self.calculate_horse_jockey_factor(df)

        if persist:
            n = self.save_factor_scores(jockey_df, trainer_df, synergy_df, draw_df, hj_df)
            print(f"Saved {n} factor score rows to factor_scores.")

        return jockey_df, trainer_df, synergy_df, draw_df, hj_df

if __name__ == "__main__":
    calc = FactorCalculator()
    j, t, s, d, hj = calc.run_all_factors(persist=True)
    if j is not None:
        print("\n=== Jockey Factor Preview (Top 5 Z-Score) ===")
        print(j.sort_values('z_score', ascending=False).head(5)[['bucket_id', 'entity_name', 'actual_runs', 'adjusted_score', 'z_score']])
        print("\nSample buckets:", sorted(j['bucket_id'].unique())[:10])
        if hj is not None and not hj.empty:
            print("HJ GLOBAL rows:", len(hj))
