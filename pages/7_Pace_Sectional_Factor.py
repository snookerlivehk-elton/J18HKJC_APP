import streamlit as st
import pandas as pd
import numpy as np
from config import ModelConfig
from factor_calculator import FactorCalculator

st.set_page_config(page_title="步速與分段形勢 (Pace & Sectional)", layout="wide")
st.title("⏱️ 步速與分段形勢因子 (Pace & Sectional Factor)")

if 'raw_df' not in st.session_state:
    st.warning("請先至主頁面載入基礎歷史數據！")
    st.stop()

st.markdown("""
### Phase 5: 跑法風格與後追力分析
這個模組旨在透過歷史走位數據，量化馬匹的**跑法風格 (Running Style)** 與 **後追力/貫注力 (Positions Gained)**。

*   **早段名次 (Early Position)**：反映馬匹的前速與領放傾向。數值越小，代表前速越快。
*   **追回名次 (Positions Gained)**：等於「早段名次 - 最終名次」。
    *   **正數 (e.g. +5)**：早段落後，但末段爆發追過 5 匹馬 👉 **強大後追力 (Closer)**。
    *   **負數 (e.g. -6)**：早段領先，但直路力弱被 6 匹馬超越 👉 **貫注力不足 (Fader)**。
""")

# ==========================================
# 1. 參數與模型設定區
# ==========================================
with st.sidebar.expander("⚙️ 參數調節 (AI 最佳化入口)", expanded=True):
    st.markdown("針對跑法與步速調整超參數")
    ModelConfig.PACE_SMOOTH_C = st.number_input("PACE_SMOOTH_C (跑法平滑數)", min_value=1, value=ModelConfig.PACE_SMOOTH_C)
    st.divider()
    st.markdown("預測時的步速加分權重 (未來預測排位表時使用)")
    ModelConfig.CLOSER_BONUS_WEIGHT = st.slider("後追馬加分 (當遇快步速)", 1.0, 3.0, ModelConfig.CLOSER_BONUS_WEIGHT, 0.1)
    ModelConfig.FRONT_RUNNER_BONUS_WEIGHT = st.slider("前領馬加分 (當遇慢步速)", 1.0, 3.0, ModelConfig.FRONT_RUNNER_BONUS_WEIGHT, 0.1)

# ==========================================
# 2. 提取分段走位數據並計算
# ==========================================
if st.button("🚀 解析歷史分段走位數據", type="primary"):
    with st.spinner("正在從 JSON 中提取分段位置並計算追回名次..."):
        calc = FactorCalculator()
        df = st.session_state['raw_df'].copy()
        
        # 提取分段位置
        df = calc.extract_sectional_positions(df)
        
        # 過濾掉沒有分段資料的無效記錄
        df = df.dropna(subset=['early_position', 'positions_gained'])
        
        # 計算每匹馬的歷史平均跑法與平均追回名次
        pace_df = df.groupby('horse_name').agg({
            'early_position': ['mean', 'count'],
            'positions_gained': 'mean',
            'finish_order_num': 'mean'
        }).reset_index()
        
        # 展平欄位名稱
        pace_df.columns = ['horse_name', 'avg_early_pos', 'runs_with_sections', 'avg_positions_gained', 'avg_finish']
        
        # 套用跑法標籤 (基於歷史平均)
        conditions = [
            (pace_df['avg_early_pos'] <= 4.5),
            (pace_df['avg_early_pos'] <= 8.5),
            (pace_df['avg_early_pos'] > 8.5)
        ]
        choices = ['前領 (Front-Runner)', '居中 (Mid-Pack)', '後追 (Closer)']
        pace_df['running_style'] = pd.Series(np.select(conditions, choices, default='未知'))
        
        # 貝葉斯平滑處理平均追回名次 (防範出賽 1 次剛好追回 10 匹的極端值)
        global_avg_gained = pace_df['avg_positions_gained'].mean()
        c = ModelConfig.PACE_SMOOTH_C
        pace_df['smoothed_positions_gained'] = (
            (pace_df['avg_positions_gained'] * pace_df['runs_with_sections'] + c * global_avg_gained) /
            (pace_df['runs_with_sections'] + c)
        )
        
        # 排序：優先顯示後追力最強的馬
        pace_df = pace_df.sort_values('smoothed_positions_gained', ascending=False)
        
        st.session_state['pace_df'] = pace_df
        st.success("✅ 分段形勢計算完成！")

if 'pace_df' in st.session_state:
    st.divider()
    st.subheader("🏆 全局馬匹跑法與後追力排行榜")
    
    display_df = st.session_state['pace_df'].copy()
    
    # 格式化數值
    display_df['avg_early_pos'] = display_df['avg_early_pos'].map('{:.1f}'.format)
    display_df['avg_positions_gained'] = display_df['avg_positions_gained'].map('{:.2f}'.format)
    display_df['avg_finish'] = display_df['avg_finish'].map('{:.1f}'.format)
    display_df['smoothed_positions_gained'] = display_df['smoothed_positions_gained'].map('{:.2f}'.format)
    
    # 重新命名欄位供顯示
    display_df = display_df.rename(columns={
        'horse_name': '馬匹名稱',
        'runs_with_sections': '有效出賽次數',
        'running_style': '跑法風格',
        'avg_early_pos': '平均早段名次',
        'avg_finish': '平均最終名次',
        'avg_positions_gained': '平均追回名次 (正數為後追)',
        'smoothed_positions_gained': '平滑後追回指數 (Closer Score)'
    })
    
    st.dataframe(display_df, hide_index=True, use_container_width=True)
    
    st.markdown("""
    **💡 解讀指南：**
    - **平滑後追回指數 (Closer Score)** 越高，代表該馬匹在末段衝刺時超越對手的能力越強。
    - 在未來的「預測階段」，如果系統判斷這場比賽將是**超快步速 (Fast Pace)**，我們就會給排行榜上方這些 **「後追 (Closer)」** 馬匹額外的加分 (`CLOSER_BONUS_WEIGHT`)！
    """)
