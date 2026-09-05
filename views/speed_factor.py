import streamlit as st
import pandas as pd
from config import ModelConfig
from factor_calculator import FactorCalculator
from bucket_utils import normalize_person_name, GLOBAL_BUCKET
import ui_utils

st.title("⏱️ 速度指數與絕對時間")
st.caption(
    "Par Time + 當日場地偏差 → Speed Figure；FSR 校正末段含金量；"
    "可選 NLP 受阻時間補償。選排位後顯示 Peak / EMA / FSR。"
)

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.sidebar.expander("⚙️ 參數調節", expanded=False):
    ModelConfig.FSR_PENALTY_THRESHOLD = st.number_input(
        "FSR 慢步速懲罰閥值", min_value=100.0, value=ModelConfig.FSR_PENALTY_THRESHOLD
    )
    ModelConfig.FSR_BONUS_THRESHOLD = st.number_input(
        "FSR 快步速獎勵閥值", max_value=100.0, value=ModelConfig.FSR_BONUS_THRESHOLD
    )
    ModelConfig.TIME_EMA_ALPHA = st.slider(
        "EMA Alpha", 0.1, 1.0, ModelConfig.TIME_EMA_ALPHA, 0.1
    )
    apply_nlp = st.checkbox(
        "套用 NLP 受阻時間補償",
        value=True,
        help="受阻場次完成時間偏慢時，對該場 Speed Figure 做小幅上修（與近績名次補償分開）。",
    )

hist_df, hist_src = ui_utils.get_history_df_for_compute()
can_compute = hist_df is not None and not hist_df.empty
if hist_src == "empty":
    st.warning("無法取得歷史資料，請先回主頁載入或確認資料庫有賽果。")
elif hist_src != "session":
    st.caption("已從資料庫載入歷史，可直接計算速度指數。")

if st.button("🚀 計算並寫入速度指數", type="primary", disabled=not can_compute):
    with st.spinner("計算 Speed Figure / FSR / EMA..."):
        calc = FactorCalculator()
        speed_df = calc.calculate_speed_factor(hist_df.copy(), apply_nlp=apply_nlp)
        if speed_df.empty:
            st.error("無法計算速度指數（缺完成時間或分段）。")
        else:
            n = calc.save_factor_scores(speed_df)
            st.session_state["speed_df"] = speed_df
            nlp_n = int(speed_df["nlp_boosted_runs"].sum()) if "nlp_boosted_runs" in speed_df.columns else 0
            st.success(
                f"完成：{len(speed_df)} 匹馬（寫入 factor_scores {n} 列，bucket={GLOBAL_BUCKET}）；"
                f"NLP 時間補償場次合計：{nlp_n}"
            )

speed_df = st.session_state.get("speed_df")
if speed_df is None or (isinstance(speed_df, pd.DataFrame) and speed_df.empty):
    loaded = ui_utils.load_factor_from_db_or_session("speed_df", "SPEED")
    if not loaded.empty and can_compute:
        st.info("資料庫已有 SPEED Z，正在用歷史重算完整 Peak/EMA/FSR 表…")
        calc = FactorCalculator()
        speed_df = calc.calculate_speed_factor(hist_df.copy(), apply_nlp=True)
        if not speed_df.empty:
            st.session_state["speed_df"] = speed_df
    elif not loaded.empty:
        speed_df = loaded
        st.session_state["speed_df"] = speed_df
        st.warning("僅載入 Z-Score。建議有歷史時按上方重算以見 Peak/FSR。")
    else:
        speed_df = pd.DataFrame()

if speed_df is None or speed_df.empty:
    st.info("請先按「計算並寫入速度指數」。")
    st.stop()

speed_df = st.session_state["speed_df"]
name_col = "entity_name" if "entity_name" in speed_df.columns else "horse_name"

upcoming_options = ui_utils.get_upcoming_races_list()
st.subheader("🔮 排位場次 × 速度指數")

