"""廣告海報：公司原圖風格、最多 4 匹、只顯示馬號＋馬名。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ad_poster import (
    BUNDLED_FONT,
    COMPANY_DIR,
    MODEL_FILE,
    AI_FILE,
    build_payload_from_prediction,
    generate_ads_for_meeting_predictions,
    generate_copy,
    generate_meeting_copy,
    latest_paths,
    render_meeting_poster,
    _cell_text,
    _find_font,
    _load_font,
    _pick_max,
    font_status,
)
from ad_poster import PickItem


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


def test_bundled_font_and_company_assets():
    assert BUNDLED_FONT.is_file()
    assert font_status()["ok"]
    assert _find_font()
    assert (COMPANY_DIR / "blue_header.jpg").is_file()
    assert (COMPANY_DIR / "beige_footer.jpg").is_file()
    assert _pick_max() == 4


def test_cell_text_no_share_pct():
    p = PickItem(5, "金光飛馳", 28.0, "爭勝")
    s = _cell_text(p)
    assert s == "5 金光飛馳"
    assert "%" not in s


def test_company_meeting_poster(tmp_path: Path):
    items = []
    for rn in range(1, 9):
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

    # 最多 4 匹
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

    # 覆蓋同一檔名
    r2 = generate_ads_for_meeting_predictions(
        batch_id="batch_co2",
        race_items=items[:6],
        output_root=tmp_path,
        racing_date="2026-09-09",
        course="HV",
    )
    assert r2["ok"]
    assert {p.name for p in tmp_path.glob("*.png")} == {"model.png", "ai.png"}

    # 強制兩種色調皆可渲染
    for theme in ("blue", "beige"):
        out = tmp_path / f"{theme}.png"
        from ad_poster import RaceAdPayload

        payload = RaceAdPayload(
            race_id="x",
            racing_date="2026-09-09",
            course="HV",
            race_num=1,
            model_picks=[
                PickItem(1, "金光飛馳", 30, "爭勝"),
                PickItem(5, "銀河之星", 22, "推介"),
                PickItem(8, "疾風少年", 15, "推介"),
                PickItem(3, "長城勇士", 12, "推介"),
                PickItem(7, "翠嶺傳奇", 10, "推介"),
            ],
        )
        meta = render_meeting_poster([payload], track="model", out_path=out, theme=theme)
        assert out.is_file()
        assert meta["theme"] == theme
        assert meta["bytes"] <= 2048 * 1024
