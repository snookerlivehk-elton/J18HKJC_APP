"""Tests for pre-race Form AI → snapshot → social_copy cascade."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ad_copy_jobs import (
    maybe_run_pre_race_cascade_after_form_ai,
    maybe_run_pre_race_cascade_after_snapshot,
    pre_race_cascade_enabled,
    run_pre_race_ad_cascade,
)


def test_pre_race_cascade_enabled_default(monkeypatch):
    monkeypatch.delenv("MEETING_PRE_RACE_AD_CASCADE", raising=False)
    assert pre_race_cascade_enabled() is True
    monkeypatch.setenv("MEETING_PRE_RACE_AD_CASCADE", "false")
    assert pre_race_cascade_enabled() is False


def test_cascade_waits_when_form_ai_not_ready(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MEETING_PRE_RACE_AD_CASCADE", "true")
    with patch(
        "ad_copy_jobs.form_ai_ready_for_cascade", return_value=(False, "0/100")
    ):
        out = run_pre_race_ad_cascade(
            racing_date="2026-09-30",
            course="ST",
            output_root=tmp_path,
            require_form_ai=True,
        )
    assert out["ok"] is False
    assert out.get("waiting") is True
    assert out["actions"][0]["action"] == "wait_form_ai"


def test_cascade_snapshot_then_social(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MEETING_PRE_RACE_AD_CASCADE", "true")
    (tmp_path / "copy.json").write_text(
        '{"meeting":{"racing_date":"2026-09-30","course":"ST","batch_id":"b1"},'
        '"races":[{"race_num":1,"fused_picks":[{"horse_no":1}]}]}',
        encoding="utf-8",
    )

    snap = {
        "ok": True,
        "batch_id": "b1",
        "ad_ok": True,
        "ad_output": {"ok": True},
    }
    social = {
        "ok": True,
        "batch_id": "b1",
        "n_featured": 2,
        "source": "llm",
    }

    with patch(
        "ad_copy_jobs.form_ai_ready_for_cascade", return_value=(True, "90/100")
    ), patch(
        "ad_copy_jobs.snapshot_ready_for_cascade", return_value=(False, "pending")
    ), patch(
        "factor_calibration.FactorCalibration"
    ) as cal_cls, patch(
        "ad_copy_jobs.run_auto_social_copy", return_value=social
    ) as social_fn:
        cal_cls.return_value.snapshot_meeting.return_value = snap
        out = run_pre_race_ad_cascade(
            racing_date="2026-09-30",
            course="ST",
            output_root=tmp_path,
        )

    assert out["ok"] is True
    assert out["batch_id"] == "b1"
    actions = [a["action"] for a in out["actions"]]
    assert "snapshot" in actions
    assert "social_copy" in actions
    social_fn.assert_called_once()


def test_after_snapshot_skips_rebuild(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MEETING_PRE_RACE_AD_CASCADE", "true")
    (tmp_path / "copy.json").write_text(
        '{"meeting":{"racing_date":"2026-09-30","course":"HV","batch_id":"b9"},'
        '"races":[{"race_num":1}]}',
        encoding="utf-8",
    )
    social = {"ok": True, "skipped": True, "reason": "already", "batch_id": "b9"}

    with patch(
        "ad_copy_jobs.run_auto_social_copy", return_value=social
    ) as social_fn, patch(
        "ad_poster.generate_ads_from_snapshot_batch"
    ) as ads_fn:
        out = maybe_run_pre_race_cascade_after_snapshot(
            racing_date="2026-09-30",
            course="HV",
            batch_id="b9",
            output_root=tmp_path,
            snapshot_ad_ok=True,
        )

    assert out["ok"] is True
    social_fn.assert_called_once()
    ads_fn.assert_not_called()


def test_after_form_ai_disabled(monkeypatch):
    monkeypatch.setenv("MEETING_PRE_RACE_AD_CASCADE", "0")
    out = maybe_run_pre_race_cascade_after_form_ai(
        racing_date="2026-09-30", course="ST"
    )
    assert out.get("skipped") is True


def test_complete_stage_form_ai_already_ok_cascades():
    from meeting_pipeline import MeetingPipeline, STATUS_OK

    pipe = MeetingPipeline.__new__(MeetingPipeline)
    pipe.check_form_ai = MagicMock(return_value=(STATUS_OK, "90/100"))
    pipe.refresh_readiness = MagicMock(return_value={})
    pipe.run_action = MagicMock()

    with patch(
        "ad_copy_jobs.maybe_run_pre_race_cascade_after_form_ai",
        return_value={"ok": True, "batch_id": "bx"},
    ) as casc:
        out = MeetingPipeline.complete_stage(pipe, "2026-09-30", "ST", "FORM_AI")

    assert out["ok"] is True
    assert out.get("skipped_ai") is True
    assert out["pre_race_cascade"]["batch_id"] == "bx"
    pipe.run_action.assert_not_called()
    casc.assert_called_once()
