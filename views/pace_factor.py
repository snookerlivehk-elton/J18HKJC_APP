import streamlit as st
import pandas as pd
from config import ModelConfig
from factor_calculator import FactorCalculator
from bucket_utils import normalize_person_name, GLOBAL_BUCKET
import ui_utils
import ui_param_help as ph

st.title("⏱️ 步速與分段形勢因子")
st.caption(
    "由歷史分段走位推跑法與追回指數（GLOBAL）；"
    "選排位後推算同場步速熱度，並給前領／後追形勢加權。"
)

if not ui_utils.ensure_history_loaded():
    st.stop()

with st.expander("⚙️ 參數調節", expanded=False):
    st.caption("游標停在標籤旁 ⓘ 可看功能與調節後變化。")
    ModelConfig.PACE_SMOOTH_C = st.number_input(
        "跑法平滑常數", min_value=1, value=ModelConfig.PACE_SMOOTH_C, help=ph.PACE_SMOOTH
    )
    ModelConfig.CLOSER_BONUS_WEIGHT = st.slider(
        "後追馬加分", 1.0, 3.0, ModelConfig.CLOSER_BONUS_WEIGHT, 0.1, help=ph.CLOSER_BONUS
    )
    ModelConfig.FRONT_RUNNER_BONUS_WEIGHT = st.slider(
        "前領馬加分", 1.0, 3.0, ModelConfig.FRONT_RUNNER_BONUS_WEIGHT, 0.1, help=ph.FRONT_BONUS
    )
    ModelConfig.EARLY_SPEED_TOP_N = st.number_input(
        "熱度取前 N 名（顯示用）",
        min_value=1,
        max_value=5,
        value=ModelConfig.EARLY_SPEED_TOP_N,
        help=ph.EARLY_SPEED_TOP_N,
    )
    ModelConfig.PACE_EARLY_FAST_Z = st.slider(
        "爭搶馬早段 Z 門檻",
        0.25, 1.50, float(ModelConfig.PACE_EARLY_FAST_Z), 0.05,
        help=ph.PACE_EARLY_FAST_Z,
    )
    ModelConfig.PACE_HOT_MIN_CONTENDERS = st.number_input(
        "超快：最少爭搶馬數",
        min_value=2, max_value=6, value=int(ModelConfig.PACE_HOT_MIN_CONTENDERS),
        help=ph.PACE_HOT_MIN,
    )
    ModelConfig.PACE_COLD_MAX_CONTENDERS = st.number_input(
        "偏慢：最多爭搶馬數",
        min_value=0, max_value=2, value=int(ModelConfig.PACE_COLD_MAX_CONTENDERS),
        help=ph.PACE_COLD_MAX,
    )

hist_df, hist_src = ui_utils.get_history_df_for_compute()
can_compute = hist_df is not None and not hist_df.empty
if hist_src == "empty":
    st.warning("無法取得歷史資料，請先回主頁載入或確認資料庫有賽果。")
elif hist_src != "session":
    st.caption("已從資料庫載入歷史，可直接計算步速因子（無需主頁 session）。")

if st.button("🚀 計算並寫入步速因子", type="primary", disabled=not can_compute):
    with st.spinner("解析分段走位並計算跑法／追回指數..."):
        calc = FactorCalculator()
        pace_df = calc.calculate_pace_factor(hist_df.copy())
        if pace_df.empty:
            st.error(
                "無法抽出分段走位（sections）。請確認歷史 raw_json 含 stage 位置資料。"
            )
        else:
            n = calc.save_factor_scores(pace_df)
            st.session_state["pace_df"] = pace_df
            st.success(
                f"完成：{len(pace_df)} 匹馬（已寫入 factor_scores {n} 列，bucket={GLOBAL_BUCKET}）。"
            )
            st.write(pace_df["running_style"].value_counts())

pace_df = st.session_state.get("pace_df")
if pace_df is None or (isinstance(pace_df, pd.DataFrame) and pace_df.empty):
    # 嘗試從 DB 讀 Z；完整跑法欄需重算
    loaded = ui_utils.load_factor_from_db_or_session("pace_df", "PACE")
    if not loaded.empty and can_compute:
        st.info("資料庫已有 PACE Z-Score，但缺跑法明細。正在用歷史重算完整表…")
        calc = FactorCalculator()
        pace_df = calc.calculate_pace_factor(hist_df.copy())
        if not pace_df.empty:
            st.session_state["pace_df"] = pace_df
    elif not loaded.empty:
        pace_df = loaded.rename(columns={"entity_name": "entity_name"})
        st.session_state["pace_df"] = pace_df
        st.warning("僅載入 Z-Score（無跑法／早段欄）。建議有歷史時按上方重算。")
    else:
        pace_df = pd.DataFrame()

if pace_df is None or pace_df.empty:
    st.info("請先按「計算並寫入步速因子」。")
    st.stop()

pace_df = st.session_state["pace_df"]
name_col = "entity_name" if "entity_name" in pace_df.columns else "horse_name"

upcoming_options = ui_utils.get_upcoming_races_list()
st.subheader("🔮 排位場次 × 步速形勢")

selected_race_id = "None"
if upcoming_options:
    selected_race_id = st.selectbox(
        "選擇賽事：",
        options=[opt[0] for opt in upcoming_options],
        format_func=lambda x: next(opt[1] for opt in upcoming_options if opt[0] == x),
        key="pace_race",
    )

