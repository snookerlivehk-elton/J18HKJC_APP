import pandas as pd
import sqlite3
import os
from config import ModelConfig
from factor_calculator import FactorCalculator

# 根據環境變數決定使用 SQLite 或 PostgreSQL
from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH
if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = os.getenv("DATABASE_URL_SYNC", "postgresql://user:password@localhost:5432/j18db")

class InferenceEngine:
    def __init__(self):
        self.db_url = DATABASE_URL_SYNC
        self.calc = FactorCalculator()

    def get_upcoming_races(self) -> pd.DataFrame:
        """獲取所有即將舉行的賽事清單"""
        if USE_SQLITE and not os.path.exists(SQLITE_DB_PATH):
            return pd.DataFrame()
            
        try:
            import sqlalchemy
            engine = sqlalchemy.create_engine(self.db_url)
            query = "SELECT * FROM upcoming_races ORDER BY racing_date ASC, race_num ASC"
            return pd.read_sql(query, engine)
        except Exception as e:
            print(f"Error fetching upcoming races: {e}")
            return pd.DataFrame()

    def get_race_runners(self, race_id: str) -> pd.DataFrame:
        """獲取特定賽事的馬匹排位名單與速勢能量"""
        try:
            import sqlalchemy
            engine = sqlalchemy.create_engine(self.db_url)
            query = f"""
                SELECT 
                    r.horse_no, r.horse_name, r.draw, r.jockey_name, r.trainer_name, 
                    r.handicap_weight, r.horse_weight, r.gear,
                    s.form_rating, s.speed_energy, s.speed_energy_delta
                FROM upcoming_runners r
                LEFT JOIN upcoming_speedguide s ON r.runner_id = s.runner_id
                WHERE r.race_id = '{race_id}'
                ORDER BY r.horse_no ASC
            """
            return pd.read_sql(query, engine)
        except Exception as e:
            print(f"Error fetching runners for {race_id}: {e}")
            return pd.DataFrame()

    def _map_form_rating(self, rating: str) -> float:
        """將狀態評級 (如 A, B, C) 轉換為數值分數"""
        if pd.isna(rating): return 0.0
        r = str(rating).upper().strip()
        mapping = {'A+': 3.0, 'A': 2.0, 'A-': 1.0, 'B+': 0.5, 'B': 0.0, 'B-': -0.5, 'C': -1.0, 'D': -2.0}
        return mapping.get(r, 0.0)

    def predict_race(self, race_id: str, df_hist: pd.DataFrame = None) -> pd.DataFrame:
        """
        執行單場賽事推論：
        1. 讀取排位表
        2. 計算賽事 Bucket
        3. 從 df_hist 字典中查找 Z-Score
        4. 加權總和
        """
        # 1. 取得賽事與馬匹資訊
        races_df = self.get_upcoming_races()
        if races_df.empty: return pd.DataFrame()
        
        race_info = races_df[races_df['race_id'] == race_id].iloc[0]
        runners_df = self.get_race_runners(race_id)
        if runners_df.empty: return pd.DataFrame()
        
        # 2. 計算 Bucket ID (例如 ST_草地_A_1200)
        course = str(race_info['course']).fillna('未知')
        track = str(race_info['track']).replace('"', '').replace(' 賽道', '').strip()
        distance = str(race_info['distance_m'])
        bucket_id = f"{course}_{track}_{distance}"
        
        # 3. 準備歷史資料字典 (若外部未提供，則即時計算)
        if df_hist is None:
            df_hist = self.calc.fetch_historical_data()
            df_hist = self.calc.calculate_base_score(df_hist)
            
        # 計算各因子字典 (這裡為了效能，實務上應該讀取 factor_scores 表，但我們暫時用即時算)
        jockey_df = self.calc.calculate_entity_factor(df_hist, 'jockey_name', ModelConfig.JOCKEY_DECAY, ModelConfig.JOCKEY_SMOOTH_C)
        trainer_df = self.calc.calculate_entity_factor(df_hist, 'trainer_name', ModelConfig.TRAINER_DECAY, ModelConfig.TRAINER_SMOOTH_C)
        
        df_hist['synergy_name'] = df_hist['jockey_name'].fillna('') + " & " + df_hist['trainer_name'].fillna('')
        synergy_df = self.calc.calculate_entity_factor(df_hist, 'synergy_name', ModelConfig.SYNERGY_DECAY, ModelConfig.SYNERGY_SMOOTH_C)
        
        draw_df = self.calc.calculate_draw_factor(df_hist)
        
        # 建立快速查找表 (針對當前 bucket)
        def get_zscore(factor_df, entity_col, entity_val):
            if factor_df is None or factor_df.empty: return 0.0
            # 檔位的欄位名在 calculate_draw_factor 中叫 draw_group
            match_col = 'draw_group' if 'draw_group' in factor_df.columns else entity_col
            subset = factor_df[(factor_df['bucket_id'] == bucket_id) & (factor_df[match_col] == entity_val)]
            return subset['z_score'].iloc[0] if not subset.empty else 0.0

        # 4. 依序為每匹馬匹配分數
        results = []
        for _, row in runners_df.iterrows():
            j_name = row['jockey_name']
            t_name = row['trainer_name']
            syn_name = f"{j_name} & {t_name}"
            draw_group = self.calc._assign_draw_group(row['draw'])
            
            # 歷史 Z-Score
            z_jockey = get_zscore(jockey_df, 'jockey_name', j_name)
            z_trainer = get_zscore(trainer_df, 'trainer_name', t_name)
            z_synergy = get_zscore(synergy_df, 'synergy_name', syn_name)
            z_draw = get_zscore(draw_df, 'draw_group', draw_group)
            
            # 官方 Speed Guide 分數轉換
            sg_form_score = self._map_form_rating(row['form_rating'])
            sg_energy = float(row['speed_energy']) if pd.notna(row['speed_energy']) else 0.0
            sg_delta = float(row['speed_energy_delta']) if pd.notna(row['speed_energy_delta']) else 0.0
            
            # 正規化 energy (假設平均在 100 左右)
            sg_energy_norm = (sg_energy - 100.0) / 10.0 if sg_energy > 0 else 0.0
            
            # 計算加權總分 (Total Score)
            total_score = (
                (z_jockey * ModelConfig.WEIGHT_JOCKEY) +
                (z_trainer * ModelConfig.WEIGHT_TRAINER) +
                (z_synergy * ModelConfig.WEIGHT_SYNERGY) +
                (z_draw * ModelConfig.WEIGHT_DRAW) +
                (sg_form_score * ModelConfig.WEIGHT_SG_FORM) +
                (sg_energy_norm * ModelConfig.WEIGHT_SG_ENERGY) +
                (sg_delta * ModelConfig.WEIGHT_SG_DELTA)
            )
            
            results.append({
                '馬號': row['horse_no'],
                '馬名': row['horse_name'],
                '檔位': row['draw'],
                '騎師': j_name,
                '練馬師': t_name,
                '騎師分': round(z_jockey, 2),
                '練馬師分': round(z_trainer, 2),
                '騎練分': round(z_synergy, 2),
                '檔位分': round(z_draw, 2),
                '狀態評級': row['form_rating'],
                '能量差值': sg_delta,
                '總預測分': round(total_score, 2)
            })
            
        df_result = pd.DataFrame(results)
        if not df_result.empty:
            # 依總分排序，給出預測排名
            df_result = df_result.sort_values('總預測分', ascending=False).reset_index(drop=True)
            df_result.insert(0, '預測排名', df_result.index + 1)
            
        return df_result, race_info
