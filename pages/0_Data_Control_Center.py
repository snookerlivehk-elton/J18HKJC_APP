import streamlit as st
import pandas as pd
import subprocess
import os
from inference_engine import InferenceEngine
from etl_pipeline import USE_SQLITE, SQLITE_DB_PATH

st.set_page_config(page_title="Data Control Center", layout="wide")

st.title("🎛️ 系統控制與數據監控中心 (Data Control Center)")
st.markdown("""
這個版面負責監控賽前資料（排位表、速勢能量）是否已經具備，並提供手動觸發爬蟲的快捷按鈕。
這也是未來開發「全自動化觸發流程」的基礎監控面板。
""")

# ==========================================
# 1. 爬蟲快捷控制按鈕
# ==========================================
st.subheader("🚀 手動觸發爬蟲 (Manual Triggers)")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 📝 抓取明日排位表")
    target_date = st.text_input("日期 (YYYY/MM/DD)", value="2026/09/06", key="racecard_date")
    target_course = st.selectbox("場地", ["ST", "HV"], key="racecard_course")
    if st.button("啟動排位表爬蟲", type="primary", use_container_width=True):
        with st.spinner(f"正在背景抓取 {target_date} {target_course} 的排位表..."):
            try:
                # 確保環境變數傳遞給子進程
                env = os.environ.copy()
                result = subprocess.run(
                    ["python", "racecard_crawler.py", "--date", target_date, "--course", target_course],
                    capture_output=True, text=True, check=True, env=env
                )
                st.success("✅ 排位表抓取完成！請重新整理頁面以更新下方監控面板。")
                with st.expander("查看執行日誌"):
                    st.text(result.stdout)
            except subprocess.CalledProcessError as e:
                st.error(f"❌ 執行失敗：\n{e.stderr}")

with col2:
    st.markdown("### ⚡ 抓取官方速勢能量")
    sg_date = st.text_input("日期 (YYYY/MM/DD)", value="2026/09/06", key="sg_date")
    sg_course = st.selectbox("場地", ["ST", "HV"], key="sg_course")
    if st.button("啟動速勢能量爬蟲", type="primary", use_container_width=True):
        with st.spinner(f"正在背景抓取 {sg_date} {sg_course} 的速勢能量..."):
            try:
                env = os.environ.copy()
                result = subprocess.run(
                    ["python", "speedguide_crawler.py", "--date", sg_date, "--course", sg_course],
                    capture_output=True, text=True, check=True, env=env
                )
                st.success("✅ 速勢能量抓取完成！請重新整理頁面以更新下方監控面板。")
                with st.expander("查看執行日誌"):
                    st.text(result.stdout)
            except subprocess.CalledProcessError as e:
                st.error(f"❌ 執行失敗：\n{e.stderr}")

with col3:
    st.markdown("### 📚 歷史賽果批量爬蟲")
    st.info("💡 歷史爬蟲目前已設定由 GitHub Actions 每日自動在凌晨更新，通常不需手動執行。")
    if st.button("強制執行歷史爬蟲 (增量更新)", use_container_width=True):
        st.warning("⚠️ 歷史爬蟲時間較長，建議在 Terminal 背景執行。這裡暫不提供一鍵觸發以免網頁逾時。")

st.divider()

# ==========================================
# 2. 賽前資料整備度監控 (Data Readiness)
# ==========================================
st.subheader("📊 賽前資料整備度監控 (Pre-race Data Readiness)")
st.markdown("這裡會顯示資料庫中『未來賽事』的準備狀況，確認是否可以進行 AI 推論。")

engine = InferenceEngine()

def get_readiness_status():
    if USE_SQLITE and not os.path.exists(SQLITE_DB_PATH):
        return pd.DataFrame()
        
    try:
        import sqlalchemy
        db_engine = sqlalchemy.create_engine(engine.db_url)
        
        # 查詢各賽事的排位馬匹數與速勢能量數
        query = """
            SELECT 
                r.racing_date AS 賽事日期,
                r.course AS 場地,
                r.race_num AS 場次,
                COUNT(ru.runner_id) AS 排位馬匹數,
                COUNT(s.runner_id) AS 速勢能量數
            FROM upcoming_races r
            LEFT JOIN upcoming_runners ru ON r.race_id = ru.race_id
            LEFT JOIN upcoming_speedguide s ON ru.runner_id = s.runner_id
            GROUP BY r.racing_date, r.course, r.race_num
            ORDER BY r.racing_date ASC, r.race_num ASC
        """
        df = pd.read_sql(query, db_engine)
        return df
    except Exception as e:
        st.error(f"無法讀取資料庫狀態: {e}")
        return pd.DataFrame()

status_df = get_readiness_status()

if status_df.empty:
    st.warning("目前資料庫中沒有任何即將舉行的賽事資料。請使用上方的按鈕抓取排位表。")
else:
    # 增加狀態燈號欄位
    def determine_status(row):
        if row['排位馬匹數'] == 0:
            return "🔴 缺排位表"
        elif row['速勢能量數'] == 0:
            return "🟡 缺速勢能量 (可推論但精度降)"
        elif row['排位馬匹數'] > row['速勢能量數']:
            return "🟡 速勢能量不齊全"
        else:
            return "🟢 資料齊全 (Ready)"
            
    status_df['狀態 (Status)'] = status_df.apply(determine_status, axis=1)
    
    st.dataframe(
        status_df,
        use_container_width=True,
        hide_index=True
    )
    
    # 匯總資訊
    total_races = len(status_df)
    ready_races = len(status_df[status_df['狀態 (Status)'] == '🟢 資料齊全 (Ready)'])
    st.info(f"📈 監控總結：共發現 **{total_races}** 場即將舉行的賽事，其中 **{ready_races}** 場資料已完全齊全。")

