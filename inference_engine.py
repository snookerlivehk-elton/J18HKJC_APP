import pandas as pd
import os
import re
import json
import numpy as np
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

from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH, resolve_database_url
from score_compose import (
    compose_total,
    coverage_mode,
    hit_coverage,
    interference_mode,
    legacy_total_from_parts,
    make_stakeholder,
    miss_coverage,
    pick_score_for_ranking,
)
if USE_SQLITE:
    DATABASE_URL_SYNC = f"sqlite:///{SQLITE_DB_PATH}"
else:
    DATABASE_URL_SYNC = resolve_database_url()


def scores_to_win_probs(
    scores,
    temperature: float = None,
    *,
    within_race_z: bool = None,
    method: str = None,
) -> np.ndarray:
    """
    同場總分 → 勝率（加總 = 1，非負）。

    預設 method=share（ModelConfig.WIN_PROB_METHOD）：
      d_i = s_i − min(s)，P_i = d_i / Σd（分差比率瓜分 100%）

    method=softmax（舊）：
      可選場內 z → softmax(/T)
    """
    from score_share import scores_to_share_probs

    mode = (method or getattr(ModelConfig, "WIN_PROB_METHOD", "share") or "share").lower()
    if mode == "share":
        return scores_to_share_probs(scores)

    arr = np.asarray(scores, dtype=float)
    if arr.size == 0:
        return arr
    use_z = (
        ModelConfig.SOFTMAX_WITHIN_RACE_Z
        if within_race_z is None
        else bool(within_race_z)
    )
    if use_z and arr.size >= 2:
        sd = float(np.std(arr, ddof=0))
        if sd > 1e-9:
            arr = (arr - float(np.mean(arr))) / sd
        else:
            arr = np.zeros_like(arr)
    t = float(temperature if temperature is not None else ModelConfig.SOFTMAX_TEMPERATURE)
    t = max(t, 1e-6)
    x = arr / t
    x = x - np.max(x)
    ex = np.exp(x)
    return ex / ex.sum()


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
            # 參數化避免注入；評分欄若舊庫沒有則回退
            queries = [
                """
                SELECT 
                    r.horse_no, r.horse_name, r.draw, r.jockey_name, r.trainer_name, 
                    r.handicap_weight, r.horse_weight, r.gear, r.rating, r.rating_delta,
                    s.form_rating, s.speed_energy, s.speed_energy_delta
                FROM upcoming_runners r
                LEFT JOIN upcoming_speedguide s ON r.runner_id = s.runner_id
                WHERE r.race_id = %(race_id)s
                ORDER BY r.horse_no ASC
                """,
                """
                SELECT 
                    r.horse_no, r.horse_name, r.draw, r.jockey_name, r.trainer_name, 
                    r.handicap_weight, r.horse_weight, r.gear,
                    s.form_rating, s.speed_energy, s.speed_energy_delta
                FROM upcoming_runners r
                LEFT JOIN upcoming_speedguide s ON r.runner_id = s.runner_id
                WHERE r.race_id = %(race_id)s
                ORDER BY r.horse_no ASC
                """,
            ]
            last_err = None
            for query in queries:
                try:
                    return pd.read_sql(query, engine, params={"race_id": race_id})
                except Exception as e:
                    last_err = e
                    continue
            print(f"Error fetching runners for {race_id}: {last_err}")
            return pd.DataFrame()
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
        """
        狀態評級 → 分數（與官方 UI 圖示一致）：
          0 → thumb_down（倒轉拇指，狀態差）
          1 → formGuide_1up
          2 → formGuide_2up
          3 → formGuide_3up
        舊式字母評級仍相容。
        """
        if pd.isna(rating):
            return 0.0
        r = str(rating).upper().strip()
        if re.fullmatch(r"-?\d+", r):
            n = int(r)
            # 0=倒轉拇指（差）；1–3=向上拇指數量（愈多愈佳）
            return {0: -1.5, 1: 0.0, 2: 1.0, 3: 2.0}.get(n, float(n) - 1.0)
        mapping = {
            'A+': 3.0, 'A': 2.0, 'A-': 1.0,
            'B+': 0.5, 'B': 0.0, 'B-': -0.5,
            'C': -1.0, 'D': -2.0,
        }
        return mapping.get(r, 0.0)

    @staticmethod
    def fitness_label(rating) -> str:
        """UI 顯示用：把 Fitness 代碼翻成中文。"""
        if pd.isna(rating) or str(rating).strip() == "":
            return ""
        r = str(rating).strip()
        return {
            "0": "👎 倒轉拇指",
            "1": "👍×1",
            "2": "👍×2",
            "3": "👍×3",
        }.get(r, r)

    @staticmethod
    def _within_field_z(series: pd.Series) -> pd.Series:
        """同場 Z-Score；有效值 < 2 則全 0（不假裝官方分）。"""
        s = pd.to_numeric(series, errors='coerce')
        valid = s.dropna()
        if len(valid) < 2:
            return pd.Series(0.0, index=series.index)
        sd = float(valid.std(ddof=0))
        if sd < 1e-9:
            return pd.Series(0.0, index=series.index)
        mu = float(valid.mean())
        return (s - mu) / sd

    def _build_score_lookup(self, scores_df: pd.DataFrame) -> dict:
        """(factor_type, bucket_id, entity_name) -> {z_score, coverage?}"""
        lookup = {}
        if scores_df is None or scores_df.empty:
            return lookup
        has_cov = "coverage" in scores_df.columns
        for _, row in scores_df.iterrows():
            key = (
                str(row['factor_type']),
                str(row['bucket_id']),
                str(row['entity_name']),
            )
            cov = None
            if has_cov and pd.notna(row.get("coverage")):
                try:
                    cov = float(row["coverage"])
                except (TypeError, ValueError):
                    cov = None
            lookup[key] = {"z": float(row['z_score']), "coverage": cov}
        return lookup

    def _lookup_z(self, lookup: dict, factor_type: str, bucket_id: str, entity_name: str):
        """回傳 (z_score, hit: bool, coverage: float)。查不到明確標 miss。"""
        key = (factor_type, bucket_id, entity_name)
        if key in lookup:
            entry = lookup[key]
            if isinstance(entry, dict):
                z = float(entry.get("z", 0.0))
                cov = entry.get("coverage")
                if cov is None:
                    cov = hit_coverage()
                return z, True, float(cov)
            return float(entry), True, hit_coverage()
        return 0.0, False, miss_coverage()

    def predict_race(self, race_id: str, df_hist: pd.DataFrame = None) -> tuple:
        """
        執行單場賽事推論（查表模式）：
        騎練/近績用距離帶粗桶；檔位用細桶；coverage 持份者合成總分。
        """
        races_df = self.get_upcoming_races()
        if races_df.empty:
            return pd.DataFrame(), None, {}

        matched = races_df[races_df['race_id'] == race_id]
        if matched.empty:
            return pd.DataFrame(), None, {}

        race_info = matched.iloc[0]
        runners_df = self.get_race_runners(race_id)
        if runners_df.empty:
            return pd.DataFrame(), race_info, {}

        fine_bucket = self.get_race_bucket(race_info)
        band_bucket = self.get_race_band_bucket(race_info)
        factor_types = [
            'JOCKEY', 'TRAINER', 'SYNERGY', 'DRAW', 'HORSE', 'PACE', 'SPEED',
            'INTERFERENCE_FORM', 'INTERFERENCE_SPEED',
        ]
        scores_df = self.calc.load_factor_scores(factor_types=factor_types)
        lookup = self._build_score_lookup(scores_df)
        mode = coverage_mode()
        iff_mode = interference_mode()
        use_i = iff_mode == "stakeholder"

        results = []
        hit_counts = {
            'JOCKEY': 0, 'TRAINER': 0, 'SYNERGY': 0, 'DRAW': 0,
            'HORSE': 0, 'PACE': 0, 'SPEED': 0,
        }
        total_lookups = 0
        provisional_reasons_race = []

        # Speed Guide：能量同場 Z；差值本身已相對 ER，直接入分（正＝官方看好）
        has_sg_energy_col = 'speed_energy' in runners_df.columns
        sg_energy_z = self._within_field_z(
            runners_df['speed_energy'] if has_sg_energy_col
            else pd.Series(dtype=float)
        )
        sg_present_n = 0
        if has_sg_energy_col:
            sg_present_n = int(pd.to_numeric(runners_df['speed_energy'], errors='coerce').notna().sum())
        if sg_present_n == 0:
            provisional_reasons_race.append("sg_missing")

        for idx, row in runners_df.iterrows():
            j_name = normalize_person_name(row['jockey_name'])
            t_name = normalize_person_name(row['trainer_name'])
            h_name = normalize_person_name(row['horse_name'])
            syn_name = synergy_name(j_name, t_name)
            draw_group = self.calc._assign_draw_group(row['draw'])

            z_jockey, hit_j, c_j = self._lookup_z(lookup, 'JOCKEY', band_bucket, j_name)
            z_trainer, hit_t, c_t = self._lookup_z(lookup, 'TRAINER', band_bucket, t_name)
            z_synergy, hit_s, c_s = self._lookup_z(lookup, 'SYNERGY', band_bucket, syn_name)
            z_draw, hit_d, c_d = self._lookup_z(lookup, 'DRAW', fine_bucket, draw_group)
            z_horse, hit_h, c_h = self._lookup_z(lookup, 'HORSE', band_bucket, h_name)
            z_pace, hit_p, c_p = self._lookup_z(lookup, 'PACE', 'GLOBAL', h_name)
            z_speed, hit_sp, c_sp = self._lookup_z(lookup, 'SPEED', 'GLOBAL', h_name)

            for ft, hit in (
                ('JOCKEY', hit_j), ('TRAINER', hit_t),
                ('SYNERGY', hit_s), ('DRAW', hit_d),
                ('HORSE', hit_h), ('PACE', hit_p), ('SPEED', hit_sp),
            ):
                total_lookups += 1
                if hit:
                    hit_counts[ft] += 1

            # SG 子項：有欄位值 → present；缺 → coverage=0
            form_raw = row.get('form_rating')
            sg_form_present = pd.notna(form_raw) and str(form_raw).strip() != ""
            sg_form_score = self._map_form_rating(form_raw) if sg_form_present else 0.0
            sg_energy = float(row['speed_energy']) if pd.notna(row.get('speed_energy')) else None
            sg_energy_present = sg_energy is not None
            sg_delta_present = pd.notna(row.get('speed_energy_delta'))
            sg_delta = float(row['speed_energy_delta']) if sg_delta_present else 0.0
            ez = sg_energy_z.get(idx, 0.0) if sg_energy_present else 0.0
            sg_energy_norm = 0.0 if (not sg_energy_present or pd.isna(ez)) else float(ez)

            # 干擾持份者
            i_form, hit_if, c_if = self._lookup_z(lookup, 'INTERFERENCE_FORM', 'GLOBAL', h_name)
            i_speed, hit_is, c_is = self._lookup_z(lookup, 'INTERFERENCE_SPEED', 'GLOBAL', h_name)
            if use_i:
                # 無列＝DELAY：I=0、coverage 低（miss_coverage）；有列則用落庫 coverage
                if not hit_if:
                    i_form, c_if = 0.0, miss_coverage()
                if not hit_is:
                    i_speed, c_is = 0.0, miss_coverage()
                # 有列但 I≈0 且 coverage 高＝ABSENT_TRUE（已反映在落庫 coverage）
            else:
                i_form, i_speed, c_if, c_is = 0.0, 0.0, 0.0, 0.0
                hit_if = hit_is = False

            stakeholders = [
                make_stakeholder("JOCKEY", z_jockey, present=hit_j, coverage=c_j if hit_j else miss_coverage(), base_weight=ModelConfig.WEIGHT_JOCKEY),
                make_stakeholder("TRAINER", z_trainer, present=hit_t, coverage=c_t if hit_t else miss_coverage(), base_weight=ModelConfig.WEIGHT_TRAINER),
                make_stakeholder("SYNERGY", z_synergy, present=hit_s, coverage=c_s if hit_s else miss_coverage(), base_weight=ModelConfig.WEIGHT_SYNERGY),
                make_stakeholder("DRAW", z_draw, present=hit_d, coverage=c_d if hit_d else miss_coverage(), base_weight=ModelConfig.WEIGHT_DRAW),
                make_stakeholder("HORSE", z_horse, present=hit_h, coverage=c_h if hit_h else miss_coverage(), base_weight=ModelConfig.WEIGHT_RECENT_FORM),
                make_stakeholder("PACE", z_pace, present=hit_p, coverage=c_p if hit_p else miss_coverage(), base_weight=ModelConfig.WEIGHT_PACE),
                make_stakeholder("SPEED", z_speed, present=hit_sp, coverage=c_sp if hit_sp else miss_coverage(), base_weight=ModelConfig.WEIGHT_SPEED_FIGURE),
                make_stakeholder("SG_FORM", sg_form_score, present=sg_form_present, coverage=1.0 if sg_form_present else 0.0, base_weight=ModelConfig.WEIGHT_SG_FORM),
                make_stakeholder("SG_ENERGY", sg_energy_norm, present=sg_energy_present, coverage=1.0 if sg_energy_present else 0.0, base_weight=ModelConfig.WEIGHT_SG_ENERGY),
                make_stakeholder("SG_DELTA", sg_delta, present=sg_delta_present, coverage=1.0 if sg_delta_present else 0.0, base_weight=ModelConfig.WEIGHT_SG_DELTA),
            ]
            if use_i:
                stakeholders.extend([
                    make_stakeholder(
                        "INTERFERENCE_FORM", i_form,
                        present=True,  # DELAY 亦 present 語意上「通道開啟」但 value=0；用 coverage 懲罰
                        coverage=c_if,
                        base_weight=float(getattr(ModelConfig, "WEIGHT_INTERFERENCE_FORM", 0.4)),
                    ),
                    make_stakeholder(
                        "INTERFERENCE_SPEED", i_speed,
                        present=True,
                        coverage=c_is,
                        base_weight=float(getattr(ModelConfig, "WEIGHT_INTERFERENCE_SPEED", 0.3)),
                    ),
                ])

            cov_total, model_cov, breakdown = compose_total(stakeholders)

            sg_contrib_legacy = (
                (sg_form_score * ModelConfig.WEIGHT_SG_FORM) +
                (sg_energy_norm * ModelConfig.WEIGHT_SG_ENERGY) +
                (sg_delta * ModelConfig.WEIGHT_SG_DELTA)
            )
            # 顯示用 SG 貢獻：coverage 模式下用 effective 加總
            sg_eff = (
                breakdown.get("SG_FORM", {}).get("effective", 0.0)
                + breakdown.get("SG_ENERGY", {}).get("effective", 0.0)
                + breakdown.get("SG_DELTA", {}).get("effective", 0.0)
            )

            legacy_score = legacy_total_from_parts(
                z_jockey=z_jockey, z_trainer=z_trainer, z_synergy=z_synergy,
                z_draw=z_draw, z_horse=z_horse, z_pace=z_pace, z_speed=z_speed,
                sg_form=sg_form_score, sg_energy=sg_energy_norm, sg_delta=sg_delta,
                i_form=i_form if use_i else 0.0,
                i_speed=i_speed if use_i else 0.0,
                include_interference=False,  # legacy 路徑不含獨立 I（舊行為）
            )

            total_score = pick_score_for_ranking(
                legacy_score=legacy_score,
                coverage_score=cov_total,
                mode=mode,
            )

            hit_n = (
                int(hit_j) + int(hit_t) + int(hit_s) + int(hit_d)
                + int(hit_h) + int(hit_p) + int(hit_sp)
            )
            row_reasons = list(provisional_reasons_race)
            if use_i and (c_if < 0.5 or c_is < 0.5):
                if "nlp_pending" not in row_reasons:
                    row_reasons.append("nlp_pending")
            if hit_n < 5:
                row_reasons.append("low_match")

            import json as _json
            results.append({
                '馬號': row['horse_no'],
                '馬名': row['horse_name'],
                '檔位': row['draw'],
                '騎師': j_name,
                '練馬師': t_name,
                '負磅': row.get('handicap_weight'),
                '體重': row.get('horse_weight'),
                '評分': row.get('rating'),
                '評分升降': row.get('rating_delta'),
                '配備': row.get('gear'),
                '騎師分': round(z_jockey, 2),
                '練馬師分': round(z_trainer, 2),
                '騎練分': round(z_synergy, 2),
                '檔位分': round(z_draw, 2),
                '近績分': round(z_horse, 2),
                '步速分': round(z_pace, 2),
                '速度分': round(z_speed, 2),
                '干擾近績': round(i_form, 2) if use_i else None,
                '干擾速度': round(i_speed, 2) if use_i else None,
                '命中': f"{hit_n}/7",
                '狀態評級': self.fitness_label(row.get('form_rating')) or row.get('form_rating'),
                '速勢能量': sg_energy,
                '能量差值': sg_delta if sg_delta_present else None,
                'SG貢獻': round(sg_eff if mode == "on" else sg_contrib_legacy, 2),
                '總預測分': round(total_score, 2),
                '總預測分_legacy': round(legacy_score, 2),
                '總預測分_coverage': round(cov_total, 2),
                '模型覆蓋': round(model_cov, 4),
                'coverage_json': json.dumps(breakdown, ensure_ascii=False),
                'provisional_reasons': ",".join(row_reasons),
            })

        df_result = pd.DataFrame(results)
        if not df_result.empty:
            df_result = df_result.sort_values('總預測分', ascending=False).reset_index(drop=True)
            df_result.insert(0, '預測排名', df_result.index + 1)
            probs = scores_to_win_probs(df_result['總預測分'].to_numpy())
            df_result['模型勝率'] = np.round(probs, 4)
            df_result['模型勝率%'] = np.round(probs * 100.0, 2)

            # 各因子：場內分差比率瓜分 100%（非負顯示；排序與原始 Z 同場一致）
            from score_share import scores_to_share_probs
            factor_share_cols = [
                '騎師分', '練馬師分', '騎練分', '檔位分',
                '近績分', '步速分', '速度分', 'SG貢獻',
            ]
            for col in factor_share_cols:
                if col not in df_result.columns:
                    continue
                sh = scores_to_share_probs(df_result[col].to_numpy(dtype=float))
                df_result[col] = np.round(sh * 100.0, 2)

        avg_cov = float(df_result['模型覆蓋'].mean()) if not df_result.empty and '模型覆蓋' in df_result.columns else 0.0
        provisional = bool(provisional_reasons_race) or (
            not df_result.empty and df_result['provisional_reasons'].astype(str).str.len().gt(0).any()
        )
        meta = {
            'bucket_id': fine_bucket,
            'band_bucket_id': band_bucket,
            'bucket_valid': is_valid_bucket(fine_bucket),
            'band_bucket_valid': is_valid_band_bucket(band_bucket),
            'factor_rows': 0 if scores_df is None else len(scores_df),
            'match_rate': (sum(hit_counts.values()) / total_lookups) if total_lookups else 0.0,
            'hit_counts': hit_counts,
            'win_prob_method': getattr(ModelConfig, 'WIN_PROB_METHOD', 'share'),
            'softmax_temperature': ModelConfig.SOFTMAX_TEMPERATURE,
            'softmax_within_race_z': ModelConfig.SOFTMAX_WITHIN_RACE_Z,
            'win_prob_sum': float(df_result['模型勝率'].sum()) if not df_result.empty else 0.0,
            'coverage_mode': mode,
            'interference_mode': iff_mode,
            'avg_model_coverage': avg_cov,
            'provisional': provisional,
            'provisional_reasons': list(dict.fromkeys(provisional_reasons_race)),
            **self._pace_scenario_meta(scores_df, runners_df),
        }

        return df_result, race_info, meta

    def _pace_board_from_scores(self, scores_df: pd.DataFrame) -> pd.DataFrame:
        """從 factor_scores 抽出 PACE 表（含 early_speed_z／跑法，供預計步速）。"""
        if scores_df is None or scores_df.empty:
            return pd.DataFrame()
        pace = scores_df[scores_df['factor_type'] == 'PACE'].copy()
        if pace.empty:
            return pd.DataFrame()
        return pace

    def _pace_scenario_meta(self, scores_df: pd.DataFrame, runners_df: pd.DataFrame) -> dict:
        """預計步速（偏慢／中性／偏快）；缺早段 Z 時標示需重算。"""
        empty = {
            'pace_scenario': '未知',
            'pace_heat': None,
            'pace_contenders': None,
        }
        if runners_df is None or runners_df.empty or 'horse_name' not in runners_df.columns:
            return empty
        pace = self._pace_board_from_scores(scores_df)
        if pace.empty:
            return empty
        if 'early_speed_z' not in pace.columns or pace['early_speed_z'].isna().all():
            return {
                'pace_scenario': '未知',
                'pace_heat': None,
                'pace_contenders': None,
                'pace_scenario_note': '請重算步速因子以寫入早段速度',
            }
        proj = self.calc.project_race_pace(pace, runners_df['horse_name'].tolist())
        return {
            'pace_scenario': proj.get('scenario') or '未知',
            'pace_heat': proj.get('heat'),
            'pace_contenders': proj.get('n_contenders'),
            'pace_fast_z': proj.get('fast_z'),
        }

    def export_kelly_payload(self, race_id: str) -> dict:
        """
        給外部凱利／賠率系統的穩定 JSON 結構。
        使用模型勝率（非原始總分）；賠率與注碼由對方系統填入。
        """
        df, race_info, meta = self.predict_race(race_id)
        info = race_info.to_dict() if hasattr(race_info, 'to_dict') else (dict(race_info) if race_info is not None else {})
        runners = []
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                runners.append({
                    'horse_no': int(row['馬號']) if pd.notna(row['馬號']) else None,
                    'horse_name': row['馬名'],
                    'draw': int(row['檔位']) if pd.notna(row.get('檔位')) else None,
                    'jockey': row.get('騎師'),
                    'trainer': row.get('練馬師'),
                    'total_score': float(row['總預測分']),
                    'model_win_prob': float(row['模型勝率']),
                    'rank': int(row['預測排名']),
                    'factors': {
                        'jockey': float(row['騎師分']),
                        'trainer': float(row['練馬師分']),
                        'synergy': float(row['騎練分']),
                        'draw': float(row['檔位分']),
                        'form': float(row['近績分']),
                        'pace': float(row['步速分']),
                        'speed': float(row['速度分']),
                        'speed_guide': float(row['SG貢獻']),
                    },
                })
        return {
            'race_id': race_id,
            'race': {
                'racing_date': str(info.get('racing_date', '')),
                'course': info.get('course'),
                'race_num': info.get('race_num'),
                'distance_m': info.get('distance_m'),
                'track': info.get('track'),
                'class': info.get('class'),
                'expected_pace': meta.get('pace_scenario'),
            },
            'meta': {
                'bucket_id': meta.get('bucket_id'),
                'band_bucket_id': meta.get('band_bucket_id'),
                'match_rate': meta.get('match_rate'),
                'softmax_temperature': meta.get('softmax_temperature'),
                'softmax_within_race_z': meta.get('softmax_within_race_z'),
                'win_prob_sum': meta.get('win_prob_sum'),
            },
            'runners': runners,
            'note': (
                'model_win_prob sums to ~1 within the race. '
                'Probs = softmax(within-race-z(total_score) / T) when within_race_z is on. '
                'Kelly: f*=(b*p-q)/b with decimal odds o, b=o-1, q=1-p. '
                'Do not shift total_score to be positive for probabilities.'
            ),
        }
