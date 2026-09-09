"""廣告海報：空白模版中段拉伸、最多 4 匹、只顯示馬號＋馬名。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from PIL import Image

from ad_poster import (
    BUNDLED_FONT,
    COMPANY_DIR,
    MODEL_FILE,
    AI_FILE,
    REF_N_ROWS,
    SLICE_MID_END,
    SLICE_TOP_END,
    build_payload_from_prediction,
    generate_ads_for_meeting_predictions,
    generate_meeting_copy,
    latest_paths,
    render_meeting_poster,
    _cell_text,
    _find_font,
    _pick_max,
    font_status,
)
from ad_poster import PickItem, RaceAdPayload


def _sample_pred_df(seed: int = 0) -> pd.DataFrame:
    base = [
        (1, "金光飛馳", 0.28),
        (5, "銀河之星", 0.22),
        (8, "疾風少年", 0.15),
        (3, "長城勇士", 0.12),
        (7, "翠嶺傳奇", 0.10),
        (2, "晴空萬里", 0.08),
    ]
    rows = []
    for i, (no, name, p) in enumerate(base):
        pp = max(0.03, p - seed * 0.01)
        rows.append(
            {
                "馬號": no,
                "馬名": name,
                "模型勝率": pp,
                "模型勝率%": round(pp * 100, 1),
                "總預測分": 1.0 - i * 0.1,
            }
        )
    return pd.DataFrame(rows)


def _payload(rn: int) -> RaceAdPayload:
    return RaceAdPayload(
        race_id=f"R{rn}",
        racing_date="2026-09-09",
        course="HV",
        race_num=rn,
        model_picks=[
            PickItem(1, "金光飛馳", 30, "爭勝"),
            PickItem(5, "銀河之星", 22, "推介"),
            PickItem(8, "疾風少年", 15, "推介"),
            PickItem(3, "長城勇士", 12, "推介"),
            PickItem(7, "翠嶺傳奇", 10, "推介"),
        ],
    )


def test_bundled_font_and_company_assets():
    assert BUNDLED_FONT.is_file()
    assert font_status()["ok"]
    assert _find_font()
    assert (COMPANY_DIR / "blank_blue.jpg").is_file()
    assert _pick_max() == 4


def test_cell_text_no_share_pct():
    p = PickItem(5, "金光飛馳", 28.0, "爭勝")
    s = _cell_text(p)
    assert s == "5 金光飛馳"
    assert "%" not in s


def test_mid_stretch_scales_with_race_count(tmp_path: Path):
    """場數變多／變少時，畫布高度應隨中段拉伸改變，列高近似固定。"""
    ref_mid = SLICE_MID_END - SLICE_TOP_END
    row_ref = ref_mid / float(REF_N_ROWS)
    heights = {}
    for n in (8, 11, 12):
        out = tmp_path / f"n{n}.png"
        meta = render_meeting_poster(
            [_payload(i) for i in range(1, n + 1)],
            track="model",
            out_path=out,
            theme="blue",
        )
        assert out.is_file()
        assert meta["n_races"] == n
        assert abs(meta["row_h"] - row_ref) < 1.0
        with Image.open(out) as im:
            heights[n] = im.size[1]
        assert meta["bytes"] <= 2048 * 1024
    assert heights[12] > heights[11] > heights[8]


def test_company_meeting_poster(tmp_path: Path):
    items = []
    for rn in range(1, 12):
        items.append(
            {
                "race_id": f"R{rn}",
                "race_info": {
                    "racing_date": "2026-09-09",
                    "course": "HV",
                    "race_num": rn,
                    "distance_m": 1200,
                    "track": "A",
                },
                "pred_df": _sample_pred_df(rn % 3),
                "ai_map": {
                    1: (8.5, 0.7, 5.95),
                    5: (7.2, 0.65, 4.68),
                    8: (6.0, 0.55, 3.3),
                    3: (5.5, 0.5, 2.75),
                    7: (5.0, 0.45, 2.25),
                },
            }
        )

    r = generate_ads_for_meeting_predictions(
        batch_id="batch_co",
        race_items=items,
        output_root=tmp_path,
        racing_date="2026-09-09",
        course="HV",
    )
    assert r["ok"]
    assert r["theme"] in ("blue", "beige")
    paths = latest_paths(tmp_path)
    assert paths["model"].name == MODEL_FILE
    assert paths["ai"].name == AI_FILE
    assert paths["model"].is_file() and paths["ai"].is_file()
    assert paths["model"].stat().st_size <= 2048 * 1024
    assert paths["model"].stat().st_size > 20_000

    assert all(len(x["model_picks"]) <= 4 for x in __import__("json").loads(paths["copy"].read_text())["races"])

    copy = generate_meeting_copy(
        [
            build_payload_from_prediction(
                race_id="R1",
                race_info=items[0]["race_info"],
                pred_df=items[0]["pred_df"],
                ai_map=items[0]["ai_map"],
            )
        ],
        "model",
    )
    assert "%" not in copy["full"]
    assert "金光飛馳" in copy["full"] or "銀河之星" in copy["full"]

    r2 = generate_ads_for_meeting_predictions(
        batch_id="batch_co2",
        race_items=items[:6],
        output_root=tmp_path,
        racing_date="2026-09-09",
        course="HV",
    )
    assert r2["ok"]
    assert {p.name for p in tmp_path.glob("*.png")} == {"model.png", "ai.png"}

    # blue／beige 皆可渲染（beige 無 blank 時 fallback blank_blue）
    for theme in ("blue", "beige"):
        out = tmp_path / f"{theme}.png"
        meta = render_meeting_poster([_payload(1)], track="model", out_path=out, theme=theme)
        assert out.is_file()
        assert meta["theme"] == theme
        assert meta["blank"].startswith("blank_")
        assert meta["bytes"] <= 2048 * 1024
