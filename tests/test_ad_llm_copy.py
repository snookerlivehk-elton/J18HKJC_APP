from __future__ import annotations

from pathlib import Path

from ad_llm_copy import (
    COMMENT_MAX_CHARS,
    DEFAULT_TONE,
    TONE_HIGH_INTERACTION,
    TONE_PROFESSIONAL,
    AdSocialCopywriter,
    build_system_prompt,
    format_social_post_text,
    load_social_copy,
    normalize_tone,
    parse_llm_json,
    post_footer_text,
    save_social_copy,
    tone_label,
)


class DummyWriter(AdSocialCopywriter):
    def __init__(self) -> None:
        pass

    def load_formguide_map(self, race_ids):
        return {
            "R1": {1: "直路望空後追回，走勢續進。"},
            "R2": {5: "沿欄省位，末段保持走勢。"},
            "R3": {8: "形勢配合，值得留意。"},
        }


def _sample_copy():
    return {
        "meeting": {
            "batch_id": "b1",
            "racing_date": "2026-09-09",
            "course": "HV",
            "n_races": 3,
        },
        "races": [
            {
                "race_id": "R1",
                "race_no": 1,
                "race_name": "Race 1",
                "distance": 1200,
                "fused_picks": [
                    {"horse_no": 1, "horse_name": "金光飛馳", "tag": "爭勝", "share_pct": 32.0},
                    {"horse_no": 5, "horse_name": "銀河之星", "tag": "推介", "share_pct": 22.0},
                ],
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
                "fused_picks": [
                    {"horse_no": 5, "horse_name": "銀河之星", "tag": "爭勝", "share_pct": 26.0},
                    {"horse_no": 3, "horse_name": "長城勇士", "tag": "推介", "share_pct": 18.0},
                ],
                "model_picks": [{"horse_no": 5, "horse_name": "銀河之星", "tag": "爭勝", "share_pct": 24.0}],
                "ai_picks": [{"horse_no": 3, "horse_name": "長城勇士", "tag": "推介", "share_pct": 18.0}],
            },
            {
                "race_id": "R3",
                "race_no": 3,
                "race_name": "Race 3",
                "distance": 1000,
                "fused_picks": [
                    {"horse_no": 8, "horse_name": "疾風少年", "tag": "推介", "share_pct": 21.0},
                ],
                "model_picks": [{"horse_no": 8, "horse_name": "疾風少年", "tag": "推介", "share_pct": 20.0}],
                "ai_picks": [{"horse_no": 8, "horse_name": "疾風少年", "tag": "推介", "share_pct": 19.0}],
            },
        ],
    }


def test_normalize_tone_defaults_to_high_interaction():
    assert DEFAULT_TONE == TONE_HIGH_INTERACTION
    assert normalize_tone(None) == TONE_HIGH_INTERACTION
    assert normalize_tone("高互動型") == TONE_HIGH_INTERACTION
    assert normalize_tone("專業型") == TONE_PROFESSIONAL
    assert tone_label("high_interaction") == "高互動型"


def test_build_system_prompt_uses_hk_and_tone():
    prompt = build_system_prompt("high_interaction")
    assert "香港" in prompt
    assert "國語" in prompt
    assert "高互動型" in prompt
    assert "融合推介" in prompt
    assert str(COMMENT_MAX_CHARS) in prompt
    assert "{{" not in prompt


def test_parse_llm_json_from_fence():
    raw = """這是前言\n```json\n{\"title\": \"今晚有睇頭\", \"featured\": []}\n```\n後記"""
    data = parse_llm_json(raw)
    assert data["title"] == "今晚有睇頭"


def test_post_footer_contains_required_lines():
    footer = post_footer_text()
    assert "賽前十分鐘如有變動" in footer
    assert "j18.hk" in footer
    assert "數據僅供參考" in footer
    assert "J18.HK" in footer


def test_build_llm_payload_uses_fused_primary_pool():
    writer = DummyWriter()
    payload = writer.build_llm_payload(
        _sample_copy(), custom_prompt="偏高互動", tone="高互動型"
    )
    assert '"pick_pool": "fused"' in payload
    assert '"candidates_from_fused_primary": true' in payload
    assert f'"comment_max_chars": {COMMENT_MAX_CHARS}' in payload
    assert '"comment_source": "form_text_only"' in payload
    assert '"custom_prompt": "偏高互動"' in payload
    assert '"tone": "high_interaction"' in payload
    assert '"writing_locale": "hong_kong_social"' in payload
    assert "直路望空後追回" in payload
    assert "沿欄省位" in payload
    assert payload.count("金光飛馳") == 1


def test_normalize_result_appends_footer_and_post_text():
    writer = DummyWriter()
    long_comment = "這是一段用來測試評述字數上限的近績改寫，" + ("走勢持續推進。" * 6)
    data = writer._normalize_result(
        {
            "title": "今晚邊場最有睇頭？",
            "subtitle": "留言你心水啦",
            "featured": [
                {
                    "race_no": 1,
                    "race_id": "R1",
                    "horse_no": 1,
                    "horse_name": "金光飛馳",
                    "comment": long_comment,
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
                    "comment": "末段走勢唔錯，有得傾",
                },
            ],
            "hashtags": ["J18", "#賽馬", "J18", "夜馬"],
        },
        "偏高互動",
        tone="高互動型",
        copy_data=_sample_copy(),
    )
    assert data["title"] == "今晚邊場最有睇頭？"
    assert data["tone"] == TONE_HIGH_INTERACTION
    assert len(data["featured"]) == 3
    assert len(long_comment) > COMMENT_MAX_CHARS
    assert len(data["featured"][0]["comment"]) <= COMMENT_MAX_CHARS
    assert "數據僅供參考" in data["footer"]
    assert "賽前十分鐘如有變動" in data["post_text"]
    assert "數據僅供參考" in data["post_text"]
    assert data["post_text"].endswith("\n") or data["post_text"].strip()


def test_normalize_fills_missing_featured_from_fallback():
    writer = DummyWriter()
    data = writer._normalize_result(
        {
            "title": "t",
            "featured": [
                {
                    "race_no": 1,
                    "race_id": "R1",
                    "horse_no": 1,
                    "horse_name": "金光飛馳",
                    "comment": "有睇頭",
                }
            ],
            "hashtags": [],
        },
        "",
        tone="高互動型",
        copy_data=_sample_copy(),
    )
    assert len(data["featured"]) == 3
    assert "數據僅供參考" in format_social_post_text(data)


def test_fallback_prefers_fused_pool():
    writer = DummyWriter()
    rows = writer.build_fallback_featured(_sample_copy(), limit=3)
    assert len(rows) == 3
    assert rows[0]["race_id"] == "R1"
    assert rows[0]["horse_no"] == 1
    assert "融合" in rows[0]["basis"]
    assert len(rows[0]["comment"]) <= COMMENT_MAX_CHARS
    assert {r["race_id"] for r in rows} <= {"R1", "R2", "R3"}


def test_social_copy_roundtrip(tmp_path: Path):
    payload = {"title": "t", "featured": [], "hashtags": ["#J18"], "tone": "high_interaction"}
    p = save_social_copy(tmp_path, payload)
    assert p.is_file()
    assert load_social_copy(tmp_path)["title"] == "t"
