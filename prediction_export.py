"""
賽前預測對外 payload：展示用欄位 + 模型勝率 + AI + Kelly 輔助計算。
外部平台帶入即時獨贏賠率（小數）即可算值搏／凱利指數。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from factor_calibration import place_cutoff
from form_ai_analyst import FormAIAnalyst
from inference_engine import InferenceEngine


def _unpack_predict(race_id: str):
    """predict_race 早期失敗可能只回 2-tuple；成功為 (df, race_info, meta)。"""
    eng = InferenceEngine()
    result = eng.predict_race(race_id)
    if len(result) == 3:
        return result[0], result[1], result[2] or {}
    df = result[0] if result else pd.DataFrame()
    info = result[1] if len(result) > 1 else None
    return df, info, {}


def kelly_fraction(p: float, decimal_odds: float, *, fraction: float = 1.0) -> float:
    """
    凱利建議倉位 f* = (b·p − q) / b；b=o−1，q=1−p。
    decimal_odds 為小數賠率（例如 5.0 = 4/1）。
    負期望時回傳 0；fraction 可做半凱利（0.5）。
    """
    try:
        p = float(p)
        o = float(decimal_odds)
        frac = float(fraction)
    except (TypeError, ValueError):
        return 0.0
    if p <= 0 or p >= 1 or o <= 1.0 or frac <= 0:
        return 0.0
    b = o - 1.0
    q = 1.0 - p
    f = (b * p - q) / b
    if f <= 0:
        return 0.0
    return round(min(f * frac, 1.0), 6)


def edge_ratio(p: float, decimal_odds: float) -> Optional[float]:
    """模型勝率 / 隱含勝率 − 1；>0 表示模型相對市場偏樂觀。"""
    try:
        p = float(p)
        o = float(decimal_odds)
    except (TypeError, ValueError):
        return None
    if o <= 1.0 or p <= 0:
        return None
    implied = 1.0 / o
    if implied <= 0:
        return None
    return round(p / implied - 1.0, 6)


def _safe_info(info) -> dict:
    if info is None:
        return {}
    if hasattr(info, "to_dict"):
        d = info.to_dict()
    else:
        d = dict(info)
    out = {}
    for k, v in d.items():
        if hasattr(v, "item"):
            try:
                out[k] = v.item()
                continue
            except Exception:
                pass
        if hasattr(v, "isoformat"):
            out[k] = str(v)[:10] if "date" in str(k).lower() else str(v)
        else:
            out[k] = v
    return out


def _ai_map(race_id: str) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    try:
        df = FormAIAnalyst().load_ai_for_race(race_id)
        if df is None or df.empty:
            return out
        for _, a in df.iterrows():
            hno = int(a["horse_no"])
            sc = float(a["ai_score"]) if pd.notna(a.get("ai_score")) else None
            cf = float(a["confidence"]) if pd.notna(a.get("confidence")) else None
            combo = None if sc is None or cf is None else round(sc * cf, 4)
            out[hno] = {
                "ai_score": sc,
                "confidence": cf,
                "ai_combo": combo,
                "summary": a.get("summary"),
            }
    except Exception:
        pass
    return out


def build_race_prediction(
    race_id: str,
    *,
    win_odds: Optional[Dict[int, float]] = None,
    kelly_fraction_scale: float = 1.0,
    include_factors: bool = True,
) -> Dict[str, Any]:
    """
    單場賽前預測 JSON。
    win_odds: {馬號: 小數獨贏賠率}，由外部平台帶入即時賠率。
    """
    df, race_info, meta = _unpack_predict(race_id)
    info = _safe_info(race_info)
    if df is None or df.empty:
        return {
            "ok": False,
            "error": "no_prediction",
            "race_id": race_id,
            "race": info,
        }

    if "模型勝率" in df.columns:
        df = df.sort_values("模型勝率", ascending=False).reset_index(drop=True)
    ai = _ai_map(race_id)
    n = len(df)
    place_n = place_cutoff(n)

    runners: List[dict] = []
    for _, row in df.iterrows():
        hno = int(row["馬號"]) if pd.notna(row["馬號"]) else None
        p = float(row["模型勝率"]) if pd.notna(row.get("模型勝率")) else None
        item = {
            "horse_no": hno,
            "horse_name": row.get("馬名"),
            "draw": int(row["檔位"]) if pd.notna(row.get("檔位")) else None,
            "jockey": row.get("騎師"),
            "trainer": row.get("練馬師"),
            "handicap_weight": float(row["負磅"]) if pd.notna(row.get("負磅")) else None,
            "horse_weight": float(row["體重"]) if pd.notna(row.get("體重")) else None,
            "total_score": float(row["總預測分"]) if pd.notna(row.get("總預測分")) else None,
            "model_win_prob": p,
            "model_win_prob_pct": float(row["模型勝率%"]) if pd.notna(row.get("模型勝率%")) else None,
            "pred_rank": int(row["預測排名"]) if pd.notna(row.get("預測排名")) else None,
            "ai": ai.get(hno) if hno is not None else None,
        }
        if include_factors:
            item["factors"] = {
                "jockey": float(row["騎師分"]) if pd.notna(row.get("騎師分")) else None,
                "trainer": float(row["練馬師分"]) if pd.notna(row.get("練馬師分")) else None,
                "synergy": float(row["騎練分"]) if pd.notna(row.get("騎練分")) else None,
                "draw": float(row["檔位分"]) if pd.notna(row.get("檔位分")) else None,
                "form": float(row["近績分"]) if pd.notna(row.get("近績分")) else None,
                "pace": float(row["步速分"]) if pd.notna(row.get("步速分")) else None,
                "speed": float(row["速度分"]) if pd.notna(row.get("速度分")) else None,
                "speed_guide": float(row["SG貢獻"]) if pd.notna(row.get("SG貢獻")) else None,
            }
        if win_odds and hno is not None and hno in win_odds:
            o = win_odds[hno]
            item["win_odds_decimal"] = float(o)
            item["kelly_fraction"] = kelly_fraction(p or 0, o, fraction=kelly_fraction_scale)
            item["edge_vs_market"] = edge_ratio(p or 0, o)
            item["implied_prob"] = round(1.0 / float(o), 6) if float(o) > 0 else None
        runners.append(item)

    # 爭勝 1～2；入圍前 place_n
    win_n = 1
    if n >= 2 and runners[0].get("model_win_prob") and runners[1].get("model_win_prob"):
        if runners[1]["model_win_prob"] >= runners[0]["model_win_prob"] * 0.70:
            win_n = 2

    def _slim(r: dict) -> dict:
        return {
            "horse_no": r["horse_no"],
            "horse_name": r["horse_name"],
            "pred_rank": r["pred_rank"],
            "model_win_prob": r["model_win_prob"],
            "model_win_prob_pct": r["model_win_prob_pct"],
            "ai_combo": (r.get("ai") or {}).get("ai_combo"),
            "kelly_fraction": r.get("kelly_fraction"),
            "edge_vs_market": r.get("edge_vs_market"),
        }

    return {
        "ok": True,
        "race_id": race_id,
        "race": {
            "racing_date": str(info.get("racing_date", ""))[:10],
            "course": info.get("course"),
            "race_num": info.get("race_num"),
            "distance_m": info.get("distance_m"),
            "track": info.get("track"),
            "class": info.get("class"),
            "race_name": info.get("race_name"),
            "n_runners": n,
            "place_cutoff": place_n,
        },
        "meta": {
            "bucket_id": meta.get("bucket_id"),
            "band_bucket_id": meta.get("band_bucket_id"),
            "match_rate": meta.get("match_rate"),
            "softmax_temperature": meta.get("softmax_temperature"),
            "softmax_within_race_z": meta.get("softmax_within_race_z"),
            "win_prob_sum": meta.get("win_prob_sum"),
            "kelly_fraction_scale": kelly_fraction_scale,
        },
        "picks": {
            "win": [_slim(r) for r in runners[:win_n]],
            "place": [_slim(r) for r in runners[:place_n]],
        },
        "runners": runners,
        "kelly": {
            "formula": "f*=(b*p-q)/b ; b=o-1 ; q=1-p ; o=decimal win odds ; p=model_win_prob",
            "odds_convention": "decimal (e.g. 5.0 means stake 1 return 5 incl. stake)",
            "note": "Pass win_odds to compute kelly_fraction per runner. Use half-Kelly via kelly_fraction_scale=0.5.",
        },
    }


def list_upcoming_meeting(racing_date: Optional[str] = None, course: Optional[str] = None) -> Dict[str, Any]:
    eng = InferenceEngine()
    races = eng.get_upcoming_races()
    if races.empty:
        return {"ok": True, "meetings": [], "races": []}
    df = races.copy()
    df["_d"] = df["racing_date"].astype(str).str[:10]
    if racing_date:
        df = df[df["_d"] == racing_date[:10]]
    if course:
        df = df[df["course"].astype(str).str.upper() == course.upper()]
    df = df.sort_values(["_d", "course", "race_num"])
    meetings = []
    for (d, c), g in df.groupby(["_d", "course"], sort=True):
        meetings.append(
            {
                "racing_date": d,
                "course": c,
                "n_races": int(len(g)),
                "race_ids": g["race_id"].astype(str).tolist(),
            }
        )
    race_list = []
    for _, r in df.iterrows():
        race_list.append(
            {
                "race_id": str(r["race_id"]),
                "racing_date": str(r["racing_date"])[:10],
                "course": r.get("course"),
                "race_num": int(r["race_num"]) if pd.notna(r.get("race_num")) else None,
                "distance_m": r.get("distance_m"),
                "track": r.get("track"),
                "class": r.get("class"),
            }
        )
    return {"ok": True, "meetings": meetings, "races": race_list}


def build_meeting_predictions(
    racing_date: str,
    course: str,
    *,
    kelly_fraction_scale: float = 1.0,
    include_factors: bool = False,
) -> Dict[str, Any]:
    listed = list_upcoming_meeting(racing_date, course)
    races_out = []
    for r in listed.get("races") or []:
        races_out.append(
            build_race_prediction(
                r["race_id"],
                kelly_fraction_scale=kelly_fraction_scale,
                include_factors=include_factors,
            )
        )
    return {
        "ok": True,
        "racing_date": racing_date[:10],
        "course": course.upper(),
        "n_races": len(races_out),
        "races": races_out,
    }


def parse_odds_map(raw: Optional[str]) -> Dict[int, float]:
    """
    解析 query：horse_no:odds,horse_no:odds
    例：3:5.5,7:8.0
    """
    out: Dict[int, float] = {}
    if not raw:
        return out
    for part in str(raw).split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        a, b = part.split(":", 1)
        try:
            out[int(a.strip())] = float(b.strip())
        except ValueError:
            continue
    return out
