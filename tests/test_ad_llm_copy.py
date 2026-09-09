from __future__ import annotations

from pathlib import Path

from ad_llm_copy import AdSocialCopywriter, load_social_copy, save_social_copy


class DummyWriter(AdSocialCopywriter):
    def __init__(self) -> None:
        pass

    def load_formguide_map(self, race_ids):
        return {
            "R1": {1: "直路望空後追回，走勢續進。"},
            "R2": {5: "沿欄省位，末段保持走勢。"},
        }


def _sample_copy():
    return {
        "meeting": {
            "batch_id": "b1",
            "racing_date": "2026-09-09",
            "course": "HV",
            "n_races": 2,
        },
        "races": [
            {
                "race_id": "R1",
                "race_no": 1,
                "race_name": "Race 1",
                "distance": 1200,
                "model_picks": [
                    {"horse_no": 1, "horse_name": "金光飛馳", "tag": "爭勝", "share_pct": 30.0},
                    {"horse_no": 5, "horse_name": "銀河之星", "tag": "推介", "share_pct": 22.0},
                ],
                "ai_picks": [
                    {"horse_no": 1, "horse_name": "金光飛馳", "tag": "爭勝", "share_pct": 28.0},
                ],
            },
            {
                "race_id": "R2",
                "race_no": 2,
                "race_name": "Race 2",
                "distance": 1650,
                "model_picks": [{"horse_no": 5, "horse_name": "銀河之星", "tag": "爭勝", "share_pct": 24.0}],
                "ai_picks": [{"horse_no": 3, "horse_name": "長城勇士", "tag": "推介", "share_pct": 18.0}],
            },
        ],
    }


def test_build_llm_payload_includes_formguide():
    writer = DummyWriter()
    payload = writer.build_llm_payload(_sample_copy(), custom_prompt="偏專業")
    assert '"custom_prompt": "偏專業"' in payload
    assert "直路望空後追回" in payload
    assert "沿欄省位" in payload
    # 同一匹馬若同時在 model / ai 出現，只應出現一次 candidate
    assert payload.count("金光飛馳") == 1


def test_normalize_result_trims_comment_and_hashtags():
    writer = DummyWriter()
    data = writer._normalize_result(
        {
            "title": "今晚三場焦點",
            "subtitle": "保持理性",
            "featured": [
                {
                    "race_no": 1,
                    "race_id": "R1",
                    "horse_no": 1,
                    "horse_name": "金光飛馳",
                    "comment": "這是一段超過四十字的測試評述，應該在正規化之後被安全截短保留前四十字。",
                    "basis": "雙邊支持",
                },
                {
                    "race_no": 1,
                    "race_id": "R1",
                    "horse_no": 5,
                    "horse_name": "銀河之星",
                    "comment": "重覆 race_id 應被去重",
                },
                {
                    "race_no": 2,
                    "race_id": "R2",
                    "horse_no": 5,
                    "horse_name": "銀河之星",
                    "comment": "末段守勢不俗",
                },
                {
                    "race_no": 3,
                    "race_id": "R3",
                    "horse_no": 8,
                    "horse_name": "疾風少年",
                    "comment": "形勢配合可留意",
                },
            ],
            "hashtags": ["J18", "#賽馬", "J18", "夜馬"],
        },
        "偏專業",
    )
    assert data["title"] == "今晚三場焦點"
    assert len(data["featured"]) == 3
    assert len(data["featured"][0]["comment"]) <= 40
    assert data["hashtags"] == ["#J18", "#賽馬", "#夜馬"]


def test_social_copy_roundtrip(tmp_path: Path):
    payload = {"title": "t", "featured": [], "hashtags": ["#J18"]}
    p = save_social_copy(tmp_path, payload)
    assert p.is_file()
    assert load_social_copy(tmp_path)["title"] == "t"
