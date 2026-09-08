"""廣告海報模組：不連 DB，用樣本推介渲染 PNG + 文案。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ad_poster import (
    PickItem,
    RaceAdPayload,
    build_payload_from_prediction,
    generate_ads_for_meeting_predictions,
    generate_copy,
    render_poster_png,
)


def _sample_pred_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"馬號": 1, "馬名": "金光飛馳", "模型勝率": 0.28, "模型勝率%": 28.0, "總預測分": 1.2},
            {"馬號": 5, "馬名": "銀河之星", "模型勝率": 0.22, "模型勝率%": 22.0, "總預測分": 0.9},
            {"馬號": 8, "馬名": "疾風少年", "模型勝率": 0.15, "模型勝率%": 15.0, "總預測分": 0.4},
            {"馬號": 3, "馬名": "長城勇士", "模型勝率": 0.12, "模型勝率%": 12.0, "總預測分": 0.2},
            {"馬號": 7, "馬名": "翠嶺傳奇", "模型勝率": 0.10, "模型勝率%": 10.0, "總預測分": 0.1},
            {"馬號": 2, "馬名": "晴空萬里", "模型勝率": 0.08, "模型勝率%": 8.0, "總預測分": 0.0},
            {"馬號": 4, "馬名": "紅日東升", "模型勝率": 0.05, "模型勝率%": 5.0, "總預測分": -0.2},
        ]
    )


def test_build_payload_and_copy():
    info = {
        "racing_date": "2026-09-10",
        "course": "ST",
        "race_num": 3,
        "race_name": "測試賽",
        "distance_m": 1200,
        "track": "草地",
    }
    ai_map = {
        1: (8.5, 0.7, 5.95),
        5: (7.2, 0.6, 4.32),
        8: (6.0, 0.5, 3.0),
        3: (5.0, 0.4, 2.0),
    }
    payload = build_payload_from_prediction(
        race_id="20260910ST03",
        race_info=info,
        pred_df=_sample_pred_df(),
        ai_map=ai_map,
    )
    assert payload.model_picks, "應有模型推介"
    assert payload.model_picks[0].tag in ("爭勝", "推介")
    model_copy = generate_copy(payload, "model")
    assert "模型推介" in model_copy["headline"]
    assert "金光飛馳" in model_copy["full"] or "銀河之星" in model_copy["full"]


def test_bundled_cjk_font_and_glyph_size():
    """Railway 無系統中文字型時，必須用內嵌字型；中文 bbox 高度應接近字級。"""
    from ad_poster import BUNDLED_FONT, _find_font, _load_font, font_status

    assert BUNDLED_FONT.is_file(), "assets/fonts/wqy-microhei.ttc 必須隨 repo 部署"
    st = font_status()
    assert st["ok"], st
    assert _find_font()
    font = _load_font(48)
    # FreeTypeFont.getbbox；預設點陣字對中文幾乎無高度
    bbox = font.getbbox("爭勝 金光飛馳")
    h = bbox[3] - bbox[1]
    w = bbox[2] - bbox[0]
    assert h >= 36, f"中文字高過矮（疑似非 TrueType）: {h}"
    assert w >= 180, f"中文字寬過窄（疑似缺字）: {w}"


def test_render_png_and_meeting_ads(tmp_path: Path):
    payload = RaceAdPayload(
        race_id="demo_r1",
        racing_date="2026-09-10",
        course="HV",
        race_num=1,
        race_name="示範盃",
        distance_m=1000,
        track="草地",
        model_picks=[
            PickItem(1, "金光飛馳", 30.0, "爭勝"),
            PickItem(5, "銀河之星", 22.0, "推介"),
        ],
        ai_picks=[
            PickItem(5, "銀河之星", 35.0, "爭勝"),
            PickItem(1, "金光飛馳", 25.0, "推介"),
        ],
    )
    out_m = tmp_path / "m.png"
    out_a = tmp_path / "a.png"
    render_poster_png(payload, track="model", out_path=out_m)
    render_poster_png(payload, track="ai", out_path=out_a)
    assert out_m.is_file() and out_m.stat().st_size > 5_000
    assert out_a.is_file() and out_a.stat().st_size > 5_000

    items = [
        {
            "race_id": "demo_r1",
            "race_info": {
                "racing_date": "2026-09-10",
                "course": "HV",
                "race_num": 1,
                "race_name": "示範盃",
                "distance_m": 1000,
                "track": "草地",
            },
            "pred_df": _sample_pred_df(),
            "ai_map": {
                1: (8.5, 0.7, 5.95),
                5: (7.2, 0.6, 4.32),
                8: (6.0, 0.55, 3.3),
            },
        }
    ]
    result = generate_ads_for_meeting_predictions(
        batch_id="test_batch_demo",
        race_items=items,
        output_root=tmp_path,
        racing_date="2026-09-10",
        course="HV",
    )
    assert result["ok"]
    assert result["races_written"] == 1
    batch_dir = tmp_path / "test_batch_demo"
    assert (batch_dir / "demo_r1_model.jpg").is_file()
    assert (batch_dir / "demo_r1_ai.jpg").is_file()
    assert (batch_dir / "demo_r1_copy.json").is_file()
    assert (batch_dir / "copy.json").is_file()
    # 體積應遠小於舊版 2MB PNG
    assert (batch_dir / "demo_r1_model.jpg").stat().st_size < 800_000
    from ad_poster import make_preview_jpeg, zip_batch_bytes

    thumb = make_preview_jpeg(batch_dir / "demo_r1_model.jpg")
    assert len(thumb) < 200_000
    z = zip_batch_bytes(batch_dir)
    assert len(z) > 1000