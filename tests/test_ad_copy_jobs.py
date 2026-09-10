"""Tests for Phase D ad copy automation jobs."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from ad_copy_jobs import (
    build_post_race_fallback,
    format_post_race_post_text,
    generate_post_race_copy,
    job_done_for_batch,
    promo_hits_to_dict,
    run_auto_post_race_copy,
    run_auto_promo_hits,
    run_auto_social_copy,
    write_archive_version,
)


def test_archive_and_job_done(tmp_path: Path):
    data = {
        "meeting": {"batch_id": "b1", "racing_date": "2026-09-09", "course": "HV"},
        "featured": [{"race_id": "R1"}],
    }
    write_archive_version(tmp_path, "2026-09-09", "HV", "social", data)
    assert job_done_for_batch(tmp_path, "2026-09-09", "HV", "social", "b1")
    assert not job_done_for_batch(tmp_path, "2026-09-09", "HV", "social", "b2")


def test_build_post_race_fallback_and_format():
    promo = {
        "meeting": {"racing_date": "2026-09-06", "course": "ST", "batch_id": "b9"},
        "n_promo_races": 2,
        "promo_races": [
            {
                "race_id": "20260906ST01",
                "picks": "1:3 飛馬 / 2:5 星河",
                "win_odds7": True,
                "qin_odds10": False,
                "t3_cover": True,
                "t4_cover": False,
                "any_promo": True,
            },
            {
                "race_id": "20260906ST03",
                "picks": "1:8 疾風",
                "win_odds7": False,
                "qin_odds10": True,
                "t3_cover": False,
                "t4_cover": False,
                "any_promo": True,
            },
        ],
    }
    out = build_post_race_fallback(promo)
    assert out["featured"]
    assert "賽後" in out["title"] or "回顧" in out["title"]
    text = format_post_race_post_text(out)
    assert "第1場" in text or "第" in text
    assert out["source"] == "fallback"


def test_generate_post_race_copy_no_api_uses_fallback():
    promo = {
        "meeting": {"racing_date": "2026-09-06", "course": "ST"},
        "n_promo_races": 1,
        "promo_races": [
            {
                "race_id": "20260906ST01",
                "picks": "1:3 飛馬",
                "win_odds7": True,
                "qin_odds10": False,
                "t3_cover": False,
                "t4_cover": False,
                "any_promo": True,
            }
        ],
    }
    writer = MagicMock()
    writer.is_ready.return_value = False
    out = generate_post_race_copy(promo, writer=writer)
    assert out["featured"]
    assert "fallback" in str(out.get("source"))


def test_run_auto_social_copy_waiting_without_copy_json(tmp_path: Path):
    r = run_auto_social_copy(
        racing_date="2026-09-09",
        course="HV",
        batch_id="b1",
        output_root=tmp_path,
        force=True,
    )
    assert r["ok"] is False
    assert r.get("waiting") is True


def test_run_auto_social_copy_dry_run_with_copy(tmp_path: Path):
    copy = {
        "meeting": {"batch_id": "b1", "racing_date": "2026-09-09", "course": "HV"},
        "races": [
            {
                "race_id": "R1",
                "race_no": 1,
                "fused_picks": [{"horse_no": 1, "horse_name": "甲"}],
            }
        ],
    }
    (tmp_path / "copy.json").write_text(json.dumps(copy), encoding="utf-8")
    r = run_auto_social_copy(
        racing_date="2026-09-09",
        course="HV",
        batch_id="b1",
        output_root=tmp_path,
        dry_run=True,
    )
    assert r["ok"] is True
    assert r.get("dry_run") is True


def test_run_auto_social_copy_generates(tmp_path: Path):
    copy = {
        "meeting": {"batch_id": "b1", "racing_date": "2026-09-09", "course": "HV"},
        "races": [
            {
                "race_id": "R1",
                "race_no": 1,
                "fused_picks": [{"horse_no": 1, "horse_name": "甲"}],
                "model_picks": [{"horse_no": 1, "horse_name": "甲"}],
                "ai_picks": [{"horse_no": 1, "horse_name": "甲"}],
            },
            {
                "race_id": "R2",
                "race_no": 2,
                "fused_picks": [{"horse_no": 2, "horse_name": "乙"}],
                "model_picks": [],
                "ai_picks": [],
            },
            {
                "race_id": "R3",
                "race_no": 3,
                "fused_picks": [{"horse_no": 3, "horse_name": "丙"}],
                "model_picks": [],
                "ai_picks": [],
            },
        ],
    }
    (tmp_path / "copy.json").write_text(
        json.dumps(copy, ensure_ascii=False), encoding="utf-8"
    )

    mock_writer = MagicMock()
    mock_writer.is_ready.return_value = True
    mock_writer.generate_social_copy.return_value = {
        "title": "今晚有睇頭",
        "subtitle": "",
        "featured": [
            {"race_no": 1, "race_id": "R1", "horse_no": 1, "horse_name": "甲", "comment": "走勢續進"}
        ],
        "hashtags": ["#J18"],
        "post_text": "x",
        "source": "llm",
    }

    with patch("ad_copy_jobs.AdSocialCopywriter", return_value=mock_writer):
        r = run_auto_social_copy(
            racing_date="2026-09-09",
            course="HV",
            batch_id="b1",
            output_root=tmp_path,
            force=True,
        )
    assert r["ok"] is True
    assert (tmp_path / "social_copy.json").is_file()
    assert job_done_for_batch(tmp_path, "2026-09-09", "HV", "social", "b1")

    # idempotent skip
    with patch("ad_copy_jobs.AdSocialCopywriter", return_value=mock_writer):
        r2 = run_auto_social_copy(
            racing_date="2026-09-09",
            course="HV",
            batch_id="b1",
            output_root=tmp_path,
            force=False,
        )
    assert r2.get("skipped") is True


def test_promo_hits_to_dict_and_post_race_skip_zero():
    race_df = pd.DataFrame(
        [
            {
                "賽日": "2026-09-06",
                "場地": "ST",
                "batch_id": "b9",
                "race_id": "20260906ST01",
                "推介數": 2,
                "推介": "1:3 飛馬",
                "WIN≥7": True,
                "冠亞+賠>10": False,
                "T3覆蓋": False,
                "T4覆蓋": False,
                "可宣傳": True,
            }
        ]
    )
    summary = pd.DataFrame([{"原則": "1", "命中場次": 1}])
    meta = {"batch_ids": ["b9"], "n_promo_races": 1, "n_races_scored": 1}
    payload = promo_hits_to_dict(
        race_df, summary, meta, racing_date="2026-09-06", course="ST"
    )
    assert payload["n_promo_races"] == 1
    assert payload["promo_races"]

    # zero promo → skip copy
    empty = {
        "meeting": {"batch_id": "b0", "racing_date": "2026-09-06", "course": "ST"},
        "n_promo_races": 0,
        "promo_races": [],
    }
    r = run_auto_post_race_copy(
        racing_date="2026-09-06",
        course="ST",
        promo=empty,
        batch_id="b0",
        output_root=Path("/tmp/ad_copy_test_empty"),
        force=True,
    )
    assert r["ok"] is True
    assert r.get("skipped") is True


def test_run_auto_promo_hits_mocked(tmp_path: Path):
    race_df = pd.DataFrame(
        [
            {
                "賽日": "2026-09-06",
                "場地": "ST",
                "batch_id": "b9",
                "race_id": "20260906ST01",
                "推介數": 1,
                "推介": "1:3",
                "WIN≥7": True,
                "冠亞+賠>10": False,
                "T3覆蓋": False,
                "T4覆蓋": False,
                "可宣傳": True,
            }
        ]
    )
    summary = pd.DataFrame()
    meta = {"batch_ids": ["b9"], "n_promo_races": 1, "n_races_scored": 1}

    cal = MagicMock()
    cal.evaluate_ad_promo_hits.return_value = (race_df, summary, meta)

    with patch("factor_calibration.FactorCalibration", return_value=cal):
        # also patch resolve used when batch_ids given — not needed
        r = run_auto_promo_hits(
            racing_date="2026-09-06",
            course="ST",
            batch_ids=["b9"],
            output_root=tmp_path,
            force=True,
        )
    assert r["ok"] is True
    assert r["n_promo_races"] == 1
    assert (tmp_path / "promo_hits.json").is_file()
