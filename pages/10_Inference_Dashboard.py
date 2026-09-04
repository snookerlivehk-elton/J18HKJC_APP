import streamlit as st
import pandas as pd
from inference_engine import InferenceEngine

st.set_page_config(page_title="Inference Dashboard", layout="wide")

st.title("🔮 明日賽事推論預測引擎 (Inference Dashboard)")
st.markdown("""
這裡是 J18 系統的**第二階段 (Phase 2)**：
讀取賽前排位表，根據明日的「場地 + 賽道 + 距離 (Bucket)」自動匹配歷史計算出的 Z-Score，
最後套用 `config.py` 中的推論權重，計算出**總預測分 (Total Score)** 並給出排名。
""")

# ==========================================
# 1. 初始化與載入賽程
# ==========================================
engine = InferenceEngine()

races_df = engine.get_upcoming_races()

if races_df.empty:
    st.warning("⚠️ 目前資料庫中沒有即將舉行的賽事 (Upcoming Races)。請先執行排位表爬蟲：`python racecard_crawler.py --date YYYY/MM/DD`")
    st.stop()

# ==========================================
# 2. 選擇賽事
# ==========================================
st.subheader("🗓️ 選擇場次")

# 建立下拉選單選項
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

# ==========================================
# 3. 執行推論與顯示排名
# ==========================================
if st.button("🚀 執行 AI 因子推論配對", type="primary"):
    if 'raw_df' not in st.session_state:
        st.error("⚠️ 請先回首頁 (ui_app.py) 點擊「載入歷史賽果數據」，才能進行歷史分數匹配！")
        st.stop()
        
    with st.spinner("正在將排位名單與歷史 Z-Score 進行配對，並套用權重計算..."):
        try:
            # 傳入 session_state 中的歷史數據，避免重複查詢 DB
            predictions_df, race_info = engine.predict_race(selected_race_id, st.session_state['raw_df'])
            
            if predictions_df.empty:
                st.warning("無法產出預測，可能是該場賽事沒有馬匹排位資料。")
            else:
                st.success(f"✅ 成功產出預測！分析基準 Bucket: `{race_info['course']}_{race_info['track'].replace(' 賽道', '')}_{race_info['distance_m']}`")
                
                # 突顯前三名
                st.subheader("🏆 預測排名結果")
                
                # 使用 DataFrame 顯示，加上樣式
                def highlight_top3(s):
                    if s['預測排名'] == 1: return ['background-color: #ffd700; color: black'] * len(s)
                    if s['預測排名'] == 2: return ['background-color: #e3e4e5; color: black'] * len(s)
                    if s['預測排名'] == 3: return ['background-color: #cd7f32; color: black'] * len(s)
                    return [''] * len(s)

                st.dataframe(
                    predictions_df.style.apply(highlight_top3, axis=1),
                    use_container_width=True,
                    height=500
                )
                
                st.info("💡 提示：『總預測分』是由騎師、練馬師、檔位等歷史 Z-Score，加上官方速勢能量轉換後，根據 `config.py` 權重相加而得。")
                
        except Exception as e:
            st.error(f"推論過程發生錯誤: {e}")
