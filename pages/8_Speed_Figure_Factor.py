import streamlit as st
import pandas as pd
from config import ModelConfig
from factor_calculator import FactorCalculator

st.set_page_config(page_title="速度指數與絕對時間 (Speed Figure)", layout="wide")
st.title("⏱️ 速度指數與絕對時間 (Speed Figure & FSR)")

if 'raw_df' not in st.session_state:
    st.warning("請先至主頁面載入基礎歷史數據！")
    st.stop()

st.markdown("""
### Phase 6: 剝離環境因素的絕對實力
傳統完成時間會被「場地快慢」與「賽事步速」嚴重扭曲。這個模組將時間轉換為客觀的 **「速度指數 (Speed Figure)」**。

*   **Speed Figure (速度指數)**：數值越高，代表該馬匹跑出的時間越快 (已扣除當日場地偏差與班次標準時間)。
*   **FSR (Finishing Speed Ratio)**：末段變速比率。
    *   `> 105%`：慢步速賽事。末段時間快是理所當然，將調降分數權重。
    *   `< 95%`：快步速消耗戰。末段仍能維持高速，給予能力加分。
""")

# ==========================================
# 1. 參數與模型設定區
# ==========================================
with st.sidebar.expander("⚙️ 參數調節 (AI 最佳化入口)", expanded=True):
    st.markdown("針對時間指數的懲罰與獎勵閥值")
    ModelConfig.FSR_PENALTY_THRESHOLD = st.number_input("FSR 慢步速懲罰閥值 (%)", min_value=100.0, value=ModelConfig.FSR_PENALTY_THRESHOLD)
    ModelConfig.FSR_BONUS_THRESHOLD = st.number_input("FSR 快步速獎勵閥值 (%)", max_value=100.0, value=ModelConfig.FSR_BONUS_THRESHOLD)
    st.divider()
    ModelConfig.TIME_EMA_ALPHA = st.slider("EMA 近況趨勢平滑率 (Alpha)", 0.1, 1.0, ModelConfig.TIME_EMA_ALPHA, 0.1)

# ==========================================
# 2. 提取時間並計算 Speed Figure
# ==========================================
if st.button("🚀 解析歷史時間與計算速度指數", type="primary"):
    with st.spinner("正在標準化完成時間與計算 FSR..."):
        calc = FactorCalculator()
        df = st.session_state['raw_df'].copy()
        
        # 提取與計算
        df = calc.extract_time_and_fsr(df)
        
        # 過濾無效時間資料
        df = df.dropna(subset=['speed_figure', 'fsr'])
        
        # 彙整每匹馬的能力指標
        # 1. 歷史峰值 (Peak Speed Rating)
        # 2. 近況趨勢 (Current Form EMA) - 這裡簡化為最近 3 場的平均，後續可加入真實 EMA
        # 3. 平均 FSR
        
        # 先按馬匹與日期排序 (新到舊)
        df = df.sort_values(['horse_name', 'racing_date'], ascending=[True, False])
        
        horse_stats = []
        for horse, group in df.groupby('horse_name'):
            runs = len(group)
            peak_speed = group['speed_figure'].max()
            avg_fsr = group['fsr'].mean()
            
            # 取近 3 場計算 EMA
            recent_3 = group.head(3)['speed_figure'].values
            if len(recent_3) > 0:
                ema = pd.Series(recent_3[::-1]).ewm(alpha=ModelConfig.TIME_EMA_ALPHA, adjust=False).mean().iloc[-1]
            else:
                ema = peak_speed
                
            horse_stats.append({
                'horse_name': horse,
                'runs': runs,
                'peak_speed': peak_speed,
                'current_ema': ema,
                'avg_fsr': avg_fsr
            })
            
        speed_df = pd.DataFrame(horse_stats)
        
        # 排序：優先顯示近況 EMA 最好的馬匹
        speed_df = speed_df.sort_values('current_ema', ascending=False)
        
        st.session_state['speed_df'] = speed_df
        st.success("✅ 速度指數計算完成！")

if 'speed_df' in st.session_state:
    st.divider()
    st.subheader("🏆 馬匹速度指數與近況排行榜 (Speed Figure)")
    
    display_df = st.session_state['speed_df'].copy()
    
    # 格式化數值
    display_df['peak_speed'] = display_df['peak_speed'].map('{:+.2f}s'.format)
    display_df['current_ema'] = display_df['current_ema'].map('{:+.2f}s'.format)
    display_df['avg_fsr'] = display_df['avg_fsr'].map('{:.1f}%'.format)
    
    # 重新命名欄位供顯示
    display_df = display_df.rename(columns={
        'horse_name': '馬匹名稱',
        'runs': '有效時間紀錄',
        'peak_speed': '歷史峰值 (Peak Speed)',
        'current_ema': '近況趨勢 (Current EMA)',
        'avg_fsr': '平均末段變速 (Avg FSR)'
    })
    
    st.dataframe(display_df, hide_index=True, use_container_width=True)
    
    st.markdown("""
    **💡 解讀指南：**
    - **歷史峰值 (Peak Speed)**：正數代表比標準時間快。例如 `+1.50s` 代表這匹馬的能力天花板極高。
    - **近況趨勢 (Current EMA)**：反映近 3 場的狀態。如果 EMA 逼近 Peak Speed，代表這匹馬目前處於大勇狀態！
    - **平均末段變速 (Avg FSR)**：
      - `< 100%`：代表末段時間比全場平均速度快 (爆發力強)。
      - `> 100%`：代表末段時間比平均速度慢 (均速馬或末段腳軟)。
    """)