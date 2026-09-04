import streamlit as st
import pandas as pd
from inference_engine import InferenceEngine

st.set_page_config(page_title="Inference Dashboard", layout="wide")

st.title("🔮 明日賽事推論預測引擎 (Inference Dashboard)")
st.markdown("""
**主流程**：讀取排位表 → 粗桶匹配騎練／近績、細桶匹配檔位 → 查 `factor_scores` → 加權排名。  

請先：① 資料控制中心抓排位 ② 主頁「重算並寫入因子分數」③ 本頁選場預測。  
""")

engine = InferenceEngine()
races_df = engine.get_upcoming_races()

if races_df.empty:
    st.warning("⚠️ 目前沒有即將舉行的賽事。請先到「資料控制中心」抓取排位表。")
    st.stop()

scores_preview = engine.calc.load_factor_scores(
    factor_types=['JOCKEY', 'TRAINER', 'SYNERGY', 'DRAW', 'HORSE']
)
if scores_preview.empty:
    st.error("❌ `factor_scores` 是空的。請回主頁執行「重算並寫入因子分數」後再預測。")
    st.stop()
else:
    types = sorted(scores_preview['factor_type'].unique().tolist())
    st.caption(f"目前資料庫已有 {len(scores_preview)} 筆因子分數（類型：{types}）。")

st.subheader("🗓️ 選擇場次")

race_options = []
for _, row in races_df.iterrows():
    date = row['racing_date']
    course = row['course']
    num = row['race_num']
    dist = row['distance_m']
    track = row['track']
    cls = row['class']
    label = f"第 {num} 場 | {date} {course} {track} {dist}米 ({cls})"
    race_options.append((row['race_id'], label))

selected_race_id = st.selectbox(
    "請選擇要進行預測的賽事：",
    options=[opt[0] for opt in race_options],
    format_func=lambda x: next(opt[1] for opt in race_options if opt[0] == x)
)

if st.button("🚀 執行因子匹配預測", type="primary"):
    with st.spinner("正在以排位條件查詢 factor_scores..."):
        try:
            predictions_df, race_info, meta = engine.predict_race(selected_race_id)

            if not meta.get('bucket_valid') and not meta.get('band_bucket_valid'):
                st.error(
                    f"此場 Bucket 無效：細=`{meta.get('bucket_id')}`／粗=`{meta.get('band_bucket_id')}`。"
                    "排位表可能缺少跑道或距離，請重新抓取排位表。"
                )
                st.stop()

            st.info(
                f"細桶(檔位)：`{meta['bucket_id']}`　｜　"
                f"粗桶(騎練/近績)：`{meta.get('band_bucket_id')}`　｜　"
                f"因子表列數：{meta['factor_rows']}　｜　"
                f"匹配率：{meta['match_rate']:.0%}　"
                f"（J{meta['hit_counts']['JOCKEY']} "
                f"T{meta['hit_counts']['TRAINER']} "
                f"S{meta['hit_counts']['SYNERGY']} "
                f"D{meta['hit_counts']['DRAW']} "
                f"H{meta['hit_counts'].get('HORSE', 0)}）"
            )

            if meta['match_rate'] == 0:
                st.warning(
                    "匹配率為 0%：請用主頁「重算並寫入 factor_scores」產生距離帶粗桶鍵（如 ST_SPRINT），"
                    "並確認排位距離/跑道正確。"
                )

            if predictions_df.empty:
                st.warning("無法產出預測，可能是該場沒有馬匹排位資料。")
            else:
                st.subheader("🏆 預測排名結果")

                def highlight_top3(s):
                    if s['預測排名'] == 1:
                        return ['background-color: #ffd700; color: black'] * len(s)
                    if s['預測排名'] == 2:
                        return ['background-color: #e3e4e5; color: black'] * len(s)
                    if s['預測排名'] == 3:
                        return ['background-color: #cd7f32; color: black'] * len(s)
                    return [''] * len(s)

                st.dataframe(
                    predictions_df.style.apply(highlight_top3, axis=1),
                    use_container_width=True,
                    height=500
                )
                st.caption("「命中」欄表示該馬四項核心因子（騎/練/騎練/檔）有幾項成功查到歷史 Z-Score。")

        except Exception as e:
            st.error(f"推論過程發生錯誤: {e}")
