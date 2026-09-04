"""
各因子頁共用的 UI 工具：排位選擇、Bucket 顯示、排位列 × 因子匹配表。
"""
import streamlit as st
import pandas as pd
from inference_engine import InferenceEngine
from factor_calculator import FactorCalculator
from bucket_utils import (
    make_bucket_id,
    normalize_person_name,
    synergy_name,
    horse_jockey_name,
    is_valid_bucket,
    GLOBAL_BUCKET,
)


@st.cache_data(ttl=60)
def get_upcoming_races_list():
    engine = InferenceEngine()
    races_df = engine.get_upcoming_races()
    if races_df.empty:
        return []

    options = [("None", "--- 純查詢歷史 Bucket（不對應排位） ---")]
    for _, row in races_df.iterrows():
        date = row['racing_date']
        course = row['course']
        num = row['race_num']
        dist = row['distance_m']
        track = row['track']
        cls = row['class']
        bucket = make_bucket_id(
            race_id=row['race_id'],
            course=course,
            track=track,
            distance_m=dist,
        )
        valid = "✓" if is_valid_bucket(bucket) else "✗"
        label = f"第 {num} 場 | {date} {course} {track or '-'} {dist or '?'}米 ({cls or '-'}) [{valid} {bucket}]"
        options.append((row['race_id'], label))
    return options


def get_runners_for_race(race_id):
    engine = InferenceEngine()
    df = engine.get_race_runners(race_id)
    if df.empty:
        return df
    df = df.copy()
    if 'jockey_name' in df.columns:
        df['jockey_name'] = df['jockey_name'].apply(normalize_person_name)
    if 'trainer_name' in df.columns:
        df['trainer_name'] = df['trainer_name'].apply(normalize_person_name)
    if 'horse_name' in df.columns:
        df['horse_name'] = df['horse_name'].apply(normalize_person_name)
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
    return make_bucket_id(
        race_id=race_info['race_id'],
        course=race_info['course'],
        track=race_info['track'],
        distance_m=race_info['distance_m'],
    )


def ensure_history_loaded() -> bool:
    """各因子頁入口：有 raw_df，或資料庫已有 factor_scores 即可進入。"""
    if 'raw_df' in st.session_state and not st.session_state['raw_df'].empty:
        return True
    calc = FactorCalculator()
    scores = calc.load_factor_scores()
    if not scores.empty:
        st.info("未載入歷史 DataFrame，但資料庫已有 factor_scores，可直接做排位匹配。調參重算仍需先回主頁載入歷史。")
        return True
    st.warning("請先至主頁「載入歷史賽果」或「重算並寫入 factor_scores」。")
    return False


def load_factor_from_db_or_session(session_key: str, factor_type: str) -> pd.DataFrame:
    """優先用 session 計算結果；沒有則嘗試從 factor_scores 讀取。"""
    if session_key in st.session_state and isinstance(st.session_state[session_key], pd.DataFrame):
        df = st.session_state[session_key]
        if not df.empty:
            return df
    calc = FactorCalculator()
    df = calc.load_factor_scores(factor_types=[factor_type])
    if not df.empty:
        st.caption(f"已從資料庫載入 `{factor_type}`（{len(df)} 筆）。若要調參重算，請按本頁計算按鈕。")
    return df


def display_factor_details(df, selected_bucket, entity_col_name, filter_entities=None, key=None):
    """歷史 bucket 瀏覽表（診斷用）。"""
    if df is None or df.empty:
        st.info("尚無因子數據")
        return

    filtered = df[df['bucket_id'] == selected_bucket].copy()
    if filtered.empty:
        st.info(f"此分桶尚無數據：`{selected_bucket}`")
        return

    if filter_entities is not None:
        filtered = filtered[filtered['entity_name'].isin(filter_entities)]
        if filtered.empty:
            st.info("此分桶中，沒有匹配到排位實體。")
            return
    else:
        search_query = st.text_input(f"🔍 搜尋特定{entity_col_name}", "", key=key)
        if search_query:
            filtered = filtered[filtered['entity_name'].str.contains(search_query, na=False)]

    cols_to_show = [
        'entity_name', 'actual_runs', 'wins', 'places',
        'weighted_runs', 'weighted_score', 'adjusted_score', 'z_score'
    ]
    existing_cols = [c for c in cols_to_show if c in filtered.columns]
    display_df = filtered[existing_cols].copy().sort_values('z_score', ascending=False)

    for col, fmt in (
        ('weighted_score', '{:.3f}'),
        ('weighted_runs', '{:.2f}'),
        ('adjusted_score', '{:.3f}'),
        ('z_score', '{:.2f}'),
    ):
        if col in display_df.columns:
            display_df[col] = display_df[col].map(fmt.format)

    display_df = display_df.rename(columns={
        'entity_name': entity_col_name,
        'actual_runs': '總出賽',
        'wins': '勝出',
        'places': '入圍',
        'weighted_runs': '加權出賽數',
        'weighted_score': '加權總分',
        'adjusted_score': '平滑後得分',
        'z_score': 'Z-Score',
    })
    st.dataframe(display_df, hide_index=True, use_container_width=True)


