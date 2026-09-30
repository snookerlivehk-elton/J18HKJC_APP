"""
馬匹歷史戰績表 PNG 渲染（對齊參考圖樣式，全中文）。

視覺要點（對照參考原圖）：
- 白底長圖、每場一個區塊
- 場次標題列（日期 時間 場地 表面 第N場 距離）
- 雙層表頭：分組（馬匹資料／馬匹統計數字／備註）+ 欄名
- 米色表頭、細格線、斑馬紋列
- 淡橘色大場次號疊於表頭後方
- 每幅圖置中 J18 logo 水印（不透明度 25%）

賽日拆圖：固定優先 3 幅；每幅 3–4 場（餘場補前）。
例：9→3+3+3、10→4+3+3、11→4+4+3、12→4+4+4；8→3+3+2。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from helper_form_client import load_helper_form_for_display

ROOT = Path(__file__).resolve().parent
BUNDLED_FONT = ROOT / "assets" / "fonts" / "wqy-microhei.ttc"
LOGO_PATH = ROOT / "assets" / "j18_helper_logo.jpg"
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

# Logo 水印：原檔偏淺橘＋白字，嚴格 25% alpha 在密表上幾乎不可見。
# 實務採「加深色＋40%」仍呈浮水印感；可用 HELPER_FORM_LOGO_OPACITY 覆寫。
LOGO_OPACITY = float(os.getenv("HELPER_FORM_LOGO_OPACITY") or "0.40")
LOGO_WIDTH_RATIO = 0.56
# 白字（J18）轉成品牌深橘色
LOGO_GLYPH_RGB = (168, 64, 18)
# 整體再加深，避免淺黃橘被白底吃掉
LOGO_DARKEN = 0.72


def split_race_layout(n_races: int) -> List[int]:
    """
    依當日總場數決定每幅張數（優先固定 3 幅；餘場補前）。

    - n<=0 → []
    - 1 → [1]；2 → [1,1]
    - n>=3 → 恒為 3 段：base = n//3，餘數由前段各 +1
      例：8→[3,3,2]、9→[3,3,3]、10→[4,3,3]、11→[4,4,3]、12→[4,4,4]
    """
    n = int(n_races or 0)
    if n <= 0:
        return []
    if n == 1:
        return [1]
    if n == 2:
        return [1, 1]
    base, rem = divmod(n, 3)
    return [base + (1 if i < rem else 0) for i in range(3)]


def chunk_races(
    races: Sequence[Dict[str, Any]],
    layout: Optional[Sequence[int]] = None,
) -> List[List[Dict[str, Any]]]:
    """依 layout 把 races 切成多組；layout 省略則自動計算。"""
    items = list(races or [])
    sizes = list(layout) if layout is not None else split_race_layout(len(items))
    if not sizes:
        return []
    out: List[List[Dict[str, Any]]] = []
    idx = 0
    for size in sizes:
        take = max(0, int(size))
        out.append(items[idx : idx + take])
        idx += take
    if idx < len(items):
        # 防 layout 與實際場數脫節：餘下併入最後一幅
        if out:
            out[-1].extend(items[idx:])
        else:
            out.append(items[idx:])
    return [part for part in out if part]


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


def _resolve_logo_path() -> Optional[Path]:
    env = str(os.getenv("HELPER_FORM_LOGO") or "").strip()
    candidates = [Path(env)] if env else []
    candidates.append(LOGO_PATH)
    for p in candidates:
        if p and p.is_file():
            return p
    return None


def _prepare_logo_for_watermark(logo: "Image.Image") -> "Image.Image":
    """
    水印前處理：
    1) 裁掉外圍近白邊距（否則縮放後有效圖案太小）
    2) 外圍白底 → 透明
    3) 圖內白字（J／18）→ 品牌深橘，白底表上才看得見字形
    """
    from collections import deque

    import numpy as np
    from PIL import Image

    src = logo.convert("RGBA")
    arr = np.array(src)
    rgb = arr[:, :, :3]
    near_white = (
        (rgb[:, :, 0] >= 248) & (rgb[:, :, 1] >= 248) & (rgb[:, :, 2] >= 248)
    )

    ys, xs = np.where(~near_white)
    if xs.size == 0:
        return src
    pad = max(2, int(min(arr.shape[0], arr.shape[1]) * 0.01))
    top = max(0, int(ys.min()) - pad)
    bottom = min(arr.shape[0], int(ys.max()) + pad + 1)
    left = max(0, int(xs.min()) - pad)
    right = min(arr.shape[1], int(xs.max()) + pad + 1)
    arr = arr[top:bottom, left:right].copy()
    rgb = arr[:, :, :3]
    near_white = (
        (rgb[:, :, 0] >= 248) & (rgb[:, :, 1] >= 248) & (rgb[:, :, 2] >= 248)
    )

    h, w = near_white.shape
    outer = np.zeros((h, w), dtype=bool)
    q = deque()
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if near_white[sy, sx] and not outer[sy, sx]:
            outer[sy, sx] = True
            q.append((sx, sy))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and near_white[ny, nx] and not outer[ny, nx]:
                outer[ny, nx] = True
                q.append((nx, ny))

    # 外圍白邊透明
    arr[outer, 3] = 0
    # 圖內白字 → 深橘
    inner_white = near_white & ~outer
    arr[inner_white, 0] = LOGO_GLYPH_RGB[0]
    arr[inner_white, 1] = LOGO_GLYPH_RGB[1]
    arr[inner_white, 2] = LOGO_GLYPH_RGB[2]
    arr[inner_white, 3] = 255

    # 非透明像素整體加深（淺黃橘在白底表上易消失）
    visible = arr[:, :, 3] > 0
    darken = float(LOGO_DARKEN)
    for c in range(3):
        channel = arr[:, :, c].astype(np.float32)
        channel[visible] = channel[visible] * darken
        arr[:, :, c] = np.clip(channel, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def _apply_logo_watermark(
    base_rgba: "Image.Image",
    *,
    opacity: float = LOGO_OPACITY,
    width_ratio: float = LOGO_WIDTH_RATIO,
) -> "Image.Image":
    """於畫布正中疊加 J18 logo（預設 25% 不透明）。"""
    from PIL import Image

    logo_path = _resolve_logo_path()
    if not logo_path:
        return base_rgba

    logo = _prepare_logo_for_watermark(Image.open(logo_path))
    target_w = max(64, int(base_rgba.width * float(width_ratio)))
    ratio = target_w / max(1, logo.width)
    target_h = max(64, int(logo.height * ratio))
    # 高度不超過畫布 62%，避免矮圖被撐爆
    max_h = max(64, int(base_rgba.height * 0.62))
    if target_h > max_h:
        scale = max_h / target_h
        target_w = max(64, int(target_w * scale))
        target_h = max_h
    logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # 統一套用目標不透明度（乘上原 alpha）
    r, g, b, a = logo.split()
    op = max(0.0, min(1.0, float(opacity)))
    a = a.point(lambda p: int(p * op))
    logo = Image.merge("RGBA", (r, g, b, a))

    layer = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
    x = (base_rgba.width - target_w) // 2
    y = (base_rgba.height - target_h) // 2
    layer.paste(logo, (x, y), logo)
    return Image.alpha_composite(base_rgba, layer)


def render_helper_form_image(
    races: Sequence[Dict[str, Any]],
    *,
    out_path: Optional[str | Path] = None,
    max_races: Optional[int] = None,
    apply_logo: bool = True,
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

    # 全程 RGBA，方便淡橘場次號／logo 半透明疊加
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

    img = Image.alpha_composite(img, watermark)
    if apply_logo:
        img = _apply_logo_watermark(img)
    img = img.convert("RGB")

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
    apply_logo: bool = True,
) -> Dict[str, Any]:
    """
    抓 API（或用 raw）→ 日期核對 → 產出單張 PNG（除錯／相容用）。
    正式賽日請用 generate_helper_form_parts()。
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
        apply_logo=apply_logo,
    )
    return {
        "ok": True,
        "guard": guard,
        "out_path": str(path),
        "n_races": loaded.get("n_races") or 0,
        "size": list(img.size),
        "stale_rendered": (not loaded.get("ok")),
    }


