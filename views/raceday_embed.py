"""
賽日速覽（電腦版公開嵌入）— 無需登入。
專為 j18.hk/pc 右手邊區域寛度；由 ui_app ?embed=raceday 進入。
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from bucket_utils import format_class_display
from form_ai_analyst import FormAIAnalyst
from form_ai_picks import build_ai_picks, build_fused_picks, compute_ai_combo
from inference_engine import InferenceEngine
from score_share import select_picks_by_share, win_pick_count_from_shares
from config import ModelConfig
from ui_theme import inject_raceday_embed_css


def _fmt_ai_display(share_pct) -> str:
    if share_pct is None:
        return "—"
    try:
        return f"{float(share_pct):.0f}%"
    except (TypeError, ValueError):
        return "—"


_RADAR_COLS = [
    ("騎師分", "騎師"),
    ("練馬師分", "練馬師"),
    ("騎練分", "騎練"),
    ("檔位分", "檔位"),
    ("近績分", "近績"),
    ("步速分", "步速"),
    ("速度分", "速度"),
    ("SG貢獻", "速勢"),  # 與 radar_charts 軸標一致
]


def _radar_norm_matrix(pred_df: pd.DataFrame) -> dict:
    """同場每軸 min→0、max→1（與 radar_charts / embed payload 一致）。"""
    out = {}
    for col, _lab in _RADAR_COLS:
        if col not in pred_df.columns:
            out[col] = pd.Series(0.5, index=pred_df.index)
            continue
        s = pd.to_numeric(pred_df[col], errors="coerce")
        valid = s.dropna()
        if valid.empty:
            out[col] = pd.Series(0.5, index=pred_df.index)
            continue
        lo, hi = float(valid.min()), float(valid.max())
        if hi - lo < 1e-9:
            out[col] = pd.Series(0.5, index=pred_df.index)
        else:
            out[col] = ((s - lo) / (hi - lo)).fillna(0.5)
    return out


def _radar_svg(values: list, labels: list) -> str:
    import math

    if not labels or len(values) != len(labels):
        return '<div class="radar-empty">暫無雷達</div>'
    cx, cy, R, n = 70, 66, 44, len(labels)
    pts = []
    for i, v in enumerate(values):
        try:
            vv = max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            vv = 0.5
        ang = -math.pi / 2 + (i * 2 * math.pi) / n
        pts.append((cx + R * vv * math.cos(ang), cy + R * vv * math.sin(ang)))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    rings = "".join(
        f'<circle cx="{cx}" cy="{cy}" r="{R * s:.1f}" fill="none" '
        f'stroke="rgba(255,255,255,0.14)" stroke-width="1"/>'
        for s in (0.33, 0.66, 1.0)
    )
    spokes = ""
    labs = ""
    for i, lab in enumerate(labels):
        ang = -math.pi / 2 + (i * 2 * math.pi) / n
        x2 = cx + R * math.cos(ang)
        y2 = cy + R * math.sin(ang)
        spokes += (
            f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="rgba(255,255,255,0.10)" stroke-width="1"/>'
        )
        lx = cx + (R + 13) * math.cos(ang)
        ly = cy + (R + 13) * math.sin(ang)
        labs += (
            f'<text x="{lx:.1f}" y="{ly:.1f}" fill="rgba(242,242,242,0.52)" '
            f'font-size="7.5" text-anchor="middle" dominant-baseline="middle">{lab}</text>'
        )
    return (
        '<svg viewBox="0 0 140 132" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        f"{rings}{spokes}"
        f'<polygon points="{poly}" fill="rgba(62,207,142,0.30)" stroke="#3ecf8e" stroke-width="1.7"/>'
        f"{labs}</svg>"
    )


def _fmt_ai_head(ai_row, share_pct) -> str:
    """AI 評價標題：場內份額；原始 × 信心 = combo。"""
    bits = []
    if share_pct is not None:
        try:
            bits.append(f"場內份額 {float(share_pct):.0f}%")
        except (TypeError, ValueError):
            pass
    if ai_row is not None and pd.notna(ai_row.get("ai_score")) and pd.notna(ai_row.get("confidence")):
        sc = float(ai_row["ai_score"])
        cf = float(ai_row["confidence"])
        combo = compute_ai_combo(sc, cf)
        if combo is None:
            combo = sc * cf
        bits.append(
            f"原始 {sc:+.2f} × 信心 {cf * 100:.0f}% = {combo:+.2f}"
        )
    if not bits:
        return ""
    return f' <span class="meta">({"；".join(bits)})</span>'


def _pick_row_html(tag: str, name_left: str, right: str, *, tag_class: str = "") -> str:
    cls = f' class="tag {tag_class}"' if tag_class else ' class="tag"'
    return (
        f'<div class="rd-pick-row">'
        f'<div class="left"><span{cls}>{tag}</span>'
        f'<span class="nm">{name_left}</span></div>'
        f'<div class="right">{right}</div>'
        f"</div>"
    )


def _deduped_pick_html(
    win_picks: list,
    place_picks: list,
    *,
    empty_msg: str,
    pct_key: str,
    pct_fmt: str = "{:.0f}%",
) -> str:
    win_picks = list(win_picks or [])
    place_picks = list(place_picks or [])
    if not win_picks and not place_picks:
        return f'<div class="rd-pick-empty">{empty_msg}</div>'

    def _pct(row) -> str:
        try:
            return pct_fmt.format(float(row.get(pct_key)))
        except (TypeError, ValueError):
            return "—"

    def _name(row) -> str:
        hno = row.get("horse_no")
        name = row.get("horse_name") or ""
        return f"{hno} {name}".strip()

    parts = []
    for i, r in enumerate(win_picks, start=1):
        parts.append(_pick_row_html(f"爭勝{i}", _name(r), _pct(r)))
    rest = place_picks[len(win_picks) :]
    for i, r in enumerate(rest, start=1):
        parts.append(_pick_row_html(f"位置{i}", _name(r), _pct(r), tag_class="pos"))
    return "".join(parts) if parts else f'<div class="rd-pick-empty">{empty_msg}</div>'


@st.cache_data(ttl=90, show_spinner="計算本場…")
def _predict(race_id: str):
    eng = InferenceEngine()
    df, info, meta = eng.predict_race(race_id)
    info_dict = info.to_dict() if hasattr(info, "to_dict") else (dict(info) if info is not None else {})
    safe = {}
    for k, v in info_dict.items():
        if hasattr(v, "item"):
            try:
                safe[k] = v.item()
                continue
            except Exception:
                pass
        safe[k] = str(v) if hasattr(v, "isoformat") else v
    return {
        "columns": list(df.columns) if df is not None and not df.empty else [],
        "df": df.to_dict(orient="list") if df is not None and not df.empty else {},
        "info": safe,
        "meta": meta or {},
    }


def load_pred(race_id: str):
    p = _predict(race_id)
    if not p["columns"]:
        return pd.DataFrame(), p["info"], p["meta"]
    return pd.DataFrame(p["df"], columns=p["columns"]), p["info"], p["meta"]


def render_raceday_embed() -> None:
    """公開電腦版賽日速覽（無登入、無導航）。"""
    inject_raceday_embed_css()

    st.markdown(
        """
