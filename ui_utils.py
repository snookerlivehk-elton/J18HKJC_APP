import streamlit as st
import pandas as pd
from inference_engine import InferenceEngine

@st.cache_data(ttl=60)
def get_upcoming_races_list():
    engine = InferenceEngine()
    races_df = engine.get_upcoming_races()
    if races_df.empty: return []
    
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
    return engine.get_race_runners(race_id)

def get_bucket_for_race(race_id):
    engine = InferenceEngine()
    races_df = engine.get_upcoming_races()
    if races_df.empty: return None
    race_info = races_df[races_df['race_id'] == race_id].iloc[0]
    course = str(race_info['course']).fillna('未知')
    track = str(race_info['track']).replace('"', '').replace(' 賽道', '').strip()
    distance = str(race_info['distance_m'])
    return f"{course}_{track}_{distance}"

def display_factor_details(df, selected_bucket, entity_col_name, filter_entities=None):
    """通用的獨立因子數據展示表格，確保顯示所有計算細節
    filter_entities: 如果提供 list，則只顯示這些實體的數據 (用於排位對應)
    """
    filtered = df[df['bucket_id'] == selected_bucket].copy()
    if filtered.empty:
        st.info("此分桶尚無數據")
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
        
    # 決定要顯示的欄位 (確保就算舊版 cache 缺少某些欄位也不會崩潰)
    cols_to_show = ['entity_name', 'actual_runs', 'wins', 'places', 'weighted_runs', 'weighted_score', 'adjusted_score', 'z_score']
    existing_cols = [c for c in cols_to_show if c in filtered.columns]
    
    display_df = filtered[existing_cols].copy()
    display_df = display_df.sort_values('z_score', ascending=False)
    
    # 格式化數值
    if 'weighted_score' in display_df: display_df['weighted_score'] = display_df['weighted_score'].map('{:.3f}'.format)
    if 'weighted_runs' in display_df: display_df['weighted_runs'] = display_df['weighted_runs'].map('{:.2f}'.format)
    if 'adjusted_score' in display_df: display_df['adjusted_score'] = display_df['adjusted_score'].map('{:.3f}'.format)
    if 'z_score' in display_df: display_df['z_score'] = display_df['z_score'].map('{:.2f}'.format)
    
    # 中文化欄位
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
    
    # 高亮顯示
    st.dataframe(display_df, hide_index=True, use_container_width=True)
