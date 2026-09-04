import pandas as pd
import os
from config import ModelConfig
from factor_calculator import FactorCalculator
from bucket_utils import (
    make_bucket_id,
    make_band_bucket_id,
    normalize_person_name,
    synergy_name,
    is_valid_bucket,
    is_valid_band_bucket,
)

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

    def get_race_bucket(self, race_info) -> str:
        """細桶 Venue_Track_Distance（檔位等）。"""
        return make_bucket_id(
            race_id=race_info.get('race_id') if hasattr(race_info, 'get') else race_info['race_id'],
            course=race_info['course'],
            track=race_info['track'],
            distance_m=race_info['distance_m'],
        )

    def get_race_band_bucket(self, race_info) -> str:
        """粗桶 Venue_距離帶（騎師/練馬師/騎練/近績）。"""
        return make_band_bucket_id(
            race_id=race_info.get('race_id') if hasattr(race_info, 'get') else race_info['race_id'],
            course=race_info['course'],
            distance_m=race_info['distance_m'],
        )

    def _map_form_rating(self, rating: str) -> float:
        """將狀態評級 (如 A, B, C) 轉換為數值分數"""
        if pd.isna(rating):
            return 0.0
        r = str(rating).upper().strip()
        mapping = {
            'A+': 3.0, 'A': 2.0, 'A-': 1.0,
            'B+': 0.5, 'B': 0.0, 'B-': -0.5,
            'C': -1.0, 'D': -2.0,
        }
        return mapping.get(r, 0.0)

    def _build_score_lookup(self, scores_df: pd.DataFrame) -> dict:
        """(factor_type, bucket_id, entity_name) -> z_score"""
        lookup = {}
        if scores_df is None or scores_df.empty:
            return lookup
        for _, row in scores_df.iterrows():
            key = (
                str(row['factor_type']),
                str(row['bucket_id']),
                str(row['entity_name']),
            )
            lookup[key] = float(row['z_score'])
        return lookup

    def _lookup_z(self, lookup: dict, factor_type: str, bucket_id: str, entity_name: str):
        """回傳 (z_score, hit: bool)。查不到明確標 miss，不靜默造假。"""
        key = (factor_type, bucket_id, entity_name)
        if key in lookup:
            return lookup[key], True
        return 0.0, False

    def predict_race(self, race_id: str, df_hist: pd.DataFrame = None) -> tuple:
        """
        執行單場賽事推論（查表模式）：
        騎練/近績用距離帶粗桶；檔位用細桶；可選 HORSE Z。
        """
        races_df = self.get_upcoming_races()
        if races_df.empty:
            return pd.DataFrame(), None

        matched = races_df[races_df['race_id'] == race_id]
        if matched.empty:
            return pd.DataFrame(), None

        race_info = matched.iloc[0]
        runners_df = self.get_race_runners(race_id)
        if runners_df.empty:
            return pd.DataFrame(), race_info

        fine_bucket = self.get_race_bucket(race_info)
        band_bucket = self.get_race_band_bucket(race_info)
        scores_df = self.calc.load_factor_scores(
            factor_types=['JOCKEY', 'TRAINER', 'SYNERGY', 'DRAW', 'HORSE']
        )
        lookup = self._build_score_lookup(scores_df)

        results = []
        hit_counts = {
            'JOCKEY': 0, 'TRAINER': 0, 'SYNERGY': 0, 'DRAW': 0, 'HORSE': 0,
        }
        total_lookups = 0

        for _, row in runners_df.iterrows():
            j_name = normalize_person_name(row['jockey_name'])
            t_name = normalize_person_name(row['trainer_name'])
            h_name = normalize_person_name(row['horse_name'])
            syn_name = synergy_name(j_name, t_name)
            draw_group = self.calc._assign_draw_group(row['draw'])

            z_jockey, hit_j = self._lookup_z(lookup, 'JOCKEY', band_bucket, j_name)
            z_trainer, hit_t = self._lookup_z(lookup, 'TRAINER', band_bucket, t_name)
            z_synergy, hit_s = self._lookup_z(lookup, 'SYNERGY', band_bucket, syn_name)
            z_draw, hit_d = self._lookup_z(lookup, 'DRAW', fine_bucket, draw_group)
            z_horse, hit_h = self._lookup_z(lookup, 'HORSE', band_bucket, h_name)

            for ft, hit in (
                ('JOCKEY', hit_j), ('TRAINER', hit_t),
                ('SYNERGY', hit_s), ('DRAW', hit_d), ('HORSE', hit_h),
            ):
                total_lookups += 1
                if hit:
                    hit_counts[ft] += 1

            sg_form_score = self._map_form_rating(row.get('form_rating'))
            sg_energy = float(row['speed_energy']) if pd.notna(row.get('speed_energy')) else 0.0
            sg_delta = float(row['speed_energy_delta']) if pd.notna(row.get('speed_energy_delta')) else 0.0
            sg_energy_norm = (sg_energy - 100.0) / 10.0 if sg_energy > 0 else 0.0

            total_score = (
                (z_jockey * ModelConfig.WEIGHT_JOCKEY) +
                (z_trainer * ModelConfig.WEIGHT_TRAINER) +
                (z_synergy * ModelConfig.WEIGHT_SYNERGY) +
                (z_draw * ModelConfig.WEIGHT_DRAW) +
                (z_horse * ModelConfig.WEIGHT_RECENT_FORM) +
                (sg_form_score * ModelConfig.WEIGHT_SG_FORM) +
                (sg_energy_norm * ModelConfig.WEIGHT_SG_ENERGY) +
                (sg_delta * ModelConfig.WEIGHT_SG_DELTA)
            )

            hit_n = int(hit_j) + int(hit_t) + int(hit_s) + int(hit_d) + int(hit_h)
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
                '近績分': round(z_horse, 2),
                '命中': f"{hit_n}/5",
                '狀態評級': row.get('form_rating'),
                '能量差值': sg_delta,
                '總預測分': round(total_score, 2),
            })

        df_result = pd.DataFrame(results)
        if not df_result.empty:
            df_result = df_result.sort_values('總預測分', ascending=False).reset_index(drop=True)
            df_result.insert(0, '預測排名', df_result.index + 1)

        meta = {
            'bucket_id': fine_bucket,
            'band_bucket_id': band_bucket,
            'bucket_valid': is_valid_bucket(fine_bucket),
            'band_bucket_valid': is_valid_band_bucket(band_bucket),
            'factor_rows': 0 if scores_df is None else len(scores_df),
            'match_rate': (sum(hit_counts.values()) / total_lookups) if total_lookups else 0.0,
            'hit_counts': hit_counts,
        }

        return df_result, race_info, meta