calc = FactorCalculator()
if selected_race_id != "None":
    runners = ui_utils.get_runners_for_race(selected_race_id)
    if runners.empty:
        st.warning("此場無排位馬匹")
        display_df = pace_df.sort_values("z_score", ascending=False).head(50)
    else:
        proj = calc.project_race_pace(pace_df, runners["horse_name"].tolist())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("步速熱度 Pace Heat", f"{proj['heat']:.2f}")
        c2.metric("形勢劇本", proj["scenario"])
        c3.metric(
            "爭搶馬數",
            f"{proj.get('n_contenders', 0)}",
        )
        c4.metric(
            "判定門檻",
            f"超快≥{proj.get('hot_need', ModelConfig.PACE_HOT_MIN_CONTENDERS)}／慢≤{proj.get('cold_need', ModelConfig.PACE_COLD_MAX_CONTENDERS)}",
        )
        st.caption(
            f"爭搶馬＝早段速度 Z ≥ {float(proj.get('fast_z', ModelConfig.PACE_EARLY_FAST_Z)):.2f}；"
            f"Pace Heat＝前 {proj.get('top_n', ModelConfig.EARLY_SPEED_TOP_N)} 名 Z 加總（僅顯示，不直接判劇本）。"
        )

        if proj["scenario"] == "超快步速":
            st.caption(
                f"超快互燒：爭搶馬 {proj.get('n_contenders')} 匹 "
                f"（需≥{proj.get('hot_need')}；命中 {proj.get('field_matched')} 匹）。後追加分、前領略扣。"
            )
        elif proj["scenario"] == "偏慢步速":
            st.caption(
                f"偏慢／獨走：爭搶馬僅 {proj.get('n_contenders')} 匹 "
                f"（≤{proj.get('cold_need')}）。前領加分、後追略扣。"
            )
        else:
            st.caption(
                f"中性步速：爭搶馬 {proj.get('n_contenders')} 匹，介於冷熱之間；主要看追回指數。"
            )

        rows = []
        for _, row in runners.iterrows():
            hn = normalize_person_name(row["horse_name"])
            info = proj["by_horse"].get(hn, {})
            base = pace_df[pace_df[name_col] == hn]
            hit = not base.empty or bool(info)
            rec = base.iloc[0] if not base.empty else None
            rows.append({
                "馬號": row.get("horse_no"),
                "馬名": row.get("horse_name"),
                "檔位": row.get("draw"),
                "騎師": row.get("jockey_name"),
                "練馬師": row.get("trainer_name"),
                "命中": "✓" if hit and rec is not None else "✗",
                "跑法": info.get("running_style") or (rec["running_style"] if rec is not None and "running_style" in rec else "—"),
                "有效出賽": int(rec["actual_runs"]) if rec is not None else None,
                "平均早段": None if rec is None or "avg_early_pos" not in rec else round(float(rec["avg_early_pos"]), 2),
                "平均追回": None if rec is None or "avg_positions_gained" not in rec else round(float(rec["avg_positions_gained"]), 2),
                "追回Z": None if info.get("pace_z") is None and rec is None else round(float(info.get("pace_z", rec["z_score"])), 2),
                "早段速度Z": None if info.get("early_speed_z") is None else round(float(info["early_speed_z"]), 2),
                "形勢加權": round(float(info.get("scenario_bonus") or 0), 2),
                "步速採用分": None if info.get("pace_score") is None else round(float(info["pace_score"]), 2),
            })
        display_df = pd.DataFrame(rows)
        hits = int((display_df["命中"] == "✓").sum())
        st.caption(f"本場有步速資料：{hits}/{len(display_df)}")
        display_df = display_df.sort_values("步速採用分", ascending=False, na_position="last")
else:
    display_df = pace_df.sort_values("z_score", ascending=False).copy()
    rename = {
        "entity_name": "馬名",
        "horse_name": "馬名",
        "actual_runs": "有效出賽",
        "running_style": "跑法",
        "avg_early_pos": "平均早段",
        "avg_positions_gained": "平均追回",
        "adjusted_score": "平滑追回",
        "z_score": "追回Z",
        "early_speed_z": "早段速度Z",
    }
    display_df = display_df.rename(columns={k: v for k, v in rename.items() if k in display_df.columns})
    keep = [c for c in ["馬名", "跑法", "有效出賽", "平均早段", "平均追回", "平滑追回", "追回Z", "早段速度Z"] if c in display_df.columns]
    display_df = display_df[keep].head(80)

st.dataframe(display_df, hide_index=True, use_container_width=True, height=480)

with st.expander("優化說明"):
    st.markdown(
        """
- **已修正**：Postgres 的 `raw_json` 是 dict，舊版 `json.loads` 導致分段全空、算不出來。
- **已修正（形勢劇本）**：不再用「前 N 名 Z 加總 ≥2.5＝超快」（幾乎每場都超快）；改數「早段 Z ≥ 門檻」的爭搶馬數判定互燒／中性／偏慢。
- **評分**：追回 Z = 平滑後「早段名次−終點名次」；同場再依步速形勢加減前領／後追。
- **推論**：`WEIGHT_PACE` 計入追回 Z（形勢加權在排位頁可見；總分用追回 Z）。
- **後續可優化**：NLP 過濾假性腳軟／假性無追勢；距離帶分桶跑法。
"""
    )
