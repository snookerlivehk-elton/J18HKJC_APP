"""廣告海報：全賽日單張 model/ai，≤800KB，固定檔名覆蓋。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ad_poster import (
    BUNDLED_FONT,
    build_payload_from_prediction,
    generate_ads_for_meeting_predictions,
    generate_copy,
    generate_meeting_copy,
    latest_paths,
    render_meeting_poster,
    render_poster_png,
    _find_font,
    _load_font,
    font_status,
)


def _sample_pred_df(seed: int = 0) -> pd.DataFrame:
    base = [
        (1, "金光飛馳", 0.28),
        (5, "銀河之星", 0.22),
        (8, "疾風少年", 0.15),
        (3, "長城勇士", 0.12),
        (7, "翠嶺傳奇", 0.10),
        (2, "晴空萬里", 0.08),
        (4, "紅日東升", 0.05),
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
    assert payload.model_picks
    model_copy = generate_copy(payload, "model")
    assert "模型推介" in model_copy["headline"]


def test_bundled_cjk_font_and_glyph_size():
    assert BUNDLED_FONT.is_file()
    st = font_status()
    assert st["ok"], st
    assert _find_font()
    font = _load_font(48)
    bbox = font.getbbox("爭勝 金光飛馳")
    assert (bbox[3] - bbox[1]) >= 36
    assert (bbox[2] - bbox[0]) >= 180


def test_meeting_poster_overwrite_and_size(tmp_path: Path):
    items = []
    for rn in range(1, 9):
        items.append(
            {
                "race_id": f"R{rn}",
                "race_info": {
                    "racing_date": "2026-09-09",
                    "course": "HV",
                    "race_num": rn,
                    "race_name": f"第{rn}場",
                    "distance_m": 1200,
                    "track": "A",
                },
                "pred_df": _sample_pred_df(rn % 3),
                "ai_map": {
                    1: (8.5, 0.7, 5.95),
                    5: (7.2, 0.65, 4.68),
                    8: (6.0, 0.55, 3.3),
                },
            }
        )

    r1 = generate_ads_for_meeting_predictions(
        batch_id="batch_a",
        race_items=items,
        output_root=tmp_path,
        racing_date="2026-09-09",
        course="HV",
    )
    assert r1["ok"]
    paths = latest_paths(tmp_path)
    assert paths["model"].is_file() and paths["ai"].is_file() and paths["copy"].is_file()
    assert paths["model"].stat().st_size <= 800 * 1024
    assert paths["ai"].stat().st_size <= 800 * 1024
    mtime1 = paths["model"].stat().st_mtime
    size1 = paths["model"].stat().st_size

    # 再次生成應覆蓋同一檔名
    items2 = items[:6]
    r2 = generate_ads_for_meeting_predictions(
        batch_id="batch_b",
        race_items=items2,
        output_root=tmp_path,
        racing_date="2026-09-09",
        course="HV",
    )
    assert r2["ok"]
    assert paths["model"].is_file()
    assert {p.name for p in tmp_path.glob("*.jpg")} == {"model.jpg", "ai.jpg"}
    copy = (tmp_path / "copy.json").read_text(encoding="utf-8")
    assert "batch_b" in copy
    assert r2["races_written"] == 6
    assert paths["model"].stat().st_size <= 800 * 1024
    _ = mtime1, size1  # first write existed; second overwrote same path

    # 單場相容 API
    from ad_poster import RaceAdPayload, PickItem

    p = RaceAdPayload(
        race_id="x",
        racing_date="2026-09-09",
        course="HV",
        race_num=1,
        model_picks=[PickItem(1, "金光飛馳", 30, "爭勝")],
        ai_picks=[PickItem(1, "金光飛馳", 40, "爭勝")],
    )
    out = tmp_path / "single.jpg"
    render_poster_png(p, track="model", out_path=out)
    assert out.is_file() and out.stat().st_size <= 800 * 1024

    mc = generate_meeting_copy(
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
    assert "全賽日" in mc["headline"]
    assert "J18.HK" in mc["full"]
    assert "J18AI" not in mc["full"]
    assert "J18AI" not in mc["headline"]
