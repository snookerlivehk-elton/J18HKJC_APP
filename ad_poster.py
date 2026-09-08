"""
廣告輸出模組：預測快照後自動生成全賽日宣傳海報。

每次產出（固定檔名，下次覆蓋）：
  - ad_output/model.jpg   全賽日 · 模型勝率份額推介
  - ad_output/ai.jpg      全賽日 · AI 馬評份額推介
  - ad_output/copy.json   宣傳文案

單張 JPEG 目標 ≤ AD_OUTPUT_MAX_KB（預設 800KB）。
模版：assets/ad_templates/model_base.jpg、ai_base.jpg
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from score_share import select_picks_by_share, win_pick_count_from_shares

ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "assets" / "ad_templates"
LOGO_PATH = ROOT / "assets" / "j18_hk_logo.jpg"
BRAND_NAME = "J18.HK"
BUNDLED_FONT = ROOT / "assets" / "fonts" / "wqy-microhei.ttc"
FONT_CANDIDATES = [
    str(BUNDLED_FONT),
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]

POSTER_W = 1080
POSTER_H = 1920
MODEL_FILE = "model.jpg"
AI_FILE = "ai.jpg"
COPY_FILE = "copy.json"


def _max_bytes() -> int:
    try:
        from config import ModelConfig

        kb = int(getattr(ModelConfig, "AD_OUTPUT_MAX_KB", 800) or 800)
    except Exception:
        kb = int(os.getenv("AD_OUTPUT_MAX_KB") or 800)
    return max(100, kb) * 1024


def default_output_dir() -> Path:
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
    env = str(os.getenv("AD_FONT_PATH") or "").strip()
    candidates = ([env] if env else []) + FONT_CANDIDATES
    for p in candidates:
        if p and Path(p).is_file():
            return p
    return None


def _load_font(size: int):
    from PIL import ImageFont

    path = _find_font()
    if not path:
        raise RuntimeError(
            "找不到 CJK 字型：請確認 assets/fonts/wqy-microhei.ttc 已部署，"
            "或設定環境變數 AD_FONT_PATH"
        )
    last_err: Optional[Exception] = None
    for index in (0, 1):
        try:
            return ImageFont.truetype(path, size=int(size), index=index)
        except Exception as e:
            last_err = e
            continue
    try:
        return ImageFont.truetype(path, size=int(size))
    except Exception as e:
        raise RuntimeError(f"無法載入字型 {path}: {e or last_err}") from e


def font_status() -> Dict[str, Any]:
    path = _find_font()
    ok = False
    err = None
    if path:
        try:
            f = _load_font(40)
            ok = hasattr(f, "getbbox") or hasattr(f, "getsize")
        except Exception as e:
            err = str(e)
    return {"path": path, "ok": ok, "error": err}


def _template_path(track: str) -> Path:
    stem = "model_base" if track == "model" else "ai_base"
    for ext in (".jpg", ".jpeg", ".png"):
        p = TEMPLATE_DIR / f"{stem}{ext}"
        if p.is_file():
            return p
    return TEMPLATE_DIR / f"{stem}.jpg"


def ensure_default_templates() -> None:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    specs = {
        "model_base.jpg": ((8, 48, 32), (4, 18, 14)),
        "ai_base.jpg": ((10, 40, 52), (8, 16, 28)),
    }
    for name, (c0, c1) in specs.items():
        path = TEMPLATE_DIR / name
        png = TEMPLATE_DIR / name.replace(".jpg", ".png")
        if path.is_file() or png.is_file():
            continue
        w, h = POSTER_W, POSTER_H
        img = Image.new("RGB", (w, h), c0)
        px = img.load()
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(c0[0] * (1 - t) + c1[0] * t)
            g = int(c0[1] * (1 - t) + c1[1] * t)
            b = int(c0[2] * (1 - t) + c1[2] * t)
            for x in range(w):
                px[x, y] = (r, g, b)
        img.save(path, "JPEG", quality=82, optimize=True)


def build_payload_from_prediction(
    *,
    race_id: str,
    race_info,
    pred_df: pd.DataFrame,
    ai_map: Optional[Dict[int, Tuple]] = None,
) -> RaceAdPayload:
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
    date_s = payload.racing_date
    course = payload.course
    rn = payload.race_num
    title = f"第{rn}場" if rn is not None else payload.race_id
    if track == "model":
        picks = payload.model_picks
        headline = f"【{BRAND_NAME} 模型推介】{date_s} {course} {title}"
        line = "模型 · 勝率份額推介："
        empty = "本場暫無模型推介。"
    else:
        picks = payload.ai_picks
        headline = f"【{BRAND_NAME} AI 馬評】{date_s} {course} {title}"
        line = "AI 馬評 · 份額推介："
        empty = payload.ai_skip_message or "本場 AI 信心不足／暫無評價，不推。"

    if not picks:
        body = empty
    else:
        parts = [f"{p.tag} #{p.horse_no} {p.horse_name}（{p.share_pct:.0f}%）" for p in picks]
        body = "、".join(parts)

    cta = f"數據僅供參考，投注前請自行判斷。關注 {BRAND_NAME} 獲取更多賽日速覽。"
    full = f"{headline}\n{line}{body}\n\n{cta}"
    return {
        "track": track,
        "headline": headline,
        "picks_line": f"{line}{body}",
        "cta": cta,
        "full": full,
    }


def generate_meeting_copy(payloads: Sequence[RaceAdPayload], track: str) -> Dict[str, str]:
    if not payloads:
        return {"track": track, "headline": "", "full": "", "cta": ""}
    date_s = payloads[0].racing_date
    course = payloads[0].course
    if track == "model":
        headline = f"【{BRAND_NAME} 模型推介】{date_s} {course} 全賽日"
        label = "模型"
    else:
        headline = f"【{BRAND_NAME} AI 馬評】{date_s} {course} 全賽日"
        label = "AI 馬評"
    lines = []
    for p in payloads:
        rn = p.race_num if p.race_num is not None else "?"
        picks = p.model_picks if track == "model" else p.ai_picks
        if track == "ai" and p.ai_skipped and not picks:
            body = p.ai_skip_message or "信心不足略過"
        elif not picks:
            body = "暫無推介"
        else:
            body = "、".join(
                f"{x.tag}#{x.horse_no}{x.horse_name}({x.share_pct:.0f}%)" for x in picks
            )
        lines.append(f"R{rn} {body}")
    cta = f"數據僅供參考，投注前請自行判斷。關注 {BRAND_NAME} 獲取更多賽日速覽。"
    full = f"{headline}\n" + "\n".join(lines) + f"\n\n{cta}"
    return {"track": track, "headline": headline, "label": label, "full": full, "cta": cta}


def _draw_text(draw, xy, text, font, fill, *, anchor="lt"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _short_name(name: str, max_chars: int = 4) -> str:
    s = str(name or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars]


def _format_picks_line(picks: Sequence[PickItem], *, compact: bool) -> str:
    if not picks:
        return "—"
    parts = []
    name_len = 3 if compact else 4
    for p in picks:
        nm = _short_name(p.horse_name, name_len)
        if compact:
            parts.append(f"{'勝' if p.tag == '爭勝' else '推'}#{p.horse_no}{nm}{p.share_pct:.0f}%")
        else:
            parts.append(f"{p.tag} #{p.horse_no}{nm} {p.share_pct:.0f}%")
    return "  ".join(parts)


def _save_jpeg_under(path: Path, rgb, *, max_bytes: Optional[int] = None) -> Dict[str, Any]:
    """寫入 JPEG，必要時降品質／縮圖以壓到 max_bytes 內。"""
    from PIL import Image

    limit = max_bytes if max_bytes is not None else _max_bytes()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = rgb.convert("RGB")
    used_q = 82
    scale = 1.0
    data = b""
    for attempt in range(12):
        work = img
        if scale < 0.999:
            nw = max(640, int(img.width * scale))
            nh = max(960, int(img.height * scale))
            work = img.resize((nw, nh), Image.Resampling.LANCZOS)
        buf = BytesIO()
        work.save(buf, format="JPEG", quality=used_q, optimize=True)
        data = buf.getvalue()
        if len(data) <= limit:
            path.write_bytes(data)
            return {"bytes": len(data), "quality": used_q, "scale": scale, "path": str(path)}
        if used_q > 55:
            used_q -= 5
        else:
            scale *= 0.9
            used_q = max(50, used_q)
    path.write_bytes(data)
    return {"bytes": len(data), "quality": used_q, "scale": scale, "path": str(path), "over_limit": len(data) > limit}


def render_meeting_poster(
    payloads: Sequence[RaceAdPayload],
    *,
    track: str,
    out_path: Path,
) -> Dict[str, Any]:
    """全賽日推介 → 單張 1080×1920 海報。"""
    from PIL import Image, ImageDraw

    ensure_default_templates()
    tpl_path = _template_path(track)
    if not tpl_path.is_file():
        ensure_default_templates()
        tpl_path = _template_path(track)

    base = Image.open(tpl_path).convert("RGBA")
    target = (POSTER_W, POSTER_H)
    if base.size != target:
        base = base.resize(target, Image.Resampling.LANCZOS)

    races = sorted(
        list(payloads),
        key=lambda p: (
            int(p.race_num) if str(p.race_num).isdigit() else 999,
            str(p.race_id),
        ),
    )
    n = max(len(races), 1)
    compact = n >= 10
    very_compact = n >= 12

    # 字級隨場次數縮放（優先可讀）
    if very_compact:
        fs = {"brand": 42, "sub": 32, "date": 30, "race": 30, "pick": 26, "foot": 24}
        header_h, foot_h, gap = 170, 90, 6
    elif compact:
        fs = {"brand": 46, "sub": 34, "date": 32, "race": 34, "pick": 28, "foot": 24}
        header_h, foot_h, gap = 180, 96, 8
    elif n >= 8:
        fs = {"brand": 48, "sub": 36, "date": 32, "race": 36, "pick": 30, "foot": 26}
        header_h, foot_h, gap = 190, 100, 8
    else:
        fs = {"brand": 52, "sub": 38, "date": 34, "race": 38, "pick": 32, "foot": 26}
        header_h, foot_h, gap = 210, 104, 10

    font_brand = _load_font(fs["brand"])
    font_sub = _load_font(fs["sub"])
    font_date = _load_font(fs["date"])
    font_race = _load_font(fs["race"])
    font_pick = _load_font(fs["pick"])
    font_foot = _load_font(fs["foot"])

    accent = (212, 175, 106) if track == "model" else (120, 220, 210)
    white = (245, 245, 242)
    muted = (190, 198, 195)

    overlay = Image.new("RGBA", target, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(
        (28, 28, POSTER_W - 28, POSTER_H - 28),
        radius=24,
        fill=(0, 0, 0, 150),
    )
    base = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(base)

    if LOGO_PATH.is_file():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((110, 110) if compact else (130, 130), Image.Resampling.LANCZOS)
            base.paste(logo, (48, 44), logo)
            draw = ImageDraw.Draw(base)
        except Exception:
            pass

    _draw_text(draw, (190, 54), BRAND_NAME, font_brand, white)
    track_label = "模型 · 全賽日勝率份額" if track == "model" else "AI 馬評 · 全賽日份額"
    _draw_text(draw, (190, 104), track_label, font_sub, accent)

    date_s = races[0].racing_date if races else ""
    course = races[0].course if races else ""
    _draw_text(
        draw,
        (48, header_h - 24),
        f"{date_s}　{course}　共 {len(races)} 場",
        font_date,
        muted,
    )

    body_top = header_h + 4
    body_bottom = POSTER_H - foot_h
    avail = max(body_bottom - body_top, 200)
    slot = max(int((avail - gap * max(n - 1, 0)) / n), 72)

    def _wrap_picks(text: str, max_w: int) -> List[str]:
        if not text:
            return ["—"]
        if font_pick.getlength(text) <= max_w:
            return [text]
        units = text.split("  ")
        lines: List[str] = []
        cur = ""
        for u in units:
            trial = u if not cur else f"{cur}  {u}"
            if font_pick.getlength(trial) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = u
        if cur:
            lines.append(cur)
        if len(lines) > 2:
            second = "  ".join(lines[1:])
            while second and font_pick.getlength(second) > max_w:
                second = second[:-2]
            if second and not second.endswith("…"):
                second = second.rstrip(" ·") + "…"
            return [lines[0], second]
        return lines or ["—"]

    y = body_top
    max_w = POSTER_W - 120
    for race in races:
        picks = race.model_picks if track == "model" else race.ai_picks
        rn = race.race_num if race.race_num is not None else "?"
        meta = f"第{rn}場"
        if race.distance_m:
            meta += f" · {race.distance_m}m"

        bar_h = max(slot - 2, 56)
        bar = Image.new("RGBA", (POSTER_W - 80, bar_h), (255, 255, 255, 24))
        base.paste(bar, (40, y), bar)
        draw = ImageDraw.Draw(base)

        if track == "ai" and race.ai_skipped and not picks:
            pick_lines = [race.ai_skip_message or "AI 信心不足 · 本場略過"]
        else:
            pick_lines = _wrap_picks(
                _format_picks_line(picks, compact=compact or very_compact or n >= 8),
                max_w,
            )

        block_h = fs["race"] + 6 + len(pick_lines) * (fs["pick"] + 4)
        ty = y + max(8, (bar_h - block_h) // 2)
        _draw_text(draw, (56, ty), meta, font_race, accent)
        py = ty + fs["race"] + 4
        for line in pick_lines:
            col = muted if (track == "ai" and race.ai_skipped and not picks) else white
            _draw_text(draw, (56, py), line, font_pick, col)
            py += fs["pick"] + 4

        y += slot + gap

    foot = f"數據僅供參考 · 非投注建議 · {BRAND_NAME}"
    draw = ImageDraw.Draw(base)
    _draw_text(draw, (POSTER_W // 2, POSTER_H - 58), foot, font_foot, muted, anchor="mm")
    _draw_text(
        draw,
        (POSTER_W // 2, POSTER_H - 28),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        font_foot,
        (140, 145, 140),
        anchor="mm",
    )

    meta = _save_jpeg_under(Path(out_path), base.convert("RGB"))
    return meta


# 相容舊測試／呼叫：單場仍可渲染（內部轉成 1 場 meeting）
def render_poster_png(
    payload: RaceAdPayload,
    *,
    track: str,
    out_path: Path,
) -> Path:
    render_meeting_poster([payload], track=track, out_path=out_path)
    return Path(out_path)


def latest_paths(output_root: Optional[Path] = None) -> Dict[str, Path]:
    root = Path(output_root) if output_root else default_output_dir()
    return {
        "root": root,
        "model": root / MODEL_FILE,
        "ai": root / AI_FILE,
        "copy": root / COPY_FILE,
    }


def generate_ads_for_meeting_predictions(
    *,
    batch_id: str,
    race_items: Sequence[Dict[str, Any]],
    output_root: Optional[Path] = None,
    racing_date: str = "",
    course: str = "",
) -> Dict[str, Any]:
    """
    全賽日 → 僅 2 張海報（model.jpg / ai.jpg），寫入 output_root 根目錄並覆蓋舊檔。
    """
    out_root = Path(output_root) if output_root else default_output_dir()
    out_root.mkdir(parents=True, exist_ok=True)
    payloads: List[RaceAdPayload] = []
    errors: List[Dict[str, str]] = []

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
            payloads.append(payload)
        except Exception as e:
            errors.append({"race_id": rid, "error": str(e)})

    if not payloads:
        return {
            "ok": False,
            "error": "無有效場次可產出海報",
            "batch_id": batch_id,
            "errors": errors,
        }

    paths = latest_paths(out_root)
    model_meta = render_meeting_poster(payloads, track="model", out_path=paths["model"])
    ai_meta = render_meeting_poster(payloads, track="ai", out_path=paths["ai"])

    model_copy = generate_meeting_copy(payloads, "model")
    ai_copy = generate_meeting_copy(payloads, "ai")
    manifest = {
        "meeting": {
            "batch_id": batch_id,
            "racing_date": racing_date,
            "course": course,
            "n_races": len(payloads),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_file": MODEL_FILE,
            "ai_file": AI_FILE,
            "max_kb": _max_bytes() // 1024,
            "model_bytes": model_meta.get("bytes"),
            "ai_bytes": ai_meta.get("bytes"),
        },
        "model_copy": model_copy.get("full"),
        "ai_copy": ai_copy.get("full"),
        "races": [
            {
                "race_id": p.race_id,
                "race_no": p.race_num,
                "race_name": p.race_name,
                "distance": p.distance_m,
                "model_picks": [asdict(x) for x in p.model_picks],
                "ai_picks": [asdict(x) for x in p.ai_picks],
                "ai_skipped": p.ai_skipped,
            }
            for p in payloads
        ],
    }
    paths["copy"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": len(errors) == 0,
        "batch_id": batch_id,
        "n_races": len(payloads),
        "races_written": len(payloads),
        "files_written": 3,
        "errors": errors,
        "output_dir": str(out_root),
        "model_file": str(paths["model"]),
        "ai_file": str(paths["ai"]),
        "copy_json": str(paths["copy"]),
        "model_bytes": model_meta.get("bytes"),
        "ai_bytes": ai_meta.get("bytes"),
        "model_meta": model_meta,
        "ai_meta": ai_meta,
    }


def generate_ads_from_snapshot_batch(
    batch_id: str,
    *,
    output_root: Optional[Path] = None,
) -> Dict[str, Any]:
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

    payloads: List[RaceAdPayload] = []
    errors: List[Dict[str, str]] = []
    # 依 race_num 排序
    groups = list(snaps.groupby("race_id"))

    def _sort_key(item):
        rid, g = item
        rm = race_meta.get(str(rid), {})
        rn = rm.get("race_num")
        try:
            return (0, int(rn))
        except Exception:
            return (1, str(rid))

    for rid, g in sorted(groups, key=_sort_key):
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
            payloads.append(payload)
        except Exception as e:
            errors.append({"race_id": str(rid), "error": str(e)})

    # 轉成 generate_ads_for_meeting_predictions 可吃的假 items 太重；直接渲染
    if not payloads:
        return {"ok": False, "error": "無有效場次", "batch_id": batch_id, "errors": errors}

    out_root = Path(output_root) if output_root else default_output_dir()
    out_root.mkdir(parents=True, exist_ok=True)
    paths = latest_paths(out_root)
    model_meta = render_meeting_poster(payloads, track="model", out_path=paths["model"])
    ai_meta = render_meeting_poster(payloads, track="ai", out_path=paths["ai"])
    model_copy = generate_meeting_copy(payloads, "model")
    ai_copy = generate_meeting_copy(payloads, "ai")
    manifest = {
        "meeting": {
            "batch_id": batch_id,
            "racing_date": racing_date,
            "course": course,
            "n_races": len(payloads),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_file": MODEL_FILE,
            "ai_file": AI_FILE,
            "max_kb": _max_bytes() // 1024,
            "model_bytes": model_meta.get("bytes"),
            "ai_bytes": ai_meta.get("bytes"),
        },
        "model_copy": model_copy.get("full"),
        "ai_copy": ai_copy.get("full"),
        "races": [
            {
                "race_id": p.race_id,
                "race_no": p.race_num,
                "race_name": p.race_name,
                "distance": p.distance_m,
                "model_picks": [asdict(x) for x in p.model_picks],
                "ai_picks": [asdict(x) for x in p.ai_picks],
                "ai_skipped": p.ai_skipped,
            }
            for p in payloads
        ],
    }
    paths["copy"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": len(errors) == 0,
        "batch_id": batch_id,
        "n_races": len(payloads),
        "races_written": len(payloads),
        "files_written": 3,
        "errors": errors,
        "output_dir": str(out_root),
        "model_file": str(paths["model"]),
        "ai_file": str(paths["ai"]),
        "copy_json": str(paths["copy"]),
        "model_bytes": model_meta.get("bytes"),
        "ai_bytes": ai_meta.get("bytes"),
    }


def list_ad_batches(output_root: Optional[Path] = None) -> List[str]:
    """相容舊 UI：若根目錄有最新海報則回傳 ['latest']。"""
    root = Path(output_root) if output_root else default_output_dir()
    paths = latest_paths(root)
    if paths["model"].is_file() or paths["ai"].is_file() or paths["copy"].is_file():
        return ["latest"]
    return []


def load_copy_json(batch_dir: Path) -> Dict[str, Any]:
    # batch_dir 可能是 out_root 或 out_root/latest
    for cand in (Path(batch_dir) / COPY_FILE, Path(batch_dir).parent / COPY_FILE, Path(batch_dir)):
        if cand.name == COPY_FILE and cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                return {}
        if cand.is_dir():
            p = cand / COPY_FILE
            if p.is_file():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    return {}
    root = default_output_dir()
    p = root / COPY_FILE
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def list_batch_images(batch_dir: Path) -> List[Path]:
    root = Path(batch_dir)
    if root.name == "latest":
        root = root.parent
    paths = latest_paths(root)
    out = []
    for key in ("model", "ai"):
        if paths[key].is_file():
            out.append(paths[key])
    return out


def make_preview_jpeg(path: Path, *, max_width: int = 540, quality: int = 72) -> bytes:
    from PIL import Image

    im = Image.open(path).convert("RGB")
    w, h = im.size
    if w > max_width:
        nh = int(h * (max_width / float(w)))
        im = im.resize((max_width, nh), Image.Resampling.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def zip_batch_bytes(batch_dir: Path) -> bytes:
    import zipfile

    root = Path(batch_dir)
    if root.name == "latest":
        root = root.parent
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in (MODEL_FILE, AI_FILE, COPY_FILE):
            p = root / name
            if p.is_file():
                zf.write(p, arcname=p.name)
    return buf.getvalue()
