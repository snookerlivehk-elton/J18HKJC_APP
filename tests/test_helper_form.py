"""helper form：日期核對、正規化、PNG 渲染。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from helper_form_client import (
    guard_helper_against_latest,
    normalize_helper_payload,
    parse_race_title,
)
from helper_form_poster import generate_helper_form_png, render_helper_form_image

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "helper_form_ST_20261001_R1R2.json"


@pytest.fixture(scope="module")
def helper_raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_race_title_zh():
    p = parse_race_title("2026年10月1日 13:00 沙田 草地 第一場 1200米")
    assert p is not None
    assert p.racing_date == "2026-10-01"
    assert p.post_time == "13:00"
    assert p.course == "ST"
    assert p.venue_label == "沙田"
    assert p.surface == "草地"
    assert p.race_num == 1
    assert p.distance_m == 1200


def test_parse_race_title_hv_night():
    p = parse_race_title("2026年9月16日 19:10 跑馬地草地 第八場 1000米")
    assert p is not None
    assert p.racing_date == "2026-09-16"
    assert p.course == "HV"
    assert p.surface == "草地"
    assert p.race_num == 8
    assert p.distance_m == 1000


def test_guard_ok_when_dates_match(helper_raw):
    g = guard_helper_against_latest(helper_raw, expected_date="2026-10-01")
    assert g.ok
    assert g.status == "ok"
    assert g.api_dates == ["2026-10-01"]


def test_guard_stale_when_date_mismatch(helper_raw):
    g = guard_helper_against_latest(helper_raw, expected_date="2026-09-16")
    assert not g.ok
    assert g.status == "stale"
    assert "不符" in g.message


def test_guard_inconsistent_dates(helper_raw):
    raw = json.loads(json.dumps(helper_raw))
    raw["data"]["2"]["title"] = "2026年9月16日 19:40 跑馬地 草地 第二場 1200米"
    g = guard_helper_against_latest(raw, expected_date="2026-10-01")
    assert not g.ok
    assert g.status == "inconsistent"


def test_normalize_chinese_columns(helper_raw):
    norm = normalize_helper_payload(helper_raw)
    assert norm["n_races"] == 2
    race = norm["races"][0]
    labels = [c["label"] for c in race["columns"]]
    assert "馬名" in labels
    assert "負磅" in labels  # 負榜→負磅
    assert "出道至今" in labels
    assert "更變裝備" in labels or any("裝備" in x for x in labels)
    groups = [g["name"] for g in race["groups"]]
    assert groups == ["馬匹資料", "馬匹統計數字", "備註"]
    row0 = race["rows"][0]
    assert row0["name"]
    assert row0["cells"]["match_work"] in ("是", "否")


def test_render_png_matches_width(helper_raw, tmp_path):
    norm = normalize_helper_payload(helper_raw)
    out = tmp_path / "helper_form.png"
    img = render_helper_form_image(norm["races"], out_path=out)
    assert out.is_file()
    assert img.size[0] == 1280
    assert img.size[1] > 400


def test_generate_blocks_stale_by_default(helper_raw, tmp_path):
    out = tmp_path / "blocked.png"
    result = generate_helper_form_png(
        out_path=out,
        expected_date="2026-09-16",
        raw=helper_raw,
        render_even_if_stale=False,
    )
    assert result["ok"] is False
    assert not out.exists()


def test_generate_allow_stale(helper_raw, tmp_path):
    out = tmp_path / "stale_ok.png"
    result = generate_helper_form_png(
        out_path=out,
        expected_date="2026-09-16",
        raw=helper_raw,
        render_even_if_stale=True,
    )
    assert result["ok"] is True
    assert result["stale_rendered"] is True
    assert out.is_file()
