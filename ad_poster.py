"""
廣告輸出模組：依公司原海報風格生成全賽日推介圖。

每次產出（固定檔名，下次覆蓋）：
  - ad_output/fused.png  全賽日 · 模型×AI 綜合推介（社交主視覺，最多 4 匹／場）
  - ad_output/copy.json  宣傳文案（僅綜合推介）

內部仍保留 model／ai 渲染路徑供對照測試；正式產出只寫綜合軌。

版式：公司空白模版（header 固定 + 表身中段垂直拉伸 + footer 固定）。
只疊加日期條、場次號、揀馬（馬號＋馬名，最多 4 匹）；不含勝率。
PNG ≤ AD_OUTPUT_MAX_KB（預設 2048）。
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
try:
    from ad_llm_copy import SOCIAL_COPY_FILE
except Exception:
    SOCIAL_COPY_FILE = "social_copy.json"

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

FUSED_FILE = "fused.png"
MODEL_FILE = "model.png"
AI_FILE = "ai.png"
TRACK_DISPLAY = {
    "fused": "綜合",
    "model": "模型",
    "ai": "AI 馬評",
}
PRIMARY_TRACK = "fused"
PRIMARY_TRACK_LABEL = TRACK_DISPLAY[PRIMARY_TRACK]  # 綜合
COPY_FILE = "copy.json"
# 空白模版量測（blank_day/night = 1280×1299；白底內容區中段可垂直拉伸）
BLANK_W = 1280
BLANK_H = 1299
# 上固定（標題＋J18精選列＋白框上緣）／中拉伸（直線白底）／下固定（白框下圓角＋footer）
SLICE_TOP_END = 400
SLICE_MID_END = 980
REF_N_ROWS = 10  # 模版中段對應參考場數
ROW_H_SCALE = 1.0
RACE_COL = (48, 175)
CONTENT_X0 = 185
CONTENT_X1 = 1220
PICK_GAP = 12
DATE_PILL = (40, 206, 460, 257)
DATE_PILL_RADIUS = 24
# 預設字色（會依 theme 覆寫）
RACE_FG = (55, 55, 55)
TEXT_FG = (40, 40, 40)
FONT_BASE_PX = 34
# 表身分隔
GRID_LINE = (210, 210, 210)
GRID_LINE_STRONG = (170, 170, 170)
ROW_TINT = (245, 245, 245)
# 日馬啡色／夜馬藍色（依 fixtures.session 或 is_day_meeting 選擇）
THEMES = ("day", "night")
THEME_STYLES = {
    "day": {
        "date_pill_fill": (245, 168, 110),
        "date_pill_text": (255, 255, 255),
        "race_fg": (90, 55, 35),
        "text_fg": (55, 40, 30),
        "grid": (210, 195, 180),
        "grid_strong": (170, 145, 125),
        "row_tint": (250, 244, 236),
        "canvas_bg": (180, 140, 110),
    },
    "night": {
        "date_pill_fill": (70, 130, 170),
        "date_pill_text": (255, 255, 255),
        "race_fg": (40, 75, 105),
        "text_fg": (35, 55, 75),
        "grid": (195, 205, 215),
        "grid_strong": (140, 160, 180),
        "row_tint": (236, 244, 250),
        "canvas_bg": (90, 120, 150),
    },
}
WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 舊測試／相容常數（不再用於主渲染）
POSTER_W = BLANK_W
POSTER_H = BLANK_H
TABLE_LEFT = RACE_COL[0]
TABLE_RIGHT = CONTENT_X1
COL_RACE = RACE_COL
COL_PICKS = [(185, 430), (430, 690), (690, 950), (950, 1220)]
ROW_H = max(1, (SLICE_MID_END - SLICE_TOP_END) // REF_N_ROWS)
# 相容舊名稱
DATE_PILL_FILL = THEME_STYLES["night"]["date_pill_fill"]


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
    fused_picks: List[PickItem] = field(default_factory=list)
    ai_skipped: bool = False
    ai_skip_message: str = ""
    fused_fallback_model_only: bool = False


def _picks_for_track(payload: RaceAdPayload, track: str) -> List[PickItem]:
    if track == "fused":
        return list(payload.fused_picks or [])
    if track == "ai":
        return list(payload.ai_picks or [])
    return list(payload.model_picks or [])


def _build_fused_pick_items(
    *,
    model_rows: List[dict],
    n_runners: int,
) -> Tuple[List[PickItem], bool]:
    """回傳 (fused PickItems, fallback_model_only)。"""
    from form_ai_picks import build_fused_picks

    pack = build_fused_picks(model_rows, n_runners=n_runners)
    fallback = bool(pack.get("fallback_model_only"))
    if not pack.get("available"):
        return [], fallback
    win_set = {
        int(x["horse_no"])
        for x in (pack.get("win") or [])
        if x.get("horse_no") is not None
    }
    out: List[PickItem] = []
    for x in (pack.get("place") or []) or (pack.get("win") or []):
        hno = int(x["horse_no"])
        out.append(
            PickItem(
                horse_no=hno,
                horse_name=str(x.get("horse_name") or ""),
                share_pct=round(float(x.get("fused_share_pct") or 0), 1),
                tag="爭勝" if hno in win_set else "推介",
            )
        )
    return out, fallback


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

    fuse_rows = []
    for _, r in df.iterrows():
        hno = int(r["馬號"])
        sc, cf, combo = ai_map.get(hno, (None, None, None))
        if combo is None:
            combo = compute_ai_combo(sc, cf)
        fuse_rows.append(
            {
                "horse_no": hno,
                "horse_name": r["馬名"],
                "model_win_prob": float(r["模型勝率"]) if pd.notna(r.get("模型勝率")) else None,
                "ai_score": sc,
                "confidence": cf,
                "ai_combo": combo,
                "pred_rank": int(r["預測排名"]) if pd.notna(r.get("預測排名")) else None,
            }
        )
    fused_picks, fused_fallback = _build_fused_pick_items(model_rows=fuse_rows, n_runners=n)

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
        fused_picks=fused_picks,
        ai_skipped=ai_skipped,
        ai_skip_message=ai_msg,
        fused_fallback_model_only=fused_fallback,
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

    fuse_rows = []
    for _, r in df.iterrows():
        sc = r.get("ai_score")
        cf = r.get("confidence")
        combo = r.get("ai_combo")
        if combo is None or (isinstance(combo, float) and pd.isna(combo)):
            combo = compute_ai_combo(sc, cf)
        fuse_rows.append(
            {
                "horse_no": int(r["horse_no"]),
                "horse_name": r.get("horse_name"),
                "model_win_prob": (
                    None
                    if r.get("model_win_prob") is None
                    or (isinstance(r.get("model_win_prob"), float) and pd.isna(r.get("model_win_prob")))
                    else float(r.get("model_win_prob"))
                ),
                "ai_score": None if sc is None or (isinstance(sc, float) and pd.isna(sc)) else float(sc),
                "confidence": None if cf is None or (isinstance(cf, float) and pd.isna(cf)) else float(cf),
                "ai_combo": None if combo is None or (isinstance(combo, float) and pd.isna(combo)) else float(combo),
                "pred_rank": r.get("pred_rank"),
            }
        )
    fused_picks, fused_fallback = _build_fused_pick_items(model_rows=fuse_rows, n_runners=n)

    return RaceAdPayload(
        race_id=str(race_id),
        racing_date=str(racing_date)[:10],
        course=str(course),
        race_num=race_num,
        race_name=race_name or "",
        model_picks=model_picks,
        ai_picks=ai_picks,
        fused_picks=fused_picks,
        ai_skipped=ai_skipped,
        ai_skip_message=str(ai_pack.get("message") or ""),
        fused_fallback_model_only=fused_fallback,
    )


def generate_copy(payload: RaceAdPayload, track: str) -> Dict[str, str]:
    date_s = payload.racing_date
    course = payload.course
    rn = payload.race_num
    title = f"第{rn}場" if rn is not None else payload.race_id
    picks = _limit_picks(_picks_for_track(payload, track))
    if track == "fused":
        headline = f"【{BRAND_NAME} 綜合推介】{date_s} {course} {title}"
        line = "綜合推介："
        empty = "本場暫無綜合推介。"
    elif track == "model":
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
    if track == "fused":
        headline = f"【{BRAND_NAME} 綜合推介】{date_s} {course} 全賽日"
        label = TRACK_DISPLAY["fused"]
    elif track == "model":
        headline = f"【{BRAND_NAME} 模型推介】{date_s} {course} 全賽日"
        label = TRACK_DISPLAY["model"]
    else:
        headline = f"【{BRAND_NAME} AI 馬評】{date_s} {course} 全賽日"
        label = TRACK_DISPLAY["ai"]
    lines = []
    for p in payloads:
        rn = p.race_num if p.race_num is not None else "?"
        picks = _limit_picks(_picks_for_track(p, track))
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
    """相容舊切片資產；主渲染改走 blank_*.jpg。"""
    return {
        "header": COMPANY_DIR / f"{theme}_header.jpg",
        "footer": COMPANY_DIR / f"{theme}_footer.jpg",
        "full": COMPANY_DIR / f"{theme}_full.jpg",
        "blank": _blank_template_path(theme),
    }


def _blank_template_path(theme: str) -> Path:
    """空白模版：優先 blank_{theme}；night fallback blank_blue；day fallback blank_night/blue。"""
    theme = resolve_poster_theme(theme=theme)
    names = [
        f"blank_{theme}.png",
        f"blank_{theme}.jpg",
        f"blank_{theme}.jpeg",
    ]
    if theme == "night":
        names += ["blank_blue.png", "blank_blue.jpg"]
    else:
        names += ["blank_night.png", "blank_night.jpg", "blank_blue.png", "blank_blue.jpg"]
    for name in names:
        p = COMPANY_DIR / name
        if p.is_file():
            return p
    raise FileNotFoundError(f"缺少空白海報模版 blank_day/night：{COMPANY_DIR}")


def resolve_poster_theme(
    *,
    theme: Optional[str] = None,
    course: str = "",
    session: Optional[str] = None,
    is_day_meeting: Optional[bool] = None,
) -> str:
    """
    日馬 → day（啡色）；夜馬 → night（藍色）。
    優先明示 theme，其次 fixtures.session／is_day_meeting，最後以場地慣例（HV=夜、ST=日）。
    """
    t = str(theme or "").strip().lower()
    if t in ("day", "beige", "brown", "日"):
        return "day"
    if t in ("night", "blue", "夜"):
        return "night"
    s = str(session or "").strip().lower()
    if s in ("day", "dusk", "日", "黄昏", "黃昏"):
        return "day"
    if s in ("night", "夜"):
        return "night"
    if is_day_meeting is True:
        return "day"
    if is_day_meeting is False:
        return "night"
    return "night" if str(course or "").upper() == "HV" else "day"


def _theme_style(theme: str) -> Dict[str, Any]:
    return dict(THEME_STYLES.get(resolve_poster_theme(theme=theme), THEME_STYLES["night"]))


def lookup_meeting_session(racing_date: str, course: str) -> Dict[str, Any]:
    """從 fixtures 讀 session／is_day_meeting；失敗則空 dict。"""
    d = str(racing_date or "")[:10]
    c = str(course or "").upper()
    if not d or not c:
        return {}
    try:
        from sqlalchemy import text

        from factor_calibration import FactorCalibration

        cal = FactorCalibration()
        df = pd.read_sql(
            text(
                "SELECT session, is_day_meeting FROM fixtures "
                "WHERE CAST(racing_date AS TEXT) LIKE :d AND UPPER(CAST(course AS TEXT)) = :c "
                "LIMIT 1"
            ),
            cal.engine,
            params={"d": f"{d}%", "c": c},
        )
        if df is None or df.empty:
            return {}
        row = df.iloc[0]
        out: Dict[str, Any] = {}
        if "session" in df.columns and pd.notna(row.get("session")):
            out["session"] = str(row.get("session"))
        if "is_day_meeting" in df.columns and pd.notna(row.get("is_day_meeting")):
            out["is_day_meeting"] = bool(row.get("is_day_meeting"))
        return out
    except Exception:
        return {}


def _venue_label(course: str) -> str:
    c = str(course or "").upper()
    if c == "ST":
        return "沙田"
    if c == "HV":
        return "谷草"
    return str(course or "")


def _meeting_date_line(
    racing_date: str,
    course: str,
    *,
    session: Optional[str] = None,
    is_day_meeting: Optional[bool] = None,
) -> str:
    """例：2026/09/09 星期三 谷草 (夜)"""
    ds = str(racing_date or "")[:10].replace("-", "/")
    wd = ""
    try:
        dt = datetime.strptime(str(racing_date or "")[:10], "%Y-%m-%d")
        wd = WEEKDAY_ZH[dt.weekday()]
    except Exception:
        pass
    venue = _venue_label(course)
    theme = resolve_poster_theme(course=course, session=session, is_day_meeting=is_day_meeting)
    session_zh = "日" if theme == "day" else "夜"
    parts = [p for p in (ds, wd, f"{venue} ({session_zh})" if venue else "") if p]
    return " ".join(parts)


def _paint_date_pill(
    canvas: "Image.Image",
    date_line: str,
    *,
    theme: str = "night",
) -> None:
    """覆蓋空白模版日期膠囊並寫入當期賽事資料。"""
    from PIL import ImageDraw

    style = _theme_style(theme)
    draw = ImageDraw.Draw(canvas)
    box = DATE_PILL
    draw.rounded_rectangle(box, radius=DATE_PILL_RADIUS, fill=tuple(style["date_pill_fill"]))
    font = _load_font(28)
    bbox = font.getbbox(date_line)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # 過長則略縮字
    if tw > (box[2] - box[0] - 36):
        font = _load_font(22)
        bbox = font.getbbox(date_line)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw > (box[2] - box[0] - 24):
        font = _load_font(18)
        bbox = font.getbbox(date_line)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = box[0] + 18
    ty = box[1] + (box[3] - box[1] - th) // 2 - 1
    draw.text((tx, ty), date_line, font=font, fill=tuple(style["date_pill_text"]))


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


def _pick_column_bounds(n_cols: int = 4) -> List[Tuple[int, int]]:
    gap = PICK_GAP
    usable = CONTENT_X1 - CONTENT_X0 - gap * (n_cols - 1)
    col_w = max(1, usable // n_cols)
    out: List[Tuple[int, int]] = []
    x = CONTENT_X0
    for _ in range(n_cols):
        out.append((x, x + col_w))
        x += col_w + gap
    return out


def _draw_table_guides(
    draw,
    *,
    mid_top: float,
    mid_bot: float,
    n: int,
    row_h: float,
    cols: Sequence[Tuple[int, int]],
    style: Optional[Dict[str, Any]] = None,
) -> None:
    """畫行底、橫線與欄分隔，區分每一場／每一揀馬欄。"""
    st = style or _theme_style("night")
    row_tint = tuple(st.get("row_tint", ROW_TINT))
    grid = tuple(st.get("grid", GRID_LINE))
    grid_strong = tuple(st.get("grid_strong", GRID_LINE_STRONG))
    x_left = RACE_COL[0]
    x_right = CONTENT_X1
    for i in range(n):
        if i % 2 == 0:
            continue
        y0 = int(mid_top + i * row_h)
        y1 = int(mid_top + (i + 1) * row_h)
        draw.rectangle((CONTENT_X0 - 8, y0, x_right, y1), fill=row_tint)

    vx = CONTENT_X0 - 12
    draw.rectangle((vx - 1, int(mid_top), vx + 2, int(mid_bot)), fill=grid_strong)

    for i in range(n + 1):
        y = int(mid_top + i * row_h)
        strong = i in (0, n)
        half = 2 if strong else 1
        draw.rectangle(
            (x_left, y - half, x_right, y + half),
            fill=grid_strong if strong else grid,
        )

    for ci in range(1, len(cols)):
        x = (cols[ci - 1][1] + cols[ci][0]) // 2
        draw.rectangle((x - 1, int(mid_top), x + 1, int(mid_bot)), fill=grid)


def _assemble_blank_canvas(blank: "Image.Image", n_races: int) -> Tuple["Image.Image", int, float]:
    """
    上固定 + 中段垂直拉伸 + 下固定。
    回傳 (canvas, mid_top_y, row_h)。
    """
    from PIL import Image

    n = max(int(n_races), 1)
    w, h = blank.size
    top_end = min(SLICE_TOP_END, h - 2)
    mid_end = min(SLICE_MID_END, h - 1)
    if mid_end <= top_end:
        raise ValueError("空白模版切片參數無效")

    top = blank.crop((0, 0, w, top_end))
    mid = blank.crop((0, top_end, w, mid_end))
    bot = blank.crop((0, mid_end, w, h))

    ref_mid_h = mid_end - top_end
    row_h = (ref_mid_h / float(REF_N_ROWS)) * float(ROW_H_SCALE)
    new_mid_h = max(1, int(round(n * row_h)))
    if mid.height != new_mid_h:
        mid = mid.resize((w, new_mid_h), Image.Resampling.LANCZOS)

    canvas_h = top.height + mid.height + bot.height
    canvas = Image.new("RGB", (w, canvas_h), (245, 245, 245))
    canvas.paste(top, (0, 0))
    canvas.paste(mid, (0, top.height))
    canvas.paste(bot, (0, top.height + mid.height))
    return canvas, top.height, float(mid.height) / float(n)


def render_meeting_poster(
    payloads: Sequence[RaceAdPayload],
    *,
    track: str,
    out_path: Path,
    theme: Optional[str] = None,
    session: Optional[str] = None,
    is_day_meeting: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    空白公司模版疊加：中段按場數垂直拉伸，再只畫日期／場次號／揀馬。
    theme=day|night（日馬啡色／夜馬藍色）；可由 session／is_day_meeting／場地推斷。
    """
    from PIL import Image, ImageDraw

    course0 = ""
    if payloads:
        course0 = str(getattr(list(payloads)[0], "course", "") or "")
    theme = resolve_poster_theme(
        theme=theme, course=course0, session=session, is_day_meeting=is_day_meeting
    )
    blank_path = _blank_template_path(theme)
    blank = Image.open(blank_path).convert("RGB")

    races = sorted(
        list(payloads),
        key=lambda p: (
            int(p.race_num) if str(p.race_num).isdigit() else 999,
            str(p.race_id),
        ),
    )
    n = max(len(races), 1)
    canvas, mid_top, row_h = _assemble_blank_canvas(blank, n)
    mid_bot = mid_top + n * row_h

    style = _theme_style(theme)
    date_line = _meeting_date_line(
        races[0].racing_date if races else "",
        races[0].course if races else "",
        session=session,
        is_day_meeting=is_day_meeting,
    )
    _paint_date_pill(canvas, date_line, theme=theme)

    draw = ImageDraw.Draw(canvas)
    cols = _pick_column_bounds(4)
    _draw_table_guides(
        draw, mid_top=mid_top, mid_bot=mid_bot, n=n, row_h=row_h, cols=cols, style=style
    )

    # 字級隨列高；推介／場次號皆欄內水平置中（anchor=mm）
    # 「第N場」較單數字寬，場次字略細以塞進左欄
    base = int(FONT_BASE_PX)
    race_px = int(max(base - 10, min(int(row_h * 0.42), base - 2)))
    pick_px = int(max(base - 6, min(int(row_h * 0.50), base + 4)))
    font_race = _load_font(race_px)
    font_pick = _load_font(pick_px)
    race_fg = tuple(style["race_fg"])
    text_fg = tuple(style["text_fg"])

    for i, race in enumerate(races):
        cy = mid_top + (i + 0.5) * row_h
        rn = race.race_num if race.race_num is not None else i + 1
        rn_s = f"第{rn}場"
        draw.text(
            ((RACE_COL[0] + RACE_COL[1]) // 2, int(cy)),
            rn_s,
            font=font_race,
            fill=race_fg,
            anchor="mm",
        )

        picks = _limit_picks(_picks_for_track(race, track))
        if track == "ai" and race.ai_skipped and not picks:
            msg = "信心不足略過"
            span0, span1 = cols[0][0], cols[-1][1]
            draw.text(
                ((span0 + span1) // 2, int(cy)),
                msg,
                font=font_pick,
                fill=(140, 120, 100),
                anchor="mm",
            )
            continue

        for ci, (x0, x1) in enumerate(cols):
            pick = picks[ci] if ci < len(picks) else None
            label_s = _cell_text(pick)
            if not label_s:
                continue
            # 過寬則縮短馬名
            bb = font_pick.getbbox(label_s)
            tw = bb[2] - bb[0]
            while tw > (x1 - x0 - 20) and len(label_s) > 4:
                label_s = label_s[:-1]
                bb = font_pick.getbbox(label_s)
                tw = bb[2] - bb[0]
            draw.text(
                ((x0 + x1) // 2, int(cy)),
                label_s,
                font=font_pick,
                fill=text_fg,
                anchor="mm",
            )

    meta = _save_png_under(Path(out_path), canvas)
    meta["theme"] = theme
    meta["blank"] = str(blank_path.name)
    meta["n_races"] = n
    meta["row_h"] = row_h
    meta["race_px"] = race_px
    meta["pick_px"] = pick_px
    meta["canvas_size"] = list(canvas.size)
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
        "fused": root / FUSED_FILE,
        "model": root / MODEL_FILE,
        "ai": root / AI_FILE,
        "copy": root / COPY_FILE,
    }


def _write_primary_meeting_outputs(
    payloads: Sequence[RaceAdPayload],
    *,
    batch_id: str,
    racing_date: str,
    course: str,
    output_root: Path,
    errors: Optional[List[Dict[str, str]]] = None,
    theme: Optional[str] = None,
    session: Optional[str] = None,
    is_day_meeting: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    正式產出：只寫綜合推介 fused.png + copy.json（含 fused_copy）。
    copy.json 仍保留各場 model／ai picks 供社交文案候選池使用。
    """
    err_list = list(errors or [])
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    if session is None and is_day_meeting is None:
        meta = lookup_meeting_session(racing_date, course)
        session = meta.get("session", session)
        if is_day_meeting is None and "is_day_meeting" in meta:
            is_day_meeting = meta.get("is_day_meeting")
    theme = resolve_poster_theme(
        theme=theme, course=course, session=session, is_day_meeting=is_day_meeting
    )
    paths = latest_paths(out_root)
    fused_meta = render_meeting_poster(
        payloads,
        track=PRIMARY_TRACK,
        out_path=paths["fused"],
        theme=theme,
        session=session,
        is_day_meeting=is_day_meeting,
    )
    fused_copy = generate_meeting_copy(payloads, PRIMARY_TRACK)
    manifest = {
        "meeting": {
            "batch_id": batch_id,
            "racing_date": racing_date,
            "course": course,
            "n_races": len(payloads),
            "theme": theme,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "primary_track": PRIMARY_TRACK,
            "primary_track_label": PRIMARY_TRACK_LABEL,
            "fused_file": FUSED_FILE,
            "max_kb": _max_bytes() // 1024,
            "fused_bytes": fused_meta.get("bytes"),
        },
        "fused_copy": fused_copy.get("full"),
        "races": [
            {
                "race_id": p.race_id,
                "race_no": p.race_num,
                "race_name": p.race_name,
                "distance": p.distance_m,
                "fused_picks": [asdict(x) for x in p.fused_picks],
                "model_picks": [asdict(x) for x in p.model_picks],
                "ai_picks": [asdict(x) for x in p.ai_picks],
                "ai_skipped": p.ai_skipped,
                "fused_fallback_model_only": p.fused_fallback_model_only,
            }
            for p in payloads
        ],
    }
    paths["copy"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 歸檔海報「生成資料」only（不存 PNG）；可供翻查／之後重產
    copy_archive: Dict[str, Any] = {}
    try:
        from ad_copy_jobs import archive_copy_payload

        copy_archive = archive_copy_payload(
            out_root,
            racing_date=str(racing_date or ""),
            course=str(course or ""),
            copy_data=manifest,
            batch_id=str(batch_id or ""),
        )
    except Exception as exc:
        print(f"[ad_poster] copy archive failed: {exc}")
        copy_archive = {"ok": False, "error": str(exc)}

    # 統計／海報完成後：產出廣告包 JSON，並 webhook 通知外部助手
    ad_pkg: Dict[str, Any] = {}
    try:
        from ad_package import publish_ad_package_after_outputs

        ad_pkg = publish_ad_package_after_outputs(output_root=out_root, notify=True)
    except Exception as exc:
        print(f"[ad_poster] ad package publish failed: {exc}")
        ad_pkg = {"ok": False, "error": str(exc)}

    return {
        "ok": len(err_list) == 0,
        "batch_id": batch_id,
        "n_races": len(payloads),
        "races_written": len(payloads),
        "files_written": 2,
        "theme": theme,
        "errors": err_list,
        "output_dir": str(out_root),
        "fused_file": str(paths["fused"]),
        "copy_json": str(paths["copy"]),
        "fused_bytes": fused_meta.get("bytes"),
        "fused_meta": fused_meta,
        "primary_track": PRIMARY_TRACK,
        "primary_track_label": PRIMARY_TRACK_LABEL,
        "ad_package": ad_pkg,
        "copy_archive": copy_archive,
    }


def generate_ads_for_meeting_predictions(
    *,
    batch_id: str,
    race_items: Sequence[Dict[str, Any]],
    output_root: Optional[Path] = None,
    racing_date: str = "",
    course: str = "",
    theme: Optional[str] = None,
    session: Optional[str] = None,
    is_day_meeting: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    全賽日 → fused.png（綜合推介主視覺）＋ copy.json，寫入 output_root 並覆蓋舊檔。
    空白模版中段按場數拉伸；表內只顯示「馬號 馬名」（最多 4 匹），不含勝率。
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
            payload.fused_picks = _limit_picks(payload.fused_picks)
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

    return _write_primary_meeting_outputs(
        payloads,
        batch_id=batch_id,
        racing_date=racing_date,
        course=course,
        output_root=out_root,
        errors=errors,
        theme=theme,
        session=session,
        is_day_meeting=is_day_meeting,
    )


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
            payload.fused_picks = _limit_picks(payload.fused_picks)
            payloads.append(payload)
        except Exception as e:
            errors.append({"race_id": str(rid), "error": str(e)})

    if not payloads:
        return {"ok": False, "error": "無有效場次", "batch_id": batch_id, "errors": errors}

    out_root = Path(output_root) if output_root else default_output_dir()
    # session／主題由 _write_primary_meeting_outputs 內查 fixtures（或場地慣例）
    return _write_primary_meeting_outputs(
        payloads,
        batch_id=batch_id,
        racing_date=racing_date,
        course=course,
        output_root=out_root,
        errors=errors,
        theme=None,
        session=None,
        is_day_meeting=None,
    )


def list_ad_batches(output_root: Optional[Path] = None) -> List[str]:
    """相容舊 UI：若根目錄有最新海報則回傳 ['latest']。"""
    root = Path(output_root) if output_root else default_output_dir()
    paths = latest_paths(root)
    if paths["fused"].is_file() or paths["copy"].is_file():
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
    if paths["fused"].is_file():
        out.append(paths["fused"])
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
        for name in (FUSED_FILE, COPY_FILE, SOCIAL_COPY_FILE):
            p = root / name
            if p.is_file():
                zf.write(p, arcname=p.name)
    return buf.getvalue()
