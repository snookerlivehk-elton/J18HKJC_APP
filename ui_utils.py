import streamlit as st

def display_factor_details(df, selected_bucket, entity_col_name):
    """通用的獨立因子數據展示表格，確保顯示所有計算細節"""
    filtered = df[df['bucket_id'] == selected_bucket].copy()
    if filtered.empty:
        st.info("此分桶尚無數據")
        return
        
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
    
    st.dataframe(display_df, hide_index=True, use_container_width=True)