<div class="rd-hero">
  <div class="mark">J18 · Race Day</div>
  <h1>賽日速覽</h1>
  <p>選場次 · 綜合推介 · 模型／AI 對照</p>
</div>
""",
        unsafe_allow_html=True,
    )

    engine = InferenceEngine()
    races_df = engine.get_upcoming_races()
    if races_df.empty:
        st.warning("尚無賽日排位，請稍後再試。")
        return

    scores_ok = not engine.calc.load_factor_scores(
        factor_types=["JOCKEY", "TRAINER", "SYNERGY", "DRAW", "HORSE", "PACE", "SPEED"]
    ).empty
    if not scores_ok:
        st.error("尚無因子分數，請稍後再試。")
        return

    races_df = races_df.copy()
    races_df["_date"] = races_df["racing_date"].astype(str)
    dates = sorted(races_df["_date"].unique().tolist())
    date_sel = st.selectbox("賽日", dates, index=len(dates) - 1, label_visibility="collapsed")
    day = races_df[races_df["_date"] == date_sel].sort_values("race_num")
    course = str(day.iloc[0]["course"])
    st.caption(f"{date_sel}　{course}　共 {len(day)} 場")

    if "rd_embed_race_id" not in st.session_state:
        st.session_state.rd_embed_race_id = str(day.iloc[0]["race_id"])

    day_ids = set(day["race_id"].astype(str))
    if st.session_state.rd_embed_race_id not in day_ids:
        st.session_state.rd_embed_race_id = str(day.iloc[0]["race_id"])

    nums = day["race_num"].astype(int).tolist()
    num_to_rid = {int(r["race_num"]): str(r["race_id"]) for _, r in day.iterrows()}
    cur_num = int(
        day[day["race_id"].astype(str) == st.session_state.rd_embed_race_id].iloc[0]["race_num"]
    )

    picked = st.pills(
        "場次",
        options=nums,
        selection_mode="single",
        default=cur_num,
        format_func=lambda n: str(n),
        label_visibility="collapsed",
        key="rd_embed_race_pills",
    )
    if picked is None:
        picked = cur_num
    if int(picked) != cur_num:
        st.session_state.rd_embed_race_id = num_to_rid[int(picked)]
        st.rerun()

    race_id = st.session_state.rd_embed_race_id
    race_row = day[day["race_id"].astype(str) == race_id].iloc[0]
    pred_df, _info, meta = load_pred(race_id)

    ai_map = {}
    try:
        ai_df = FormAIAnalyst().load_ai_for_race(race_id)
        if not ai_df.empty:
            for _, a in ai_df.iterrows():
                ai_map[int(a["horse_no"])] = a
    except Exception:
        pass

    if pred_df.empty:
        st.warning("此場暫無預測結果。")
        return

    if "模型勝率" in pred_df.columns:
        pred_df = pred_df.sort_values("模型勝率", ascending=False).reset_index(drop=True)
    else:
        pred_df = pred_df.sort_values("總預測分", ascending=False).reset_index(drop=True)

    n_runners = len(pred_df)
    win_n = 1
    pick_n = min(2, n_runners)
    if n_runners >= 1 and "模型勝率" in pred_df.columns:
        probs = [float(x or 0) for x in pred_df["模型勝率"].tolist()]
        win_n = win_pick_count_from_shares(probs)
        pick_n = select_picks_by_share(probs)
    elif n_runners >= 2:
        win_n = 2
        pick_n = min(int(getattr(ModelConfig, "PICK_MAX", 5)), n_runners)

    ai_rows = []
    for _, r in pred_df.iterrows():
        hno = int(r["馬號"])
        ai = ai_map.get(hno)
        sc = float(ai["ai_score"]) if ai is not None and pd.notna(ai.get("ai_score")) else None
        cf = float(ai["confidence"]) if ai is not None and pd.notna(ai.get("confidence")) else None
        ai_rows.append(
            {
                "horse_no": hno,
                "horse_name": r["馬名"],
                "ai_score": sc,
                "confidence": cf,
                "ai_combo": compute_ai_combo(sc, cf),
                "pred_rank": int(r["預測排名"]) if pd.notna(r.get("預測排名")) else None,
                "model_win_prob": float(r["模型勝率"]) if pd.notna(r.get("模型勝率")) else None,
            }
        )
    ai_picks = build_ai_picks(ai_rows, n_runners=n_runners)
    ai_pick_hnos = {
        int(x["horse_no"])
        for x in (ai_picks.get("win") or []) + (ai_picks.get("place") or [])
        if x.get("horse_no") is not None
    }
    ai_share_by_hno = {
        int(r["horse_no"]): r.get("ai_share_pct")
        for r in (ai_picks.get("ranked") or [])
        if r.get("horse_no") is not None and r.get("ai_share_pct") is not None
    }
    fused_picks = build_fused_picks(ai_rows, n_runners=n_runners)
    fused_pick_hnos = {
        int(x["horse_no"])
        for x in (fused_picks.get("win") or []) + (fused_picks.get("place") or [])
        if x.get("horse_no") is not None
    }
    fused_share_by_hno = {
        int(r["horse_no"]): r.get("fused_share_pct")
        for r in (fused_picks.get("ranked") or [])
        if r.get("horse_no") is not None and r.get("fused_share_pct") is not None
    }

    def _model_deduped_html() -> str:
        win_rows = []
        for _, r in pred_df.head(win_n).iterrows():
            win_rows.append(
                {
                    "horse_no": int(r["馬號"]),
                    "horse_name": r["馬名"],
                    "model_pct": float(r["模型勝率%"]) if pd.notna(r.get("模型勝率%")) else 0.0,
                }
            )
        place_rows = []
        for _, r in pred_df.head(pick_n).iterrows():
            place_rows.append(
                {
                    "horse_no": int(r["馬號"]),
                    "horse_name": r["馬名"],
                    "model_pct": float(r["模型勝率%"]) if pd.notna(r.get("模型勝率%")) else 0.0,
                }
            )
        return _deduped_pick_html(
            win_rows, place_rows, empty_msg="—", pct_key="model_pct", pct_fmt="{:.1f}%"
        )

    fuse_empty = "尚無綜合推介"
    if fused_picks.get("fallback_model_only"):
        fuse_empty = fused_picks.get("message") or "退回純模型"
    fuse_html = _deduped_pick_html(
        fused_picks.get("win") or [],
        fused_picks.get("place") or [],
        empty_msg=fuse_empty,
        pct_key="fused_share_pct",
    )
    ai_empty = "尚無 AI 評價"
    if ai_picks.get("skipped_low_confidence"):
        ai_empty = ai_picks.get("message") or "信心不足，本場不推"
    ai_html = _deduped_pick_html(
        ai_picks.get("win") or [],
        ai_picks.get("place") or [],
        empty_msg=ai_empty,
        pct_key="ai_share_pct",
    )
    model_html = _model_deduped_html()

    fuse_note = ""
    if fused_picks.get("fallback_model_only"):
        fuse_note = " · 無 AI 時退回模型"
    elif fused_picks.get("available"):
        fuse_note = f" · α={float(fused_picks.get('alpha') or 0):.2f}"

    cls_disp = format_class_display(race_row.get("class"))
    race_name = race_row.get("race_name") or ""
    pace_label = meta.get("pace_scenario") or "未知"

    st.markdown(
        f"""
