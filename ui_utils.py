"""
各因子頁共用的 UI 工具：排位選擇、Bucket 顯示、排位列 × 因子匹配表。
"""
import streamlit as st
import pandas as pd
from inference_engine import InferenceEngine
from factor_calculator import FactorCalculator
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
    parse_bucket_parts,
    format_class_display,
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
        cls_disp = format_class_display(cls)
        bucket = make_bucket_id(
            race_id=row['race_id'],
            course=course,
            track=track,
            distance_m=dist,
        )
        band = make_band_bucket_id(
            race_id=row['race_id'],
            course=course,
            distance_m=dist,
        )
        valid = "✓" if is_valid_bucket(bucket) else "✗"
        label = (
            f"第 {num} 場 | {date} {course} {track or '-'} {dist or '?'}米 ({cls_disp}) "
            f"[{valid} {bucket} / 粗:{band}]"
        )
        options.append((row['race_id'], label))
    return options


@st.cache_data(ttl=60)
def get_upcoming_meeting_days_list():
    """
    整個賽日選項。
    回傳 [(meeting_key, label, race_ids), ...]
    meeting_key = YYYY-MM-DD|ST 或 YYYY-MM-DD|HV
    """
    engine = InferenceEngine()
    races_df = engine.get_upcoming_races()
    if races_df.empty:
        return []

    df = races_df.copy()
    df["racing_date"] = pd.to_datetime(df["racing_date"]).dt.strftime("%Y-%m-%d")
    df["course"] = df["course"].astype(str).str.upper()
    options = []
    for (date, course), g in df.groupby(["racing_date", "course"], sort=True):
        g = g.sort_values("race_num")
        race_ids = g["race_id"].astype(str).tolist()
        n_races = len(race_ids)
        key = f"{date}|{course}"
        label = f"{date} {course}｜共 {n_races} 場（第 {int(g['race_num'].min())}–{int(g['race_num'].max())} 場）"
        options.append((key, label, race_ids))
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


def get_history_df_for_compute():
    """供各因子頁計算：優先 session raw_df，否則直接從 DB 抓歷史。"""
    if 'raw_df' in st.session_state and not st.session_state['raw_df'].empty:
        return st.session_state['raw_df'].copy(), "session"
    calc = FactorCalculator()
    df = calc.fetch_historical_data()
    if df.empty:
        return df, "empty"
    df = calc.calculate_base_score(df)
    st.session_state['raw_df'] = df
    st.session_state['buckets'] = sorted(df['bucket_id'].unique().tolist())
    return df.copy(), "database"


