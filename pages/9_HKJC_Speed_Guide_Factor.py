import streamlit as st
import pandas as pd
import sqlite3
import os

st.set_page_config(page_title="HKJC Speed Guide Factor", layout="wide")

st.title("⚡ Phase 9: HKJC Speed Guide (官方速勢能量因子)")
st.markdown("""
這頁面用來展示賽前 36 小時由 `speedguide_crawler.py` 從 HKJC 官網抓取的官方數據：
- **狀態評級 (Form Rating)**
- **速勢能量評估 (Speed Energy)**
- **速勢能量評估差值 (Speed Energy Delta)**

這三個維度將構成我們最後一個官方分析因子，用來補足我們純歷史量化數據的盲區。
""")

DB_PATH = "j18_local.db"

def load_speedguide_data():
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
        
    try:
        conn = sqlite3.connect(DB_PATH)
        query = '''
            SELECT 
                race_id, horse_no, form_rating, speed_energy, speed_energy_delta, created_at
            FROM upcoming_speedguide
            ORDER BY race_id DESC, horse_no ASC
        '''
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    except sqlite3.OperationalError:
        return pd.DataFrame()

# ==========================================
# 1. 數據展示區
# ==========================================
st.header("📊 速勢能量暫存區 (Speedguide Data)")

col1, col2 = st.columns([1, 4])
with col1:
    if st.button("🔄 刷新資料庫", use_container_width=True):
        st.cache_data.clear()
        
df = load_speedguide_data()

if df.empty:
    st.info("目前資料庫中尚未有任何速勢能量資料。請確保您已執行 `python speedguide_crawler.py --date YYYY/MM/DD` 來抓取賽前排位資料。")
else:
    # 進行一些中文欄位對應，方便閱讀
    display_df = df.copy()
    display_df = display_df.rename(columns={
        "race_id": "賽事 ID",
        "horse_no": "馬號",
        "form_rating": "狀態評級 (Form)",
        "speed_energy": "速勢能量 (Energy)",
        "speed_energy_delta": "速勢能量差值 (Delta)",
        "created_at": "爬取時間"
    })
    
    st.dataframe(display_df, use_container_width=True)

# ==========================================
# 2. 超參數調節區 (預留給未來推論引擎)
# ==========================================
st.header("🎛️ 因子權重調節 (Factor Hyperparameters)")
st.markdown("在這裡您可以設定這三個官方指標在最終推論時的影響力 (此設定將寫入未來的 `config.py`)")

col_p1, col_p2, col_p3 = st.columns(3)
with col_p1:
    st.slider("狀態評級權重 (Form Rating Weight)", 0.0, 2.0, 1.0, 0.1, help="決定官方狀態評級對總分的影響")
with col_p2:
    st.slider("速勢能量權重 (Speed Energy Weight)", 0.0, 2.0, 1.0, 0.1, help="決定官方速勢能量對總分的影響")
with col_p3:
    st.slider("能量差值權重 (Delta Weight)", -1.0, 1.0, 0.5, 0.1, help="決定差值的補償力道")

st.success("目前爬蟲已實裝，並嚴格遵守了 `httpx.Limits(max_connections=1)` 與 3.0 秒的禮貌延遲規範。")