def _entity_key_for_runner(row, match_mode: str, calc: FactorCalculator) -> str:
    if match_mode == 'jockey':
        return normalize_person_name(row.get('jockey_name'))
    if match_mode == 'trainer':
        return normalize_person_name(row.get('trainer_name'))
    if match_mode == 'synergy':
        return synergy_name(row.get('jockey_name'), row.get('trainer_name'))
    if match_mode == 'draw':
        return calc._assign_draw_group(row.get('draw'))
    if match_mode == 'horse':
        return normalize_person_name(row.get('horse_name'))
    if match_mode == 'horse_jockey':
        return horse_jockey_name(row.get('horse_name'), row.get('jockey_name'))
    return ""


def render_upcoming_match_panel(
    factor_df: pd.DataFrame,
    match_mode: str,
    entity_label: str,
    key_prefix: str,
    use_global_bucket: bool = False,
):
    """
    標準「排位 × 因子」面板：
    - 選場
    - 顯示完整排位列
    - 依每匹馬條件匹配 Z-Score（命中/未命中）
    """
    if factor_df is None or factor_df.empty:
        st.info("請先計算本因子，或回主頁寫入 factor_scores。")
        return

    upcoming_options = get_upcoming_races_list()
    if not upcoming_options:
        st.warning("尚無排位資料。請到「資料控制中心」抓取排位表。")
        # 仍提供歷史瀏覽
        buckets = sorted(factor_df['bucket_id'].unique().tolist())
        if buckets:
            selected_bucket = st.selectbox("📍 歷史分桶", buckets, key=f"{key_prefix}_hist_only")
            display_factor_details(factor_df, selected_bucket, entity_label, key=f"{key_prefix}_hist_search")
        return

    st.subheader("🔮 排位匹配（本場參賽條件 × 本因子）")
    selected_race_id = st.selectbox(
        "選擇賽事：",
        options=[opt[0] for opt in upcoming_options],
        format_func=lambda x: next(opt[1] for opt in upcoming_options if opt[0] == x),
        key=f"{key_prefix}_race",
    )

    if selected_race_id == "None":
        buckets = sorted(factor_df['bucket_id'].unique().tolist())
        selected_bucket = st.selectbox("📍 歷史分桶", buckets, key=f"{key_prefix}_hist")
        display_factor_details(factor_df, selected_bucket, entity_label, key=f"{key_prefix}_search")
        return

    runners_df = get_runners_for_race(selected_race_id)
    if runners_df.empty:
        st.warning("此場沒有排位馬匹。")
        return

    if use_global_bucket:
        target_bucket = GLOBAL_BUCKET
        bucket_ok = True
    else:
        target_bucket = get_bucket_for_race(selected_race_id)
        bucket_ok = is_valid_bucket(target_bucket) if target_bucket else False

    c1, c2, c3 = st.columns(3)
    c1.metric("Bucket", target_bucket or "-")
    c2.metric("Bucket 有效", "是" if bucket_ok else "否")
    c3.metric("排位馬匹數", len(runners_df))

    if not bucket_ok and not use_global_bucket:
        st.error("此場距離/跑道不完整，無法用 Venue_Track_Distance 匹配。請重新抓排位表。")

    calc = FactorCalculator()
    score_map = {}
    subset = factor_df[factor_df['bucket_id'] == target_bucket] if target_bucket else factor_df.iloc[0:0]
    for _, srow in subset.iterrows():
        score_map[str(srow['entity_name'])] = srow

    rows = []
    hits = 0
    for _, row in runners_df.iterrows():
        entity = _entity_key_for_runner(row, match_mode, calc)
        hit = entity in score_map
        if hit:
            hits += 1
            s = score_map[entity]
            z = float(s['z_score'])
            runs = int(s['actual_runs']) if pd.notna(s.get('actual_runs')) else None
            adj = float(s['adjusted_score']) if 'adjusted_score' in s and pd.notna(s.get('adjusted_score')) else None
        else:
            z, runs, adj = None, None, None

        rows.append({
            '馬號': row.get('horse_no'),
            '馬名': row.get('horse_name'),
            '檔位': row.get('draw'),
            '騎師': row.get('jockey_name'),
            '練馬師': row.get('trainer_name'),
            entity_label: entity,
            '命中': '✓' if hit else '✗',
            'Z-Score': None if z is None else round(z, 2),
            '出賽': runs,
            '平滑分': None if adj is None else round(adj, 3),
        })

    match_df = pd.DataFrame(rows)
    st.caption(f"匹配率：{hits}/{len(runners_df)}（{hits / max(len(runners_df), 1):.0%}）")

    # 依 Z-Score 排序（未命中放最後）
    match_df['_sort'] = match_df['Z-Score'].fillna(-999)
    match_df = match_df.sort_values('_sort', ascending=False).drop(columns=['_sort'])

    st.markdown("#### 本場排位 × 因子對照")
    st.dataframe(match_df, hide_index=True, use_container_width=True, height=420)

    with st.expander("查看該 Bucket 完整因子榜（診斷）"):
        display_factor_details(
            factor_df,
            target_bucket,
            entity_label,
            key=f"{key_prefix}_full",
        )
