import streamlit as st
import pandas as pd
from inference_engine import InferenceEngine
from bucket_utils import make_bucket_id, normalize_person_name, is_valid_bucket

@st.cache_data(ttl=60)
def get_upcoming_races_list():
    engine = InferenceEngine()
    races_df = engine.get_upcoming_races()
    if races_df.empty:
        return []

    options = [("None", "--- 純查詢歷史 Bucket (不對應明日排位) ---")]
    for _, row in races_df.iterrows():
        date = row['racing_date']
        course = row['course']
        num = row['race_num']
        dist = row['distance_m']
        track = row['track']
        cls = row['class']
        label = f"明日第 {num} 場 | {date} {course} {track} {dist}米 ({cls})"
        options.append((row['race_id'], label))
    return options

def get_runners_for_race(race_id):
    engine = InferenceEngine()
    df = engine.get_race_runners(race_id)
    if not df.empty and 'jockey_name' in df.columns:
        df = df.copy()
        df['jockey_name'] = df['jockey_name'].apply(normalize_person_name)
        df['trainer_name'] = df['trainer_name'].apply(normalize_person_name)
    return df

def get_bucket_for_race(race_id):
    engine = InferenceEngine()
    races_df = engine.get_upcoming_races()
    if races_df.empty:
        return None
    matched = races_df[races_df['race_id'] == race_id]
    if matched.empty:
        return None
    race_info = matched.iloc[0]
    bucket = make_bucket_id(
        race_id=race_info['race_id'],
        course=race_info['course'],
        track=race_info['track'],
        distance_m=race_info['distance_m'],
    )
    return bucket if is_valid_bucket(bucket) else bucket

def display_factor_details(df, selected_bucket, entity_col_name, filter_entities=None):
    """通用的獨立因子數據展示表格"""
    if filter_entities is not None:
        filter_entities = [normalize_person_name(x) for x in filter_entities]

    filtered = df[df['bucket_id'] == selected_bucket].copy()
    if filtered.empty:
        st.info(f"此分桶尚無數據：`{selected_bucket}`")
        return

    if filter_entities is not None:
        filtered = filtered[filtered['entity_name'].isin(filter_entities)]
        if filtered.empty:
            st.info("此分桶中，沒有任何明日參賽實體的歷史數據。")
            return
    else:
        search_query = st.text_input(f"🔍 搜尋特定{entity_col_name}", "")
        if search_query:
            filtered = filtered[filtered['entity_name'].str.contains(search_query, na=False)]

    cols_to_show = [
        'entity_name', 'actual_runs', 'wins', 'places',
        'weighted_runs', 'weighted_score', 'adjusted_score', 'z_score'
    ]
    existing_cols = [c for c in cols_to_show if c in filtered.columns]

    display_df = filtered[existing_cols].copy()
    display_df = display_df.sort_values('z_score', ascending=False)

    if 'weighted_score' in display_df:
        display_df['weighted_score'] = display_df['weighted_score'].map('{:.3f}'.format)
    if 'weighted_runs' in display_df:
        display_df['weighted_runs'] = display_df['weighted_runs'].map('{:.2f}'.format)
    if 'adjusted_score' in display_df:
        display_df['adjusted_score'] = display_df['adjusted_score'].map('{:.3f}'.format)
    if 'z_score' in display_df:
        display_df['z_score'] = display_df['z_score'].map('{:.2f}'.format)

    rename_dict = {
        'entity_name': entity_col_name,
        'actual_runs': '總出賽',
        'wins': '勝出',
        'places': '入圍',
        'weighted_runs': '加權出賽數',
        'weighted_score': '加權總分',
        'adjusted_score': '平滑後得分',
        'z_score': 'Z-Score'
    }
    display_df = display_df.rename(columns=rename_dict)
    st.dataframe(display_df, hide_index=True, use_container_width=True)
