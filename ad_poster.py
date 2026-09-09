"""
廣告輸出模組：依公司原海報風格生成全賽日推介圖。

每次產出（固定檔名，下次覆蓋）：
  - ad_output/model.png   全賽日 · 模型推介（最多 4 匹／場）
  - ad_output/ai.png      全賽日 · AI 馬評推介（最多 4 匹／場）
  - ad_output/copy.json   宣傳文案

版式：嚴格跟從 assets/ad_templates/company/ 藍／米色原圖（header+動態表身+footer）。
高度隨場次數拉長；PNG ≤ AD_OUTPUT_MAX_KB（預設 2048）。每次隨機選一種色調。
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from score_share import select_picks_by_share, win_pick_count_from_shares

ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "assets" / "ad_templates"
COMPANY_DIR = TEMPLATE_DIR / "company"
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

MODEL_FILE = "model.png"
AI_FILE = "ai.png"
COPY_FILE = "copy.json"

# 公司原圖量測（1280 寬）
POSTER_W = 1280
TABLE_LEFT = 66
TABLE_RIGHT = 1214
COL_RACE = (66, 240)
COL_PICKS = [(240, 484), (484, 728), (728, 972), (972, 1216)]
ROW_H = 72
THEMES = ("blue", "beige")
WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _max_bytes() -> int:
    try:
        from config import ModelConfig

        kb = int(getattr(ModelConfig, "AD_OUTPUT_MAX_KB", 2048) or 2048)
    except Exception:
        kb = int(os.getenv("AD_OUTPUT_MAX_KB") or 2048)
    return max(100, kb) * 1024


def _pick_max() -> int:
    try:
        from config import ModelConfig

        return int(getattr(ModelConfig, "AD_OUTPUT_PICK_MAX", None) or getattr(ModelConfig, "PICK_MAX", 4) or 4)
    except Exception:
        return 4


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
    picks = _limit_picks(payload.model_picks if track == "model" else payload.ai_picks)
    if track == "model":
        headline = f"【{BRAND_NAME} 模型推介】{date_s} {course} {title}"
        line = "模型推介："
        empty = "本場暫無模型推介。"
    else:
        headline = f"【{BRAND_NAME} AI 馬評】{date_s} {course} {title}"
        line = "AI 馬評推介："
        empty = payload.ai_skip_message or "本場 AI 信心不足／暫無評價，不推。"

    if track == "ai" and payload.ai_skipped and not picks:
        body = empty
    elif not picks:
        body = empty
    else:
        # 嚴格跟公司原圖：只顯示「馬號 馬名」，不含勝率
        parts = [f"{p.horse_no} {p.horse_name}" for p in picks]
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
        picks = _limit_picks(p.model_picks if track == "model" else p.ai_picks)
        if track == "ai" and p.ai_skipped and not picks:
            body = p.ai_skip_message or "信心不足略過"
        elif not picks:
            body = "暫無推介"
        else:
            body = "、".join(f"{x.horse_no} {x.horse_name}" for x in picks)
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


def _save_png_under(path: Path, rgb, *, max_bytes: Optional[int] = None) -> Dict[str, Any]:
    """寫入 PNG，必要時縮圖以壓到 max_bytes 內（公司規格 2MB 以下）。"""
    from PIL import Image

    limit = max_bytes if max_bytes is not None else _max_bytes()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = rgb.convert("RGB")
    scale = 1.0
    data = b""
    for _ in range(10):
        work = img
        if scale < 0.999:
            nw = max(720, int(img.width * scale))
            nh = max(720, int(img.height * scale))
            work = img.resize((nw, nh), Image.Resampling.LANCZOS)
        buf = BytesIO()
        work.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        if len(data) <= limit:
            path.write_bytes(data)
            return {"bytes": len(data), "scale": scale, "path": str(path), "format": "PNG"}
        scale *= 0.88
    path.write_bytes(data)
    return {
        "bytes": len(data),
        "scale": scale,
        "path": str(path),
        "format": "PNG",
        "over_limit": len(data) > limit,
    }


def _save_jpeg_under(path: Path, rgb, *, max_bytes: Optional[int] = None) -> Dict[str, Any]:
    """相容舊呼叫；公司海報改走 PNG。"""
    return _save_png_under(path.with_suffix(".png") if path.suffix.lower() in {".jpg", ".jpeg"} else path, rgb, max_bytes=max_bytes)


def _theme_paths(theme: str) -> Dict[str, Path]:
    return {
        "header": COMPANY_DIR / f"{theme}_header.jpg",
        "footer": COMPANY_DIR / f"{theme}_footer.jpg",
        "full": COMPANY_DIR / f"{theme}_full.jpg",
    }


def _venue_label(course: str) -> str:
    c = str(course or "").upper()
    if c == "ST":
        return "沙田"
    if c == "HV":
        return "谷草"
    return str(course or "")


def _meeting_date_line(racing_date: str, course: str) -> str:
    """例：2026/09/09 星期三 谷草 (夜)"""
    ds = str(racing_date or "")[:10].replace("-", "/")
    wd = ""
    try:
        dt = datetime.strptime(str(racing_date or "")[:10], "%Y-%m-%d")
        wd = WEEKDAY_ZH[dt.weekday()]
    except Exception:
        pass
    venue = _venue_label(course)
    # HV 夜賽為主；ST 日賽為主（無確切場次時用慣例括號）
    session = "夜" if str(course or "").upper() == "HV" else "日"
    parts = [p for p in (ds, wd, f"{venue} ({session})" if venue else "") if p]
    return " ".join(parts)


def _paint_date_pill(header: "Image.Image", theme: str, date_line: str) -> None:
    """覆蓋原圖日期條並重寫當期賽事資料。"""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(header)
    font = _load_font(34)
    # 量測自原圖：左上日期膠囊區
    if theme == "blue":
        box = (48, 188, 620, 258)
        fill = (150, 195, 220)
        text_fill = (255, 255, 255)
    else:
        box = (48, 188, 620, 258)
        fill = (232, 210, 170)
        text_fill = (70, 45, 30)
    draw.rounded_rectangle(box, radius=22, fill=fill)
    # 垂直置中
    bbox = font.getbbox(date_line)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = box[0] + 28
    ty = box[1] + (box[3] - box[1] - th) // 2 - 2
    draw.text((tx, ty), date_line, font=font, fill=text_fill)


def _cell_text(pick: Optional[PickItem]) -> str:
    if not pick:
        return ""
    name = str(pick.horse_name or "").strip()
    if len(name) > 6:
        name = name[:6]
    return f"{pick.horse_no} {name}"


def _limit_picks(picks: Sequence[PickItem]) -> List[PickItem]:
    n = _pick_max()
    return list(picks)[:n]


def render_meeting_poster(
    payloads: Sequence[RaceAdPayload],
    *,
    track: str,
    out_path: Path,
    theme: Optional[str] = None,
) -> Dict[str, Any]:
    """
    公司原海報風格：header（含賽事資料）+ 動態場次表（每場最多 4 匹）+ footer。
    高度隨場數拉長；theme=blue|beige，未指定則隨機。
    """
    from PIL import Image, ImageDraw

    theme = theme if theme in THEMES else random.choice(THEMES)
    paths = _theme_paths(theme)
    if not paths["header"].is_file() or not paths["footer"].is_file():
        raise FileNotFoundError(f"缺少公司海報模版：{COMPANY_DIR}")

    races = sorted(
        list(payloads),
        key=lambda p: (
            int(p.race_num) if str(p.race_num).isdigit() else 999,
            str(p.race_id),
        ),
    )
    n = max(len(races), 1)
    header = Image.open(paths["header"]).convert("RGB")
    footer = Image.open(paths["footer"]).convert("RGB")
    w = POSTER_W
    if header.width != w:
        header = header.resize((w, int(header.height * w / header.width)), Image.Resampling.LANCZOS)
    if footer.width != w:
        footer = footer.resize((w, int(footer.height * w / footer.width)), Image.Resampling.LANCZOS)

    date_line = _meeting_date_line(
        races[0].racing_date if races else "",
        races[0].course if races else "",
    )
    _paint_date_pill(header, theme, date_line)

    table_h = n * ROW_H + 8
    canvas_h = header.height + table_h + footer.height
    if theme == "blue":
        page_bg = (210, 230, 240)
        row_a = (255, 255, 255)
        row_b = (236, 244, 248)
        grid = (190, 205, 215)
        race_bg = (210, 225, 235)
        race_fg = (40, 90, 140)
        text_fg = (45, 40, 35)
    else:
        page_bg = (230, 210, 175)
        row_a = (255, 255, 255)
        row_b = (245, 236, 220)
        grid = (210, 195, 175)
        race_bg = (235, 220, 195)
        race_fg = (90, 55, 30)
        text_fg = (55, 40, 30)

    canvas = Image.new("RGB", (w, canvas_h), page_bg)
    canvas.paste(header, (0, 0))
    # 表身白底卡片延續
    body_top = header.height
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((TABLE_LEFT - 4, body_top - 2, TABLE_RIGHT + 4, body_top + table_h), fill=row_a)

    font_race = _load_font(40)
    font_pick = _load_font(30)

    for i, race in enumerate(races):
        y0 = body_top + i * ROW_H
        y1 = y0 + ROW_H
        fill = row_a if i % 2 == 0 else row_b
        draw.rectangle((TABLE_LEFT, y0, TABLE_RIGHT, y1), fill=fill)
        # 場次欄
        draw.rectangle((COL_RACE[0], y0, COL_RACE[1], y1), fill=race_bg)
        rn = race.race_num if race.race_num is not None else i + 1
        rn_s = str(rn)
        bb = font_race.getbbox(rn_s)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        draw.text(
            (
                (COL_RACE[0] + COL_RACE[1] - tw) // 2,
                y0 + (ROW_H - th) // 2 - 2,
            ),
            rn_s,
            font=font_race,
            fill=race_fg,
        )
        picks = _limit_picks(race.model_picks if track == "model" else race.ai_picks)
        if track == "ai" and race.ai_skipped and not picks:
            # 整列提示
            msg = "信心不足略過"
            bb = font_pick.getbbox(msg)
            draw.text(
                (COL_PICKS[0][0] + 16, y0 + (ROW_H - (bb[3] - bb[1])) // 2),
                msg,
                font=font_pick,
                fill=(140, 120, 100),
            )
        else:
            for ci, (x0, x1) in enumerate(COL_PICKS):
                pick = picks[ci] if ci < len(picks) else None
                label = _cell_text(pick)
                if not label:
                    continue
                bb = font_pick.getbbox(label)
                tw, th = bb[2] - bb[0], bb[3] - bb[1]
                # 過寬則縮短馬名
                while tw > (x1 - x0 - 16) and len(label) > 4:
                    label = label[:-1]
                    bb = font_pick.getbbox(label)
                    tw, th = bb[2] - bb[0], bb[3] - bb[1]
                draw.text(
                    (x0 + 12, y0 + (ROW_H - th) // 2 - 1),
                    label,
                    font=font_pick,
                    fill=text_fg,
                )
        # 橫線
        draw.line((TABLE_LEFT, y1, TABLE_RIGHT, y1), fill=grid, width=1)

    # 縱線
    for x0, x1 in [COL_RACE] + COL_PICKS:
        draw.line((x0, body_top, x0, body_top + table_h), fill=grid, width=1)
    draw.line((TABLE_RIGHT, body_top, TABLE_RIGHT, body_top + table_h), fill=grid, width=1)

    canvas.paste(footer, (0, body_top + table_h))
    meta = _save_png_under(Path(out_path), canvas)
    meta["theme"] = theme
    meta["n_races"] = n
    meta["date_line"] = date_line
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
    全賽日 → 僅 2 張 PNG（model.png / ai.png），寫入 output_root 根目錄並覆蓋舊檔。
    隨機選藍／米色公司模版；表內只顯示「馬號 馬名」（最多 4 匹），不含勝率。
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
            # 海報欄位固定最多 4 匹
            payload.model_picks = _limit_picks(payload.model_picks)
            payload.ai_picks = _limit_picks(payload.ai_picks)
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

    theme = random.choice(THEMES)
    paths = latest_paths(out_root)
    model_meta = render_meeting_poster(
        payloads, track="model", out_path=paths["model"], theme=theme
    )
    ai_meta = render_meeting_poster(
        payloads, track="ai", out_path=paths["ai"], theme=theme
    )

    model_copy = generate_meeting_copy(payloads, "model")
    ai_copy = generate_meeting_copy(payloads, "ai")
    manifest = {
        "meeting": {
            "batch_id": batch_id,
            "racing_date": racing_date,
            "course": course,
            "n_races": len(payloads),
            "theme": theme,
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
        "theme": theme,
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
            payload.model_picks = _limit_picks(payload.model_picks)
            payload.ai_picks = _limit_picks(payload.ai_picks)
            payloads.append(payload)
        except Exception as e:
            errors.append({"race_id": str(rid), "error": str(e)})

    if not payloads:
        return {"ok": False, "error": "無有效場次", "batch_id": batch_id, "errors": errors}

    theme = random.choice(THEMES)
    out_root = Path(output_root) if output_root else default_output_dir()
    out_root.mkdir(parents=True, exist_ok=True)
    paths = latest_paths(out_root)
    model_meta = render_meeting_poster(
        payloads, track="model", out_path=paths["model"], theme=theme
    )
    ai_meta = render_meeting_poster(
        payloads, track="ai", out_path=paths["ai"], theme=theme
    )
    model_copy = generate_meeting_copy(payloads, "model")
    ai_copy = generate_meeting_copy(payloads, "ai")
    manifest = {
        "meeting": {
            "batch_id": batch_id,
            "racing_date": racing_date,
            "course": course,
            "n_races": len(payloads),
            "theme": theme,
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
        "theme": theme,
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
