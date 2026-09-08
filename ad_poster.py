"""
廣告輸出模組：預測快照後自動生成宣傳海報 PNG + 文案。

每場產出：
  - {race_id}_model.png  模型 · 勝率份額推介
  - {race_id}_ai.png     AI 馬評 · 份額推介
  - {race_id}_copy.json  宣傳文案（模型／AI）

模版：assets/ad_templates/model_base.png、ai_base.png（可替換）
輸出：ad_output/{batch_id}/
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from score_share import select_picks_by_share, win_pick_count_from_shares

ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "assets" / "ad_templates"
LOGO_PATH = ROOT / "assets" / "j18ai_plus_logo.png"
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]


def default_output_dir() -> Path:
    """環境變數 AD_OUTPUT_DIR 優先，其次 ModelConfig.AD_OUTPUT_DIR，否則專案 ad_output/。"""
    custom = str(os.getenv("AD_OUTPUT_DIR") or "").strip()
    if not custom:
        try:
            from config import ModelConfig

            custom = str(getattr(ModelConfig, "AD_OUTPUT_DIR", "") or "").strip()
        except Exception:
            custom = ""
    return Path(custom) if custom else (ROOT / "ad_output")


OUTPUT_ROOT = default_output_dir()


@dataclass
class PickItem:
    horse_no: int
    horse_name: str
    share_pct: float
    tag: str  # 爭勝 / 推介


@dataclass
class RaceAdPayload:
    race_id: str
    racing_date: str
    course: str
    race_num: Any
    race_name: str = ""
    distance_m: Any = None
    track: str = ""
    model_picks: List[PickItem] = field(default_factory=list)
    ai_picks: List[PickItem] = field(default_factory=list)
    ai_skipped: bool = False
    ai_skip_message: str = ""


def _find_font() -> Optional[str]:
    for p in FONT_CANDIDATES:
        if p and Path(p).is_file():
            return p
    return None


def _load_font(size: int):
    from PIL import ImageFont

    path = _find_font()
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def ensure_default_templates() -> None:
    """若缺模版則畫簡單漸層底圖（可被 assets 內 PNG 覆蓋）。"""
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    specs = {
        "model_base.png": ((8, 48, 32), (4, 18, 14)),
        "ai_base.png": ((10, 40, 52), (8, 16, 28)),
    }
    for name, (c0, c1) in specs.items():
        path = TEMPLATE_DIR / name
        if path.is_file():
            continue
        w, h = 1080, 1920
        img = Image.new("RGB", (w, h), c0)
        px = img.load()
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(c0[0] * (1 - t) + c1[0] * t)
            g = int(c0[1] * (1 - t) + c1[1] * t)
            b = int(c0[2] * (1 - t) + c1[2] * t)
            for x in range(w):
                px[x, y] = (r, g, b)
        img.save(path, "PNG")


def build_payload_from_prediction(
    *,
    race_id: str,
    race_info,
    pred_df: pd.DataFrame,
    ai_map: Optional[Dict[int, Tuple]] = None,
) -> RaceAdPayload:
    """
    從 predict_race 結果 + AI map 組裝與賽日速覽一致的推介。
    ai_map: horse_no -> (ai_score, confidence, ai_combo)
    """
    from form_ai_picks import build_ai_picks, compute_ai_combo

    info = race_info.to_dict() if hasattr(race_info, "to_dict") else (dict(race_info) if race_info is not None else {})
    racing_date = str(info.get("racing_date", ""))[:10]
    course = str(info.get("course") or "")
    race_num = info.get("race_num")
    race_name = str(info.get("race_name") or info.get("title") or "")
    distance_m = info.get("distance_m")
    track = str(info.get("track") or "")

    df = pred_df.copy()
    if "模型勝率" in df.columns:
        df = df.sort_values("模型勝率", ascending=False).reset_index(drop=True)
    else:
        df = df.sort_values("總預測分", ascending=False).reset_index(drop=True)

    n = len(df)
    model_picks: List[PickItem] = []
    if n and "模型勝率" in df.columns:
        probs = [float(x or 0) for x in df["模型勝率"].tolist()]
        win_n = win_pick_count_from_shares(probs)
        pick_n = select_picks_by_share(probs)
        for i, (_, r) in enumerate(df.head(pick_n).iterrows(), start=1):
            pct = float(r["模型勝率%"]) if pd.notna(r.get("模型勝率%")) else float(r.get("模型勝率") or 0) * 100.0
            tag = "爭勝" if i <= win_n else "推介"
            model_picks.append(
                PickItem(
                    horse_no=int(r["馬號"]),
                    horse_name=str(r["馬名"]),
                    share_pct=round(pct, 1),
                    tag=tag,
                )
            )

    ai_map = ai_map or {}
    ai_rows = []
    for _, r in df.iterrows():
        hno = int(r["馬號"])
        sc, cf, combo = ai_map.get(hno, (None, None, None))
        if combo is None:
            combo = compute_ai_combo(sc, cf)
        ai_rows.append(
            {
                "horse_no": hno,
                "horse_name": r["馬名"],
                "ai_score": sc,
                "confidence": cf,
                "ai_combo": combo,
            }
        )
    ai_pack = build_ai_picks(ai_rows, n_runners=n)
    ai_picks: List[PickItem] = []
    ai_skipped = bool(ai_pack.get("skipped_low_confidence"))
    ai_msg = str(ai_pack.get("message") or "")
    if not ai_skipped:
        win_set = {int(x["horse_no"]) for x in (ai_pack.get("win") or []) if x.get("horse_no") is not None}
        place = (ai_pack.get("place") or []) or (ai_pack.get("win") or [])
        for i, x in enumerate(place, start=1):
            hno = int(x["horse_no"])
            pct = float(x.get("ai_share_pct") or 0)
            tag = "爭勝" if hno in win_set else "推介"
            ai_picks.append(
                PickItem(
                    horse_no=hno,
                    horse_name=str(x.get("horse_name") or ""),
                    share_pct=round(pct, 1),
                    tag=tag,
                )
            )

    return RaceAdPayload(
        race_id=str(race_id),
        racing_date=racing_date,
        course=course,
        race_num=race_num,
        race_name=race_name,
        distance_m=distance_m,
        track=track,
        model_picks=model_picks,
        ai_picks=ai_picks,
        ai_skipped=ai_skipped,
        ai_skip_message=ai_msg,
    )


def build_payload_from_snapshot_rows(
    race_id: str,
    rows: Sequence[dict],
    *,
    racing_date: str,
    course: str,
    race_num: Any = None,
    race_name: str = "",
) -> RaceAdPayload:
    """從已寫入快照的列（含 ai_*）重建推介。"""
    from form_ai_picks import build_ai_picks, compute_ai_combo

    df = pd.DataFrame(list(rows))
    if df.empty:
        return RaceAdPayload(
            race_id=race_id,
            racing_date=racing_date,
            course=course,
            race_num=race_num,
            race_name=race_name,
        )

    # 快照存的可能是 share% 欄位名稱已變；優先 model_win_prob
    if "model_win_prob" in df.columns:
        df = df.sort_values("model_win_prob", ascending=False).reset_index(drop=True)
    elif "total_score" in df.columns:
        df = df.sort_values("total_score", ascending=False).reset_index(drop=True)

    probs = [float(x or 0) for x in df.get("model_win_prob", pd.Series(dtype=float)).tolist()]
    n = len(df)
    model_picks: List[PickItem] = []
    if probs:
        win_n = win_pick_count_from_shares(probs)
        pick_n = select_picks_by_share(probs)
        for i, (_, r) in enumerate(df.head(pick_n).iterrows(), start=1):
            pct = float(r.get("model_win_prob") or 0) * 100.0
            model_picks.append(
                PickItem(
                    horse_no=int(r["horse_no"]),
                    horse_name=str(r.get("horse_name") or ""),
                    share_pct=round(pct, 1),
                    tag="爭勝" if i <= win_n else "推介",
                )
            )

    ai_rows = []
    for _, r in df.iterrows():
        sc = r.get("ai_score")
        cf = r.get("confidence")
        combo = r.get("ai_combo")
        if combo is None or (isinstance(combo, float) and pd.isna(combo)):
            combo = compute_ai_combo(sc, cf)
        ai_rows.append(
            {
                "horse_no": int(r["horse_no"]),
                "horse_name": r.get("horse_name"),
                "ai_score": None if sc is None or (isinstance(sc, float) and pd.isna(sc)) else float(sc),
                "confidence": None if cf is None or (isinstance(cf, float) and pd.isna(cf)) else float(cf),
                "ai_combo": None if combo is None or (isinstance(combo, float) and pd.isna(combo)) else float(combo),
            }
        )
    ai_pack = build_ai_picks(ai_rows, n_runners=n)
    ai_picks: List[PickItem] = []
    ai_skipped = bool(ai_pack.get("skipped_low_confidence"))
    if not ai_skipped:
        win_set = {int(x["horse_no"]) for x in (ai_pack.get("win") or []) if x.get("horse_no") is not None}
        place = (ai_pack.get("place") or []) or (ai_pack.get("win") or [])
        for x in place:
            hno = int(x["horse_no"])
            ai_picks.append(
                PickItem(
                    horse_no=hno,
                    horse_name=str(x.get("horse_name") or ""),
                    share_pct=round(float(x.get("ai_share_pct") or 0), 1),
                    tag="爭勝" if hno in win_set else "推介",
                )
            )

    return RaceAdPayload(
        race_id=str(race_id),
        racing_date=str(racing_date)[:10],
        course=str(course),
        race_num=race_num,
        race_name=race_name or "",
        model_picks=model_picks,
        ai_picks=ai_picks,
        ai_skipped=ai_skipped,
        ai_skip_message=str(ai_pack.get("message") or ""),
    )


def generate_copy(payload: RaceAdPayload, track: str) -> Dict[str, str]:
    """宣傳文案（繁中）。track=model|ai"""
    date_s = payload.racing_date
    course = payload.course
    rn = payload.race_num
    title = f"第{rn}場" if rn is not None else payload.race_id
    if track == "model":
        picks = payload.model_picks
        headline = f"【J18AI Plus+ 模型推介】{date_s} {course} {title}"
        line = "模型 · 勝率份額推介："
        empty = "本場暫無模型推介。"
    else:
        picks = payload.ai_picks
        headline = f"【J18AI Plus+ AI 馬評】{date_s} {course} {title}"
        line = "AI 馬評 · 份額推介："
        empty = payload.ai_skip_message or "本場 AI 信心不足／暫無評價，不推。"

    if not picks:
        body = empty
    else:
        parts = [f"{p.tag} #{p.horse_no} {p.horse_name}（{p.share_pct:.0f}%）" for p in picks]
        body = "、".join(parts)

    cta = "數據僅供參考，投注前請自行判斷。關注 J18AI Plus+ 獲取更多賽日速覽。"
    full = f"{headline}\n{line}{body}\n\n{cta}"
    return {
        "track": track,
        "headline": headline,
        "picks_line": f"{line}{body}",
        "cta": cta,
        "full": full,
    }


def _draw_text(draw, xy, text, font, fill, *, anchor="lt"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def render_poster_png(
    payload: RaceAdPayload,
    *,
    track: str,
    out_path: Path,
) -> Path:
    """
    在海報模版上疊加品牌 Logo、場次資訊與推介列表，輸出高品質 PNG。
    track: model | ai
    """
    from PIL import Image, ImageDraw

    ensure_default_templates()
    tpl_name = "model_base.png" if track == "model" else "ai_base.png"
    tpl_path = TEMPLATE_DIR / tpl_name
    if not tpl_path.is_file():
        ensure_default_templates()

    base = Image.open(tpl_path).convert("RGBA")
    # 統一輸出尺寸（Instagram story 友好）
    target = (1080, 1920)
    if base.size != target:
        base = base.resize(target, Image.Resampling.LANCZOS)

    # 輕微壓暗中下區以利文字
    overlay = Image.new("RGBA", target, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((60, 420, 1020, 1680), fill=(0, 0, 0, 110))
    base = Image.alpha_composite(base, overlay)

    draw = ImageDraw.Draw(base)
    font_brand = _load_font(42)
    font_title = _load_font(56)
    font_sub = _load_font(34)
    font_row = _load_font(40)
    font_tag = _load_font(28)
    font_small = _load_font(26)

    accent = (212, 175, 106) if track == "model" else (120, 220, 210)
    white = (245, 245, 242)
    muted = (200, 205, 200)

    # Logo
    if LOGO_PATH.is_file():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((220, 220), Image.Resampling.LANCZOS)
            base.paste(logo, (80, 80), logo)
        except Exception:
            pass

    brand = "J18AI Plus+"
    _draw_text(draw, (320, 120), brand, font_brand, white)
    track_label = "模型 · 勝率份額" if track == "model" else "AI 馬評 · 份額"
    _draw_text(draw, (320, 175), track_label, font_sub, accent)

    rn = payload.race_num
    title = f"第 {rn} 場" if rn is not None else payload.race_id
    meta_line = f"{payload.racing_date}　{payload.course}"
    if payload.distance_m:
        meta_line += f"　{payload.distance_m}米"
    if payload.track:
        meta_line += f"　{payload.track}"
    _draw_text(draw, (80, 340), title, font_title, white)
    if payload.race_name:
        _draw_text(draw, (80, 410), str(payload.race_name)[:28], font_sub, muted)
        _draw_text(draw, (80, 460), meta_line, font_small, muted)
        y0 = 540
    else:
        _draw_text(draw, (80, 410), meta_line, font_sub, muted)
        y0 = 500

    picks = payload.model_picks if track == "model" else payload.ai_picks
    if track == "ai" and payload.ai_skipped and not picks:
        _draw_text(
            draw,
            (80, y0 + 40),
            payload.ai_skip_message or "本場 AI 信心不足，暫不推介",
            font_row,
            muted,
        )
    else:
        for i, p in enumerate(picks):
            y = y0 + i * 130
            # row card
            card = Image.new("RGBA", (920, 110), (255, 255, 255, 28))
            base.paste(card, (80, y), card)
            draw = ImageDraw.Draw(base)
            tag_col = accent if p.tag == "爭勝" else (180, 190, 185)
            _draw_text(draw, (110, y + 35), p.tag, font_tag, tag_col)
            _draw_text(
                draw,
                (220, y + 28),
                f"#{p.horse_no}  {p.horse_name}",
                font_row,
                white,
            )
            _draw_text(
                draw,
                (920, y + 32),
                f"{p.share_pct:.0f}%",
                font_row,
                accent,
                anchor="rt",
            )

    foot = "數據僅供參考 · 非投注建議"
    draw = ImageDraw.Draw(base)
    _draw_text(draw, (540, 1820), foot, font_small, muted, anchor="mm")
    _draw_text(
        draw,
        (540, 1865),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        font_small,
        (140, 145, 140),
        anchor="mm",
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rgb = base.convert("RGB")
    rgb.save(out_path, "PNG", optimize=True)
    return out_path


def render_race_ads(
    payload: RaceAdPayload,
    *,
    batch_id: str,
    output_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """為單場生成 model/ai 兩張 PNG + copy json。"""
    root = Path(output_root or default_output_dir()) / str(batch_id)
    root.mkdir(parents=True, exist_ok=True)
    rid = payload.race_id
    model_path = root / f"{rid}_model.png"
    ai_path = root / f"{rid}_ai.png"
    copy_path = root / f"{rid}_copy.json"

    render_poster_png(payload, track="model", out_path=model_path)
    render_poster_png(payload, track="ai", out_path=ai_path)

    model_copy = generate_copy(payload, "model")
    ai_copy = generate_copy(payload, "ai")
    copies = {
        "race_id": rid,
        "racing_date": payload.racing_date,
        "course": payload.course,
        "race_num": payload.race_num,
        "race_name": payload.race_name,
        "distance": payload.distance_m,
        "model": model_copy,
        "ai": ai_copy,
        "model_copy": model_copy.get("full"),
        "ai_copy": ai_copy.get("full"),
        "model_file": model_path.name,
        "ai_file": ai_path.name,
        "model_picks": [asdict(p) for p in payload.model_picks],
        "ai_picks": [asdict(p) for p in payload.ai_picks],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    copy_path.write_text(json.dumps(copies, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "race_id": rid,
        "race_no": payload.race_num,
        "race_name": payload.race_name,
        "distance": payload.distance_m,
        "model_png": str(model_path),
        "ai_png": str(ai_path),
        "copy_json": str(copy_path),
        "model_copy": model_copy.get("full"),
        "ai_copy": ai_copy.get("full"),
        "model_file": model_path.name,
        "ai_file": ai_path.name,
        "model_picks_n": len(payload.model_picks),
        "ai_picks_n": len(payload.ai_picks),
    }


def _write_batch_manifest(
    *,
    batch_id: str,
    root: Path,
    results: Sequence[Dict[str, Any]],
    racing_date: str = "",
    course: str = "",
) -> Path:
    races = []
    for r in results:
        races.append(
            {
                "race_id": r.get("race_id"),
                "race_no": r.get("race_no"),
                "race_name": r.get("race_name") or "",
                "distance": r.get("distance"),
                "model_file": r.get("model_file"),
                "ai_file": r.get("ai_file"),
                "model_copy": r.get("model_copy"),
                "ai_copy": r.get("ai_copy"),
            }
        )
    manifest = {
        "meeting": {
            "batch_id": batch_id,
            "racing_date": racing_date,
            "course": course,
            "n_races": len(races),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "races": races,
    }
    path = root / "copy.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def generate_ads_for_meeting_predictions(
    *,
    batch_id: str,
    race_items: Sequence[Dict[str, Any]],
    output_root: Optional[Path] = None,
    racing_date: str = "",
    course: str = "",
) -> Dict[str, Any]:
    """
    race_items: list of {
      race_id, race_info, pred_df, ai_map?
    }
    """
    out_root = Path(output_root) if output_root else default_output_dir()
    batch_dir = out_root / str(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    results = []
    errors = []
    for item in race_items:
        rid = str(item["race_id"])
        try:
            payload = build_payload_from_prediction(
                race_id=rid,
                race_info=item.get("race_info"),
                pred_df=item["pred_df"],
                ai_map=item.get("ai_map") or {},
            )
            if not racing_date and payload.racing_date:
                racing_date = payload.racing_date
            if not course and payload.course:
                course = payload.course
            results.append(
                render_race_ads(payload, batch_id=batch_id, output_root=out_root)
            )
        except Exception as e:
            errors.append({"race_id": rid, "error": str(e)})

    manifest_path = _write_batch_manifest(
        batch_id=batch_id,
        root=batch_dir,
        results=results,
        racing_date=racing_date,
        course=course,
    )
    files_written = len(results) * 3 + (1 if results else 0)  # 2 png + copy per race + manifest
    return {
        "ok": len(errors) == 0,
        "batch_id": batch_id,
        "n_races": len(results),
        "races_written": len(results),
        "files_written": files_written,
        "results": results,
        "errors": errors,
        "output_dir": str(batch_dir),
        "copy_json": str(manifest_path),
    }


def generate_ads_from_snapshot_batch(
    batch_id: str,
    *,
    output_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """從已寫入 DB 的預測快照重產海報（不重跑推論）。"""
    from sqlalchemy import text

    from factor_calibration import FactorCalibration

    cal = FactorCalibration()
    batches = cal.list_batches()
    if batches.empty or batch_id not in set(batches["batch_id"].astype(str)):
        return {"ok": False, "error": f"找不到批次 {batch_id}", "batch_id": batch_id}
    meta = batches[batches["batch_id"].astype(str) == str(batch_id)].iloc[0]
    racing_date = str(meta.get("racing_date") or "")[:10]
    course = str(meta.get("course") or "")

    snaps = pd.read_sql(
        text("SELECT * FROM prediction_snapshots WHERE batch_id = :b"),
        cal.engine,
        params={"b": batch_id},
    )
    if snaps.empty:
        return {"ok": False, "error": "此批次無快照列", "batch_id": batch_id}

    race_meta: Dict[str, dict] = {}
    try:
        from inference_engine import InferenceEngine

        up = InferenceEngine().get_upcoming_races()
        if up is not None and not up.empty:
            for _, r in up.iterrows():
                race_meta[str(r["race_id"])] = {
                    "race_num": r.get("race_num"),
                    "race_name": r.get("race_name") or r.get("title") or "",
                    "distance_m": r.get("distance_m"),
                    "track": r.get("track") or "",
                }
    except Exception:
        pass

    out_root = Path(output_root) if output_root else default_output_dir()
    results = []
    errors = []
    for rid, g in snaps.groupby("race_id"):
        try:
            rm = race_meta.get(str(rid), {})
            payload = build_payload_from_snapshot_rows(
                str(rid),
                g.to_dict(orient="records"),
                racing_date=racing_date,
                course=course,
                race_num=rm.get("race_num"),
                race_name=str(rm.get("race_name") or ""),
            )
            if rm.get("distance_m") is not None:
                payload.distance_m = rm.get("distance_m")
            if rm.get("track"):
                payload.track = str(rm.get("track"))
            results.append(
                render_race_ads(payload, batch_id=batch_id, output_root=out_root)
            )
        except Exception as e:
            errors.append({"race_id": str(rid), "error": str(e)})

    batch_dir = out_root / str(batch_id)
    manifest_path = _write_batch_manifest(
        batch_id=batch_id,
        root=batch_dir,
        results=results,
        racing_date=racing_date,
        course=course,
    )
    return {
        "ok": len(errors) == 0,
        "batch_id": batch_id,
        "n_races": len(results),
        "races_written": len(results),
        "files_written": len(results) * 3 + (1 if results else 0),
        "results": results,
        "errors": errors,
        "output_dir": str(batch_dir),
        "copy_json": str(manifest_path),
    }


def list_ad_batches(output_root: Optional[Path] = None) -> List[str]:
    root = Path(output_root) if output_root else default_output_dir()
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_dir() and (list(p.glob("*.png")) or (p / "copy.json").is_file()):
            out.append(p.name)
    return out


def load_copy_json(batch_dir: Path) -> Dict[str, Any]:
    path = Path(batch_dir) / "copy.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def list_batch_outputs(batch_id: str, output_root: Optional[Path] = None) -> List[Path]:
    d = (Path(output_root) if output_root else default_output_dir()) / batch_id
    if not d.is_dir():
        return []
    return sorted(d.glob("*.png")) + sorted(d.glob("*_copy.json"))
