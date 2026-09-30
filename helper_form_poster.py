"""
馬匹歷史戰績表 PNG 渲染（對齊參考圖樣式，全中文）。

視覺要點（對照參考原圖）：
- 白底長圖、每場一個區塊
- 場次標題列（日期 時間 場地 表面 第N場 距離）
- 雙層表頭：分組（馬匹資料／馬匹統計數字／備註）+ 欄名
- 米色表頭、細格線、斑馬紋列
- 淡橘色大場次號疊於表頭後方
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from helper_form_client import load_helper_form_for_display

ROOT = Path(__file__).resolve().parent
BUNDLED_FONT = ROOT / "assets" / "fonts" / "wqy-microhei.ttc"
FONT_CANDIDATES = [
    str(BUNDLED_FONT),
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]

# 版式（參考原圖約 1280 寬）
CANVAS_W = 1280
MARGIN_X = 28
TITLE_H = 36
GROUP_HEADER_H = 28
COL_HEADER_H = 42
ROW_H = 28
SECTION_GAP = 22
TOP_PAD = 18
BOTTOM_PAD = 24

BG = (255, 255, 255)
TITLE_FG = (40, 40, 40)
HEADER_BG = (231, 223, 200)  # 米色
HEADER_FG = (35, 35, 35)
GROUP_BG = (220, 210, 185)
GRID = (90, 90, 90)
ROW_ALT = (245, 245, 245)
ROW_BG = (255, 255, 255)
RACE_NUM_FG = (232, 140, 70)  # 淡橘場次號
CELL_FG = (25, 25, 25)
NAME_FG = (15, 15, 15)


def _find_font() -> Optional[str]:
    env = str(os.getenv("AD_FONT_PATH") or os.getenv("HELPER_FORM_FONT") or "").strip()
    for p in ([env] if env else []) + FONT_CANDIDATES:
        if p and Path(p).is_file():
            return p
    return None


def _load_font(size: int):
    from PIL import ImageFont

    path = _find_font()
    if not path:
        raise RuntimeError("找不到 CJK 字型（請確認 assets/fonts/wqy-microhei.ttc）")
    last_err: Optional[Exception] = None
    for index in (0, 1):
        try:
            return ImageFont.truetype(path, size=int(size), index=index)
        except Exception as e:
            last_err = e
    try:
        return ImageFont.truetype(path, size=int(size))
    except Exception as e:
        raise RuntimeError(f"無法載入字型 {path}: {e or last_err}") from e


def _text_size(draw, text: str, font) -> Tuple[int, int]:
    if hasattr(draw, "textbbox"):
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return int(r - l), int(b - t)
    if hasattr(font, "getbbox"):
        l, t, r, b = font.getbbox(text)
        return int(r - l), int(b - t)
    return font.getsize(text)  # type: ignore[attr-defined]


def _draw_centered(draw, box: Tuple[int, int, int, int], text: str, font, fill) -> None:
    x0, y0, x1, y1 = box
    tw, th = _text_size(draw, text, font)
    x = x0 + max(0, (x1 - x0 - tw) // 2)
    y = y0 + max(0, (y1 - y0 - th) // 2) - 1
    draw.text((x, y), text, font=font, fill=fill)


def _draw_left(draw, box: Tuple[int, int, int, int], text: str, font, fill, pad: int = 4) -> None:
    x0, y0, x1, y1 = box
    _, th = _text_size(draw, text, font)
    y = y0 + max(0, (y1 - y0 - th) // 2) - 1
    draw.text((x0 + pad, y), text, font=font, fill=fill)


def _col_widths(n_cols: int, table_w: int) -> List[int]:
    """馬名較寬，其餘均分。"""
    if n_cols <= 0:
        return []
    name_w = max(96, int(table_w * 0.095))
    rest = table_w - name_w
    other = n_cols - 1
    if other <= 0:
        return [table_w]
    base = rest // other
    widths = [name_w] + [base] * other
    widths[-1] += table_w - sum(widths)
    return widths


def _section_height(n_rows: int) -> int:
    return TITLE_H + GROUP_HEADER_H + COL_HEADER_H + n_rows * ROW_H


def render_helper_form_image(
    races: Sequence[Dict[str, Any]],
    *,
    out_path: Optional[str | Path] = None,
    max_races: Optional[int] = None,
) -> "Image.Image":
    """將正規化後的 races 渲成接近參考圖的長 PNG。"""
    from PIL import Image, ImageDraw

    items = list(races or [])
    if max_races is not None:
        items = items[: max(0, int(max_races))]
    if not items:
        img = Image.new("RGB", (CANVAS_W, 200), BG)
        draw = ImageDraw.Draw(img)
        font = _load_font(22)
        draw.text((40, 80), "沒有可顯示的場次資料", font=font, fill=TITLE_FG)
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            img.save(out_path, format="PNG", optimize=True)
        return img

    table_w = CANVAS_W - 2 * MARGIN_X
    heights = [_section_height(len(r.get("rows") or [])) for r in items]
    total_h = TOP_PAD + sum(heights) + SECTION_GAP * (len(items) - 1) + BOTTOM_PAD

    # 全程 RGBA，方便淡橘場次號半透明疊加
    img = Image.new("RGBA", (CANVAS_W, total_h), BG + (255,))
    draw = ImageDraw.Draw(img)
    watermark = Image.new("RGBA", (CANVAS_W, total_h), (0, 0, 0, 0))
    wm_draw = ImageDraw.Draw(watermark)

    font_title = _load_font(18)
    font_group = _load_font(15)
    font_head = _load_font(13)
    font_head_sm = _load_font(11)
    font_cell = _load_font(12)
    font_cell_sm = _load_font(10)
    font_name = _load_font(13)
    font_race_num = _load_font(86)

    y = TOP_PAD
    for race in items:
        columns = list(race.get("columns") or [])
        groups = list(race.get("groups") or [])
        rows = list(race.get("rows") or [])
        n_cols = len(columns) or 1
        widths = _col_widths(n_cols, table_w)
        x0 = MARGIN_X
        title = str(race.get("title") or "")
        race_num = race.get("race_num") or ""

        # 標題
        draw.text((x0, y + 8), title, font=font_title, fill=TITLE_FG)
        y_table = y + TITLE_H

        # 淡橘大場次號（表頭後方浮水印）
        num_text = str(race_num)
        if num_text:
            tw, _th = _text_size(wm_draw, num_text, font_race_num)
            nx = x0 + (table_w - tw) // 2
            ny = y_table + 4
            wm_draw.text((nx, ny), num_text, font=font_race_num, fill=(232, 140, 70, 78))

        # 分組表頭
        key_to_idx = {c["key"]: i for i, c in enumerate(columns)}
        gx = x0
        for g in groups:
            gcols = list(g.get("columns") or [])
            gw = 0
            for c in gcols:
                i = key_to_idx.get(c.get("key"))
                if i is not None:
                    gw += widths[i]
            if gw <= 0:
                continue
            box = (gx, y_table, gx + gw, y_table + GROUP_HEADER_H)
            draw.rectangle(box, fill=GROUP_BG + (255,), outline=GRID, width=1)
            _draw_centered(draw, box, str(g.get("name") or ""), font_group, HEADER_FG)
            gx += gw

        # 欄名列
        y_col = y_table + GROUP_HEADER_H
        cx = x0
        for i, col in enumerate(columns):
            w = widths[i]
            box = (cx, y_col, cx + w, y_col + COL_HEADER_H)
            draw.rectangle(box, fill=HEADER_BG + (255,), outline=GRID, width=1)
            label = str(col.get("label") or "")
            f = font_head_sm if len(label) >= 5 else font_head
            if len(label) >= 6:
                mid = max(2, (len(label) + 1) // 2)
                line1, line2 = label[:mid], label[mid:]
                tw1, th1 = _text_size(draw, line1, f)
                tw2, th2 = _text_size(draw, line2, f)
                tx1 = cx + max(0, (w - tw1) // 2)
                tx2 = cx + max(0, (w - tw2) // 2)
                ty = y_col + max(2, (COL_HEADER_H - th1 - th2 - 2) // 2)
                draw.text((tx1, ty), line1, font=f, fill=HEADER_FG)
                draw.text((tx2, ty + th1 + 1), line2, font=f, fill=HEADER_FG)
            else:
                _draw_centered(draw, box, label, f, HEADER_FG)
            cx += w

        # 資料列
        y_row = y_col + COL_HEADER_H
        for ri, row in enumerate(rows):
            fill = (ROW_ALT if ri % 2 else ROW_BG) + (255,)
            cx = x0
            cells = row.get("cells") or {}
            for i, col in enumerate(columns):
                w = widths[i]
                box = (cx, y_row, cx + w, y_row + ROW_H)
                draw.rectangle(box, fill=fill, outline=GRID, width=1)
                key = col["key"]
                text = str(cells.get(key, ""))
                if key == "name":
                    _draw_left(draw, box, text, font_name, NAME_FG, pad=3)
                else:
                    f = font_cell if len(text) < 12 else font_cell_sm
                    _draw_centered(draw, box, text, f, CELL_FG)
                cx += w
            y_row += ROW_H

        # 外框加強
        draw.rectangle(
            (x0, y_table, x0 + table_w, y_row),
            outline=GRID,
            width=2,
        )

        y = y_row + SECTION_GAP

    img = Image.alpha_composite(img, watermark).convert("RGB")

    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="PNG", optimize=True)
    return img


def generate_helper_form_png(
    *,
    out_path: str | Path,
    expected_date: Optional[str] = None,
    expected_course: Optional[str] = None,
    require_course: bool = False,
    raw: Optional[Dict[str, Any]] = None,
    max_races: Optional[int] = None,
    render_even_if_stale: bool = False,
) -> Dict[str, Any]:
    """
    抓 API（或用 raw）→ 日期核對 → 產出 PNG。
    預設 stale 不產圖；測試視覺可設 render_even_if_stale=True。
    """
    loaded = load_helper_form_for_display(
        expected_date=expected_date,
        expected_course=expected_course,
        require_course=require_course,
        raw=raw,
    )
    guard = loaded.get("guard") or {}
    if not loaded.get("ok") and not render_even_if_stale:
        return {
            "ok": False,
            "error": guard.get("message") or "日期核對失敗",
            "guard": guard,
            "out_path": None,
        }

    path = Path(out_path)
    img = render_helper_form_image(
        loaded.get("races") or [],
        out_path=path,
        max_races=max_races,
    )
    return {
        "ok": True,
        "guard": guard,
        "out_path": str(path),
        "n_races": loaded.get("n_races") or 0,
        "size": list(img.size),
        "stale_rendered": (not loaded.get("ok")),
    }


def default_output_dir() -> Path:
    return ROOT / "ad_output" / "helper_form"


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="產出馬匹歷史戰績表 PNG")
    ap.add_argument("--out", default=str(default_output_dir() / "helper_form.png"))
    ap.add_argument("--expect-date", default=None, help="YYYY-MM-DD；省略則用系統最新賽日")
    ap.add_argument("--expect-course", default=None, help="ST 或 HV")
    ap.add_argument("--require-course", action="store_true")
    ap.add_argument("--from-file", default=None, help="本地 helper JSON fixture")
    ap.add_argument("--max-races", type=int, default=None)
    ap.add_argument(
        "--allow-stale",
        action="store_true",
        help="日期不符仍渲染（僅供視覺對照）",
    )
    args = ap.parse_args()

    raw = None
    if args.from_file:
        raw = json.loads(Path(args.from_file).read_text(encoding="utf-8"))

    result = generate_helper_form_png(
        out_path=args.out,
        expected_date=args.expect_date,
        expected_course=args.expect_course,
        require_course=args.require_course,
        raw=raw,
        max_races=args.max_races,
        render_even_if_stale=args.allow_stale,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