selected_race_id = "None"
if upcoming_options:
    selected_race_id = st.selectbox(
        "選擇賽事：",
        options=[opt[0] for opt in upcoming_options],
        format_func=lambda x: next(opt[1] for opt in upcoming_options if opt[0] == x),
        key="speed_race",
    )

if selected_race_id != "None":
    runners = ui_utils.get_runners_for_race(selected_race_id)
    if runners.empty:
        st.warning("此場無排位馬匹")
        display_df = pd.DataFrame()
    else:
        rows = []
        for _, row in runners.iterrows():
            hn = normalize_person_name(row["horse_name"])
            base = speed_df[speed_df[name_col] == hn]
            hit = not base.empty
            rec = base.iloc[0] if hit else None
            rows.append({
                "馬號": row.get("horse_no"),
                "馬名": row.get("horse_name"),
                "檔位": row.get("draw"),
                "騎師": row.get("jockey_name"),
                "練馬師": row.get("trainer_name"),
                "命中": "✓" if hit else "✗",
                "有效紀錄": int(rec["actual_runs"]) if hit else None,
                "歷史峰值": None if not hit else round(float(rec.get("peak_speed", rec.get("adjusted_score", 0))), 2),
                "近況EMA": None if not hit else round(float(rec.get("current_ema", rec.get("adjusted_score", 0))), 2),
                "速度Z": None if not hit else round(float(rec["z_score"]), 2),
                "平均FSR": None if not hit or "avg_fsr" not in rec else round(float(rec["avg_fsr"]), 1),
                "NLP補償場": None if not hit or "nlp_boosted_runs" not in rec else int(rec["nlp_boosted_runs"]),
            })
        display_df = pd.DataFrame(rows)
        hits = int((display_df["命中"] == "✓").sum())
        nlp_horses = int((display_df["NLP補償場"].fillna(0) > 0).sum()) if "NLP補償場" in display_df.columns else 0
        st.caption(f"本場有速度指數：{hits}/{len(display_df)}　｜　有 NLP 時間補償紀錄的馬：{nlp_horses}")
        display_df = display_df.sort_values("速度Z", ascending=False, na_position="last")
else:
    q = st.text_input("搜尋馬名", "")
    display_df = speed_df.copy()
    if q and name_col in display_df.columns:
        display_df = display_df[display_df[name_col].astype(str).str.contains(q, na=False)]
    rename = {
        "entity_name": "馬名",
        "horse_name": "馬名",
        "actual_runs": "有效紀錄",
        "peak_speed": "歷史峰值",
        "current_ema": "近況EMA",
        "z_score": "速度Z",
        "avg_fsr": "平均FSR",
        "nlp_boosted_runs": "NLP補償場",
    }
    display_df = display_df.rename(columns={k: v for k, v in rename.items() if k in display_df.columns})
    keep = [c for c in ["馬名", "有效紀錄", "歷史峰值", "近況EMA", "速度Z", "平均FSR", "NLP補償場"] if c in display_df.columns]
    display_df = display_df[keep].sort_values("速度Z", ascending=False).head(80)

if not display_df.empty:
    st.dataframe(display_df, hide_index=True, use_container_width=True, height=480)

with st.expander("設計說明與優化建議"):
    st.markdown(
        """
**NLP？** 建議加入，但採「時間補償」而非近績名次補償：受阻常令完成時間變慢、Speed Figure 被低估，故對該場 SF 小幅上修。  
未解析報告＝不補償；與近績頁的入位分 NLP 分開。

**本版已接上**
- FSR 慢／快步速校正（先前參數存在但未套用）
- 寫入 `factor_scores`（SPEED）並進推論 `WEIGHT_SPEED_FIGURE`
- 排位表顯示 Peak / EMA / FSR / NLP補償場

**後續優化**
- Par Time 改距離帶＋班次分位數，減少小樣本班次噪音
- L400 改固定末 400m（非「最後一個 stage」近似）
- Peak 與 EMA 雙特徵進 ML（現推論主要用 EMA→Z）
"""
    )