def racecard_looks_corrupt(runners_df: pd.DataFrame):
    """偵測舊版爬蟲造成的欄位錯位：檔位全 0、練馬師變成數字。
    回傳 (is_corrupt, message)
    """
    if runners_df is None or runners_df.empty:
        return False, ""
    n = len(runners_df)
    draw_zero = 0
    if 'draw' in runners_df.columns:
        draw_zero = int((pd.to_numeric(runners_df['draw'], errors='coerce').fillna(0) == 0).sum())
    trainer_numeric = 0
    if 'trainer_name' in runners_df.columns:
        trainer_numeric = int(
            runners_df['trainer_name'].astype(str).str.fullmatch(r"\d+").fillna(False).sum()
        )
    if draw_zero >= max(n - 1, 1) and trainer_numeric >= max(n // 2, 1):
        return True, (
            f"排位資料疑似舊版錯位（檔位為 0 者 {draw_zero}/{n}，"
            f"練馬師為純數字者 {trainer_numeric}/{n}）。"
            "請到「資料控制中心」用**最新程式**重新抓取排位表覆寫，"
            "再回本頁重新整理。這不是因子計算錯誤。"
        )
    if trainer_numeric >= max(n // 2, 1):
        return True, (
            f"練馬師欄位多數為數字（{trainer_numeric}/{n}），排位爬蟲欄位仍錯位。"
            "請重新抓取排位表。"
        )
    return False, ""


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


def get_band_bucket_for_race(race_id):
    """騎師/練馬師/騎練用的距離帶粗桶。"""
    engine = InferenceEngine()
    races_df = engine.get_upcoming_races()
    if races_df.empty:
        return None
    matched = races_df[races_df['race_id'] == race_id]
    if matched.empty:
        return None
    race_info = matched.iloc[0]
    return make_band_bucket_id(
        race_id=race_info['race_id'],
        course=race_info['course'],
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

    corrupt, corrupt_msg = racecard_looks_corrupt(runners_df)
    if corrupt:
        st.error(corrupt_msg)
        st.dataframe(
            runners_df[['horse_no', 'horse_name', 'draw', 'jockey_name', 'trainer_name']],
            hide_index=True,
            use_container_width=True,
        )
        return

    if use_global_bucket:
        target_bucket = GLOBAL_BUCKET
        bucket_ok = True
        race_bucket = get_bucket_for_race(selected_race_id)
        band_bucket = get_band_bucket_for_race(selected_race_id)
    elif match_mode in ('jockey', 'trainer', 'synergy', 'horse'):
        # 騎練／馬匹近績：距離帶粗桶
        target_bucket = get_band_bucket_for_race(selected_race_id)
        band_bucket = target_bucket
        race_bucket = get_bucket_for_race(selected_race_id)
        bucket_ok = is_valid_band_bucket(target_bucket) if target_bucket else False
    else:
        # 檔位等：細桶
        target_bucket = get_bucket_for_race(selected_race_id)
        race_bucket = target_bucket
        band_bucket = get_band_bucket_for_race(selected_race_id)
        bucket_ok = is_valid_bucket(target_bucket) if target_bucket else False

    c1, c2, c3 = st.columns(3)
    c1.metric("匹配 Bucket", target_bucket or "-")
    c2.metric("Bucket 有效", "是" if bucket_ok else "否")
    c3.metric("排位馬匹數", len(runners_df))
    if band_bucket and match_mode == 'draw':
        st.caption(f"參考：本場距離帶粗桶為 `{band_bucket}`（騎練／近績因子用此鍵）")
    if match_mode in ('jockey', 'trainer', 'synergy', 'horse') and race_bucket:
        st.caption(f"參考：本場細桶為 `{race_bucket}`（檔位因子用此鍵）")

    if not bucket_ok and not use_global_bucket:
        st.error("此場 Bucket 無效（缺距離/場地）。請重新抓排位表。")

    calc = FactorCalculator()
    score_map = {}
    subset = factor_df[factor_df['bucket_id'] == target_bucket] if target_bucket else factor_df.iloc[0:0]
    for _, srow in subset.iterrows():
        score_map[str(srow['entity_name'])] = srow

    # 近績頁：顯示 NLP 是否已納入目前 factor_scores
    horse_nlp_map = {}
    if match_mode == 'horse':
        freshness = calc.horse_factor_nlp_freshness()
        st.markdown("#### NLP 判決納入狀態")
        f1, f2, f3 = st.columns(3)
        f1.metric("有受阻判決的歷史出賽", freshness.get("excuse_runner_count", 0))
        f2.metric(
            "近績分數時間",
            str(freshness.get("horse_calculated_at"))[:19] if freshness.get("horse_calculated_at") is not None else "尚無",
        )
        f3.metric(
            "最新 NLP 時間",
            str(freshness.get("nlp_updated_at"))[:19] if freshness.get("nlp_updated_at") is not None else "尚無",
        )
        st_map = freshness.get("status")
        if st_map == "stale_horse":
            st.warning(
                "NLP 解析比近績分數更新。**目前表上的 Z／平滑分尚未反映最新判決**。"
                "請按上方「計算並寫入馬匹近績因子」（勾選套用 NLP）或主頁重算。"
            )
        elif st_map == "horse_current":
            if freshness.get("excuse_runner_count", 0) > 0:
                st.success(
                    "近績分數時間不早於最新 NLP；若重算時有勾選「套用 NLP」，"
                    "下方「NLP受阻」為 ✓ 的馬，其 Z 已可能含受阻補償。"
                )
            else:
                st.info("已有近績分數，但庫內尚無 has_excuse=true 的判決（或皆為無受阻／略過）。")
        elif st_map == "no_nlp":
            st.info("尚未有 NLP 解析結果；目前近績為純歷史名次計算。")
        elif st_map == "no_horse_factor":
            st.warning("尚無 HORSE 近績分數，請先計算並寫入。")

        horse_nlp_map = calc.summarize_nlp_impact_by_horse(
            runners_df["horse_name"].tolist(),
            lookback_days=360,
        )

    # 人馬雙軌：預載歷史 + 騎師 Z（供 Upgrade Delta）
    hist_df = None
    jockey_scores = None
    if match_mode == 'horse_jockey':
        st.caption(
            "分桶說明：A 軌人馬合作本身是 GLOBAL（白皮書：不分場地距離）；"
            "現場再用「接近距離加權」提高相近路程權重。"
            "B 軌騎師 Z 採層級回退：精確桶 → 同場地同距 → 距離帶 → 全局。"
            f" 熟識 prior={ModelConfig.HJ_PARTNERSHIP_PRIOR}；"
            f"無合作 B×{ModelConfig.UPGRADE_B_ONLY_SCALE}。"
        )
        if 'raw_df' in st.session_state and not st.session_state['raw_df'].empty:
            hist_df = st.session_state['raw_df']
        else:
            hist_df, _ = get_history_df_for_compute()
        jockey_scores = calc.load_factor_scores(['JOCKEY'])
        if jockey_scores.empty and 'j_df_indep' in st.session_state:
            jockey_scores = st.session_state['j_df_indep']

    rows = []
    hits = 0
    scored = 0
    for _, row in runners_df.iterrows():
        entity = _entity_key_for_runner(row, match_mode, calc)
        hit = entity in score_map
        if hit:
            hits += 1
            s = score_map[entity]
            z = float(s['z_score'])
            runs = int(s['actual_runs']) if pd.notna(s.get('actual_runs')) else None
            adj = float(s['adjusted_score']) if 'adjusted_score' in s and pd.notna(s.get('adjusted_score')) else None
            source = 'A:合作歷史'
            used = z
        else:
            z, runs, adj, used = None, None, None, None
            source = '無'

        if match_mode == 'horse_jockey':
            _, _, race_dist = parse_bucket_parts(race_bucket) if race_bucket else (None, None, None)
            near = calc.score_partnership_near_distance(
                row.get('horse_name'),
                row.get('jockey_name'),
                race_dist,
                hist_df,
            )
            # 優先用接近距離加權現場分；若無配對再退回 GLOBAL 表
            if near.get('z_proxy') is not None and near.get('actual_runs', 0) > 0:
                z = float(near['z_proxy'])
                runs = int(near['actual_runs'])
                hit = True
                hits = hits  # already counted if score_map hit; avoid double — recount below
            elif hit:
                pass  # keep GLOBAL z
            else:
                z, runs = None, 0

            # B 軌用距離帶粗桶查騎師 Z（與 JOCKEY factor_scores 一致）
            jockey_lookup_bucket = band_bucket or race_bucket or ''
            delta_info = calc.compute_jockey_upgrade_delta(
                horse_name=row.get('horse_name'),
                current_jockey=row.get('jockey_name'),
                race_bucket=jockey_lookup_bucket,
                hist_df=hist_df,
                jockey_scores=jockey_scores,
            )
            delta = delta_info.get('delta')
            used, scaled_b, source = calc.adopt_horse_jockey_score(
                z if (z is not None) else None,
                runs if runs else 0,
                delta,
            )
            if near.get('source') == 'near_distance_weighted' and z is not None and source.startswith('A'):
                source = source + '+近距加權'

            row_out = {
                '馬號': row.get('horse_no'),
                '馬名': row.get('horse_name'),
                '檔位': row.get('draw'),
                '騎師': row.get('jockey_name'),
                '練馬師': row.get('trainer_name'),
                entity_label: entity,
                '合作命中': '✓' if (z is not None) else '✗',
                '合作Z': None if z is None else round(z, 2),
                '加權出賽': None if not near.get('weighted_runs') else round(float(near['weighted_runs']), 2),
                '換人Δ原值': None if delta is None else round(delta, 2),
                '換人Δ正規化': None if scaled_b is None else round(scaled_b, 2),
                '採用分': None if used is None else round(used, 2),
                '來源': source,
                '合作出賽': runs,
            }
            if used is not None:
                scored += 1
            rows.append(row_out)
            continue

        row_out = {
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
        }
        if match_mode == 'horse':
            nlp = horse_nlp_map.get(entity) or horse_nlp_map.get(normalize_person_name(row.get('horse_name'))) or {}
            exc = int(nlp.get("excuse_count") or 0)
            row_out['NLP受阻'] = '✓' if exc > 0 else '—'
            row_out['NLP場次'] = exc
            row_out['NLP段'] = nlp.get("best_stage") or '—'
            row_out['NLP嚴重度'] = (
                round(float(nlp.get("best_severity") or 0), 2) if exc > 0 else None
            )
            row_out['NLP摘要'] = nlp.get("reason") or ''
            row_out['已解析報告'] = int(nlp.get("parsed_reports") or 0)
        rows.append(row_out)
        if hit:
            scored += 1

    # 人馬頁重新統計合作命中（含近距加權現場算出者）
    if match_mode == 'horse_jockey' and rows:
        hits = sum(1 for r in rows if r.get('合作命中') == '✓')

    match_df = pd.DataFrame(rows)
    if match_mode == 'horse_jockey':
        st.caption(
            f"合作歷史命中：{hits}/{len(runners_df)}　｜　"
            f"有採用分（A／混合／正規化B）：{scored}/{len(runners_df)}"
        )
        sort_col = '採用分'
    else:
        st.caption(f"匹配率：{hits}/{len(runners_df)}（{hits / max(len(runners_df), 1):.0%}）")
        sort_col = 'Z-Score'
        if match_mode == 'horse' and 'NLP受阻' in match_df.columns:
            n_exc = int((match_df['NLP受阻'] == '✓').sum())
            st.caption(
                f"本場有 NLP 受阻判決的馬：{n_exc}/{len(runners_df)}　｜　"
                "「NLP受阻=✓」表示回看期內至少一場 has_excuse；"
                "Z 是否已含補償取決於上方「近績分數時間」是否在 NLP 之後並已重算。"
            )

    # 依分數排序（未命中放最後）
    if sort_col in match_df.columns:
        match_df['_sort'] = match_df[sort_col].fillna(-999)
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