def generate_helper_form_parts(
    *,
    out_dir: str | Path,
    expected_date: Optional[str] = None,
    expected_course: Optional[str] = None,
    require_course: bool = False,
    raw: Optional[Dict[str, Any]] = None,
    render_even_if_stale: bool = False,
    apply_logo: bool = True,
    file_prefix: str = "helper_form",
) -> Dict[str, Any]:
    """
    抓 API → 日期核對 → 依總場數拆成多幅 PNG（通常 3 幅）+ manifest。
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
            "parts": [],
            "out_dir": str(out_dir),
        }

    races = list(loaded.get("races") or [])
    layout = split_race_layout(len(races))
    chunks = chunk_races(races, layout)

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    # 賽日／場地取自第一場解析結果
    first_parsed = (races[0].get("parsed") if races else {}) or {}
    racing_date = first_parsed.get("racing_date") or (guard.get("api_dates") or [None])[0]
    course = first_parsed.get("course") or (guard.get("api_courses") or [None])[0]

    parts_meta: List[Dict[str, Any]] = []
    for i, chunk in enumerate(chunks, start=1):
        filename = f"{file_prefix}_{i}.png"
        path = directory / filename
        img = render_helper_form_image(chunk, out_path=path, apply_logo=apply_logo)
        race_nums = [r.get("race_num") for r in chunk]
        parts_meta.append(
            {
                "index": i,
                "file": filename,
                "path": str(path),
                "race_nums": race_nums,
                "n_races": len(chunk),
                "size": list(img.size),
            }
        )

    manifest = {
        "ok": True,
        "racing_date": racing_date,
        "course": course,
        "n_races": len(races),
        "layout": layout,
        "parts": parts_meta,
        "guard": guard,
        "stale_rendered": (not loaded.get("ok")),
        "logo": {
            "path": str(_resolve_logo_path() or ""),
            "opacity": LOGO_OPACITY,
        },
    }
    manifest_path = directory / f"{file_prefix}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def default_output_dir() -> Path:
    return ROOT / "ad_output" / "helper_form"


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="產出馬匹歷史戰績表 PNG（預設拆成多幅）")
    ap.add_argument("--out-dir", default=str(default_output_dir()), help="輸出目錄")
    ap.add_argument(
        "--out",
        default=None,
        help="若指定則只產單張（相容舊用法）；省略則拆多幅到 --out-dir",
    )
    ap.add_argument("--expect-date", default=None, help="YYYY-MM-DD；省略則用系統最新賽日")
    ap.add_argument("--expect-course", default=None, help="ST 或 HV")
    ap.add_argument("--require-course", action="store_true")
    ap.add_argument("--from-file", default=None, help="本地 helper JSON fixture")
    ap.add_argument("--max-races", type=int, default=None, help="僅單張模式有效")
    ap.add_argument("--no-logo", action="store_true", help="關閉 logo 水印")
    ap.add_argument(
        "--allow-stale",
        action="store_true",
        help="日期不符仍渲染（僅供視覺對照）",
    )
    args = ap.parse_args()

    raw = None
    if args.from_file:
        raw = json.loads(Path(args.from_file).read_text(encoding="utf-8"))

    apply_logo = not args.no_logo
    if args.out:
        result = generate_helper_form_png(
            out_path=args.out,
            expected_date=args.expect_date,
            expected_course=args.expect_course,
            require_course=args.require_course,
            raw=raw,
            max_races=args.max_races,
            render_even_if_stale=args.allow_stale,
            apply_logo=apply_logo,
        )
    else:
        result = generate_helper_form_parts(
            out_dir=args.out_dir,
            expected_date=args.expect_date,
            expected_course=args.expect_course,
            require_course=args.require_course,
            raw=raw,
            render_even_if_stale=args.allow_stale,
            apply_logo=apply_logo,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