<div class="rd-panel">
  <div class="rd-meta">
    <div class="title">第 {int(race_row['race_num'])} 場{' · ' + race_name if race_name else ''}</div>
    <div class="grid">
      <div>日期 <b>{race_row['racing_date']}</b></div>
      <div>場地 <b>{race_row['course']}</b></div>
      <div>賽道 <b>{race_row.get('track') or '-'}</b></div>
      <div>距離 <b>{race_row.get('distance_m') or '-'} 米</b></div>
      <div>班次 <b>{cls_disp}</b></div>
      <div>預計步速 <b>{pace_label}</b></div>
      <div>匹配 <b>{meta.get('match_rate', 0):.0%}</b></div>
      <div>覆蓋 <b>{(meta.get('avg_model_coverage') or 0):.0%}{' · provisional' if meta.get('provisional') else ''}</b></div>
    </div>
  </div>
</div>
<div class="rd-tips">
  <div class="rd-fuse">
    <div class="col-title">綜合推介{fuse_note}</div>
    {fuse_html}
    <div class="note">主顯示＝模型×AI 綜合。本場 {n_runners} 匹</div>
  </div>
  <div class="rd-side">
    <div class="col-title">模型 · 勝率份額</div>
    {model_html}
  </div>
  <div class="rd-side ai">
    <div class="col-title">AI 馬評 · 份額</div>
    {ai_html}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # 一馬一列 + 可排序
    sort_opts = {
        "綜合份額高→低": "fused",
        "模型份額高→低": "model",
        "AI 份額高→低": "ai",
        "預測排名": "rank",
        "馬號": "no",
        "檔位": "draw",
    }
    sort_label = st.selectbox("出馬排序", list(sort_opts.keys()), index=0, key="rd_embed_sort")
    sort_key = sort_opts[sort_label]

    rows = []
    for _, row in pred_df.iterrows():
        hno = int(row["馬號"])
        rows.append(
            {
                "row": row,
                "rank": int(row["預測排名"]) if pd.notna(row.get("預測排名")) else 999,
                "hno": hno,
                "model": float(row["模型勝率%"]) if pd.notna(row.get("模型勝率%")) else -1.0,
                "fused": float(fused_share_by_hno.get(hno) or -1),
                "ai": float(ai_share_by_hno.get(hno) or -1),
                "draw": float(row["檔位"]) if pd.notna(row.get("檔位")) else 999,
            }
        )
    if sort_key == "model":
        rows.sort(key=lambda x: (-x["model"], x["hno"]))
    elif sort_key == "ai":
        rows.sort(key=lambda x: (-x["ai"], x["hno"]))
    elif sort_key == "rank":
        rows.sort(key=lambda x: (x["rank"], x["hno"]))
    elif sort_key == "no":
        rows.sort(key=lambda x: x["hno"])
    elif sort_key == "draw":
        rows.sort(key=lambda x: (x["draw"], x["hno"]))
    else:
        rows.sort(key=lambda x: (-x["fused"], x["hno"]))

    radar_norm = _radar_norm_matrix(pred_df)
    radar_labels = [lab for _, lab in _RADAR_COLS]

    for item in rows:
        row = item["row"]
        rank = item["rank"] if item["rank"] != 999 else 0
        hno = item["hno"]
        top_cls = "top1" if rank == 1 else ("pick" if hno in fused_pick_hnos or hno in ai_pick_hnos else "")
        name = row["馬名"]
        prob = float(row["模型勝率%"]) if pd.notna(row.get("模型勝率%")) else 0.0
        jockey = row.get("騎師") or "-"
        trainer = row.get("練馬師") or "-"
        draw = row.get("檔位")
        hw = row.get("負磅")
        bw = row.get("體重")
        total = row.get("總預測分")
        ai = ai_map.get(hno)
        ai_pct = ai_share_by_hno.get(hno)

        def _fmt(v, suffix=""):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return "-"
            try:
                return f"{float(v):.0f}{suffix}" if float(v) == int(float(v)) else f"{float(v):.1f}{suffix}"
            except (TypeError, ValueError):
                return str(v)

        # 該列在 pred_df 的 index（排序後可能與 iterrows index 不同）
        idx = row.name if hasattr(row, "name") else None
        vals = []
        for col, _ in _RADAR_COLS:
            series = radar_norm.get(col)
            if series is None or idx is None or idx not in series.index:
                vals.append(0.5)
            else:
                try:
                    vals.append(float(series.loc[idx]))
                except Exception:
                    vals.append(0.5)
        radar_html = _radar_svg(vals, radar_labels)

        ai_head_meta = _fmt_ai_head(ai, ai_pct)
        summary = ""
        if ai is not None and pd.notna(ai.get("summary")):
            summary = str(ai.get("summary") or "").strip()
        score_line = ""
        if total is not None and not (isinstance(total, float) and pd.isna(total)):
            try:
                score_line = f"{name}系統統計總預測分{float(total):.2f}"
            except (TypeError, ValueError):
                score_line = ""
        if summary and score_line:
            ai_body = f"{score_line}。{summary}"
        else:
            ai_body = summary or score_line
        ai_body_html = (
            f'<div class="ai-body">{ai_body}</div>'
            if ai_body
            else '<div class="ai-empty">尚無 AI 評價</div>'
        )

        st.markdown(
            f"""
<div class="horse-card {top_cls}">
  <div class="hc-info">
    <div class="hc-id">
      <span class="hc-rank">#{rank or "—"}</span>
      <div class="hc-name"><span class="hc-no">{hno}</span>{name}</div>
      <div class="hc-sub">騎師 {jockey} · 練馬師 {trainer}</div>
      <div class="hc-sub">檔位 {_fmt(draw)} · 負磅 {_fmt(hw)} · 馬重 {_fmt(bw)}</div>
    </div>
    <div class="hc-prob">
      <div class="pct">{prob:.1f}%</div>
      <div class="lbl">模型份額</div>
    </div>
  </div>
  <div class="hc-radar">{radar_html}</div>
  <div class="hc-ai">
    <div class="ai-head">AI 評價{ai_head_meta}</div>
    {ai_body_html}
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    st.caption(
        "公開嵌入頁 · 無需登入 · 專為 j18.hk/pc 右手邊。"
        f"推介動態最多 {getattr(ModelConfig, 'PICK_MAX', 5)} 匹。"
    )
