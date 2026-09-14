"""
賽日速覽（公開嵌入）payload：與 views/raceday 對齊的綜合推介＋場次資料。
供 FastAPI /embed 與測試使用；不含 Kelly／賠率。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from bucket_utils import format_class_display
from form_ai_picks import build_ai_picks, build_fused_picks, compute_ai_combo
from inference_engine import InferenceEngine
from prediction_export import build_race_prediction, list_upcoming_meeting
from score_share import select_picks_by_share, win_pick_count_from_shares


def _course_label(course: Any) -> str:
    c = str(course or "").upper()
    if c == "HV":
        return "跑馬地"
    if c == "ST":
        return "沙田"
    return str(course or "")


def build_public_meetings(
    racing_date: Optional[str] = None,
    course: Optional[str] = None,
) -> Dict[str, Any]:
    raw = list_upcoming_meeting(racing_date, course)
    meetings = []
    for m in raw.get("meetings") or []:
        meetings.append(
            {
                **m,
                "course_label": _course_label(m.get("course")),
            }
        )
    races = []
    for r in raw.get("races") or []:
        races.append(
            {
                **r,
                "course_label": _course_label(r.get("course")),
                "class_display": format_class_display(r.get("class")),
            }
        )
    return {"ok": True, "meetings": meetings, "races": races}


def build_public_race_view(race_id: str) -> Dict[str, Any]:
    """
    單場公開速覽：綜合推介＋模型／AI 對照＋出馬列表（含雷達因子；無 Kelly）。
    """
    base = build_race_prediction(race_id, include_factors=True)
    if not base.get("ok"):
        return base

    runners_in = base.get("runners") or []
    n = len(runners_in)
    ai_rows = []
    for r in runners_in:
        a = r.get("ai") or {}
        ai_rows.append(
            {
                "horse_no": r.get("horse_no"),
                "horse_name": r.get("horse_name"),
                "ai_score": a.get("ai_score"),
                "confidence": a.get("confidence"),
                "ai_combo": a.get("ai_combo")
                if a.get("ai_combo") is not None
                else compute_ai_combo(a.get("ai_score"), a.get("confidence")),
                "pred_rank": r.get("pred_rank"),
                "model_win_prob": r.get("model_win_prob"),
            }
        )
    fused = build_fused_picks(ai_rows, n_runners=n)
    ai_picks = build_ai_picks(ai_rows, n_runners=n)

    probs = [float(r.get("model_win_prob") or 0) for r in runners_in]
    win_n = win_pick_count_from_shares(probs) if probs else 1
    pick_n = select_picks_by_share(probs) if probs else 0

    fused_share_map = {
        int(x["horse_no"]): x.get("fused_share_pct")
        for x in (fused.get("ranked") or [])
        if x.get("horse_no") is not None
    }
    ai_share_map = {
        int(x["horse_no"]): x.get("ai_share_pct")
        for x in (ai_picks.get("ranked") or [])
        if x.get("horse_no") is not None
    }
    fused_pick_hnos = {
        int(x["horse_no"])
        for x in (fused.get("win") or []) + (fused.get("place") or [])
        if x.get("horse_no") is not None
    }

    # 雷達軸：同場 min→0、max→1（與 radar_charts 一致）
    radar_keys = [
        ("jockey", "騎師"),
        ("trainer", "練馬師"),
        ("synergy", "騎練"),
        ("draw", "檔位"),
        ("form", "近績"),
        ("pace", "步速"),
        ("speed", "速度"),
        ("speed_guide", "速勢"),
    ]
    factor_series: Dict[str, List[Optional[float]]] = {k: [] for k, _ in radar_keys}
    for r in runners_in:
        f = r.get("factors") or {}
        for k, _ in radar_keys:
            v = f.get(k)
            try:
                factor_series[k].append(float(v) if v is not None else None)
            except (TypeError, ValueError):
                factor_series[k].append(None)

    def _norm_axis(vals: List[Optional[float]]) -> List[float]:
        valid = [v for v in vals if v is not None]
        if not valid:
            return [0.5] * len(vals)
        lo, hi = min(valid), max(valid)
        if hi - lo < 1e-9:
            return [0.5 if v is not None else 0.5 for v in vals]
        out = []
        for v in vals:
            if v is None:
                out.append(0.5)
            else:
                out.append((v - lo) / (hi - lo))
        return out

    radar_norm = {k: _norm_axis(factor_series[k]) for k, _ in radar_keys}

    runners_out: List[dict] = []
    for i, r in enumerate(runners_in):
        hno = r.get("horse_no")
        try:
            hno_i = int(hno) if hno is not None else None
        except (TypeError, ValueError):
            hno_i = None
        a = r.get("ai") or {}
        sc = a.get("ai_score")
        cf = a.get("confidence")
        try:
            combo = (
                round(float(sc) * float(cf), 4)
                if sc is not None and cf is not None
                else None
            )
        except (TypeError, ValueError):
            combo = None
        factors = r.get("factors") or {}
        runners_out.append(
            {
                "horse_no": hno_i,
                "horse_name": r.get("horse_name"),
                "draw": r.get("draw"),
                "jockey": r.get("jockey"),
                "trainer": r.get("trainer"),
                "handicap_weight": r.get("handicap_weight"),
                "horse_weight": r.get("horse_weight"),
                "pred_rank": r.get("pred_rank"),
                "total_score": r.get("total_score"),
                "model_win_prob": r.get("model_win_prob"),
                "model_win_prob_pct": r.get("model_win_prob_pct"),
                "model_coverage": r.get("model_coverage"),
                "ai_score": sc,
                "ai_confidence": cf,
                "ai_combo": combo if combo is not None else a.get("ai_combo"),
                "ai_summary": a.get("summary"),
                "ai_share_pct": ai_share_map.get(hno_i) if hno_i is not None else None,
                "fused_share_pct": fused_share_map.get(hno_i) if hno_i is not None else None,
                "is_fused_pick": hno_i in fused_pick_hnos if hno_i is not None else False,
                "factors": factors,
                "radar": {
                    "labels": [lab for _, lab in radar_keys],
                    "values": [radar_norm[k][i] for k, _ in radar_keys],
                },
            }
        )

    race = dict(base.get("race") or {})
    race["course_label"] = _course_label(race.get("course"))
    race["class_display"] = format_class_display(race.get("class"))

    meta = base.get("meta") or {}
    return {
        "ok": True,
        "race_id": race_id,
        "race": race,
        "meta": {
            "match_rate": meta.get("match_rate"),
            "avg_model_coverage": meta.get("avg_model_coverage"),
            "provisional": meta.get("provisional"),
            "expected_pace": race.get("expected_pace") or meta.get("pace_scenario"),
        },
        "picks": {
            "fused": {
                "available": bool(fused.get("available")),
                "fallback_model_only": bool(fused.get("fallback_model_only")),
                "alpha": fused.get("alpha"),
                "message": fused.get("message"),
                "win": fused.get("win") or [],
                "place": fused.get("place") or [],
            },
            "model": {
                "win": (base.get("picks") or {}).get("win") or [],
                "place": (base.get("picks") or {}).get("place") or [],
                "win_n": win_n,
                "pick_n": pick_n,
            },
            "ai": {
                "available": bool(ai_picks.get("available")),
                "skipped_low_confidence": bool(ai_picks.get("skipped_low_confidence")),
                "message": ai_picks.get("message"),
                "win": ai_picks.get("win") or [],
                "place": ai_picks.get("place") or [],
            },
        },
        "runners": runners_out,
        "radar_axes": [{"key": k, "label": lab} for k, lab in radar_keys],
    }


def default_meeting_selection() -> Dict[str, Any]:
    """選最近一個有排位的賽日作為預設。"""
    listed = build_public_meetings()
    meetings = listed.get("meetings") or []
    if not meetings:
        return {"ok": True, "meeting": None, "races": []}
    # list_upcoming 已按日期排序；取最後一個（最近／即將）
    m = meetings[-1]
    races = [
        r
        for r in (listed.get("races") or [])
        if r.get("racing_date") == m.get("racing_date")
        and str(r.get("course") or "").upper() == str(m.get("course") or "").upper()
    ]
    races.sort(key=lambda x: int(x.get("race_num") or 0))
    return {"ok": True, "meeting": m, "races": races}


def health_payload(version: str) -> Dict[str, Any]:
    eng = InferenceEngine()
    try:
        races = eng.get_upcoming_races()
        n = 0 if races is None or races.empty else int(len(races))
    except Exception:
        n = -1
    return {
        "status": "ok",
        "service": "j18-raceday-embed",
        "version": version,
        "upcoming_races": n,
    }
