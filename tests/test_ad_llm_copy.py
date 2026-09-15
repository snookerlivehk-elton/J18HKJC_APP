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
    assert "綜合分析名單" in prompt or "綜合分析" in prompt
    assert "投注" in prompt  # 禁用作引導／出現喺禁用說明
    assert "研究" in prompt or "統計" in prompt
    assert "#賽事數據" in prompt or "#模型分析" in prompt
    assert str(COMMENT_MAX_CHARS) in prompt
    assert "近績" in prompt and "本場" in prompt  # 賽前時間線規則
    assert "{{" not in prompt


def test_frame_prerace_comment_marks_past_form():
    from ad_llm_copy import _frame_as_prerace_form_comment, _humanize_comment

    raw = "本場銀亮濠俠以中等步速出閘，走二疊第二位，直路上進展不大，值得留意其走勢是否會有改變。"
    framed = _frame_as_prerace_form_comment(raw)
    assert framed.startswith("近績")
    assert "本場" not in framed[:4]
    assert "出閘" in framed

    canned = (
        "棒棒糖以極快步速出閘，領放馬稍後位置，直路上仍居第三位，"
        "但進一步落後領放馬，值得留意其是否能夠挑戰領放馬"
    )
    out = _humanize_comment(canned, daypart="今晚")
    assert out.startswith("近績")
    assert "值得留意其是否能夠挑戰領放馬" not in out
    assert len(out) <= COMMENT_MAX_CHARS

    already = "近績：直路望空後追回，走勢續進。"
    assert _frame_as_prerace_form_comment(already) == already


def test_parse_llm_json_from_fence():
    raw = """這是前言\n```json\n{\"title\": \"今晚有睇頭\", \"featured\": []}\n```\n後記"""
    data = parse_llm_json(raw)
    assert data["title"] == "今晚有睇頭"


def test_post_footer_contains_required_lines():
    footer = post_footer_text()
    assert "j18.hk" in footer.lower()
    assert "不構成投注建議" in footer
    assert ("未滿18" in footer) or ("未滿18歲" in footer) or ("18歲" in footer)
    assert "資料研究" in footer or "研究" in footer


def test_build_llm_payload_uses_fused_primary_pool():
    writer = DummyWriter()
    payload = writer.build_llm_payload(
        _sample_copy(), custom_prompt="偏高互動", tone="高互動型"
    )
    assert '"pick_pool": "fused"' in payload
    assert '"candidates_from_fused_primary": true' in payload
    assert f'"comment_max_chars": {COMMENT_MAX_CHARS}' in payload
    assert '"comment_source": "form_text_only"' in payload
    assert '"prerace_copy": true' in payload
    assert '"form_comments_must_mark_past_runs": true' in payload
    assert '"featured_fused_top_n": 2' in payload
    assert '"distinct_observation_angles"' in payload
    # top-N=2：R1 fused 只有頭兩匹進入 candidates（唔含第三）
    assert payload.count('"horse_no": 1') >= 1
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
            "subtitle": "留言你點睇呢個模型觀察啦",
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
    assert "不構成投注建議" in data["footer"]
    assert "j18.hk" in data["post_text"].lower()
    assert "不構成投注建議" in data["post_text"]
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
    assert "不構成投注建議" in format_social_post_text(data)


def test_normalize_remaps_outside_fused_top_n_and_adds_pick_reason(monkeypatch):
    monkeypatch.setenv("AD_FEATURED_FUSED_TOP_N", "2")
    writer = DummyWriter()
    copy = _sample_copy()
    # R1 加第 3 匹 fused，模擬 LLM 誤揀 tip #3
    copy["races"][0]["fused_picks"].append(
        {"horse_no": 9, "horse_name": "後備駒", "tag": "觀察", "share_pct": 10.0}
    )
    data = writer._normalize_result(
        {
            "title": "今晚邊場？",
            "featured": [
                {
                    "race_no": 1,
                    "race_id": "R1",
                    "horse_no": 9,
                    "horse_name": "後備駒",
                    "comment": "本場後備駒以極快步速出閘，直路上進展不大。",
                    "angle": "步速",
                },
                {
                    "race_no": 2,
                    "race_id": "R2",
                    "horse_no": 5,
                    "horse_name": "銀河之星",
                    "comment": "沿欄省位，末段保持走勢。",
                    "angle": "走位",
                },
                {
                    "race_no": 3,
                    "race_id": "R3",
                    "horse_no": 8,
                    "horse_name": "疾風少年",
                    "comment": "形勢配合，值得留意。",
                    "angle": "恢復",
                },
            ],
            "hashtags": ["#日馬", "#沙田", "#J18"],
        },
        "",
        tone="高互動型",
        copy_data={
            "meeting": {
                "racing_date": "2026-09-16",
                "course": "HV",
                "session": "夜",
            },
            "races": copy["races"],
        },
    )
    f0 = data["featured"][0]
    assert f0["horse_no"] != 9
    assert f0["horse_no"] in {1, 5}  # top-2 of R1 fused
    assert f0["pick_reason"]["selected_by"] == "remapped"
    assert "綜合第" in f0["pick_reason"]["label"] or "已校正" in f0["pick_reason"]["label"]
    angles = [r.get("angle") for r in data["featured"]]
    assert len(set(angles)) == 3
    endings = [r["comment"] for r in data["featured"]]
    assert len(set(endings)) == 3
    assert "#夜馬" in data["hashtags"]
    assert "#日馬" not in data["hashtags"]
    assert "#跑馬地" in data["hashtags"]
    assert "#沙田" not in data["hashtags"]
    assert "#日馬" not in data["post_text"]


def test_normalize_frames_live_sounding_comments():
    writer = DummyWriter()
    data = writer._normalize_result(
        {
            "title": "今晚邊場數據差異最值得一齊睇？",
            "subtitle": "以下三場數據評述，哪一個你覺得最吸引？",
            "featured": [
                {
                    "race_no": 1,
                    "race_id": "R1",
                    "horse_no": 1,
                    "horse_name": "金光飛馳",
                    "comment": "本場金光飛馳以中等步速出閘，直路上進展不大。",
                },
                {
                    "race_no": 2,
                    "race_id": "R2",
                    "horse_no": 5,
                    "horse_name": "銀河之星",
                    "comment": (
                        "銀河之星以極快步速出閘，領放馬稍後位置，"
                        "值得留意其是否能夠挑戰領放馬"
                    ),
                },
                {
                    "race_no": 3,
                    "race_id": "R3",
                    "horse_no": 8,
                    "horse_name": "疾風少年",
                    "comment": (
                        "疾風少年以極快步速出閘，居最後數位之內，"
                        "值得留意其是否能夠挑戰領放馬"
                    ),
                },
            ],
            "hashtags": ["#J18"],
        },
        "",
        tone="高互動型",
        copy_data={
            "meeting": {
                "racing_date": "2026-09-16",
                "course": "HV",
                "session": "夜",
            },
            "races": _sample_copy()["races"],
        },
    )
    comments = [r["comment"] for r in data["featured"]]
    assert all(c.startswith("近績") for c in comments)
    assert all("本場" not in c[:6] for c in comments)
    assert "值得留意其是否能夠挑戰領放馬" not in "".join(comments)
    # 兩場原本同一罐頭收尾，normalize 後唔應完全相同
    assert len(set(comments)) == 3


def test_fallback_prefers_fused_pool():
    writer = DummyWriter()
    rows = writer.build_fallback_featured(_sample_copy(), limit=3)
    assert len(rows) == 3
    assert rows[0]["race_id"] == "R1"
    assert rows[0]["horse_no"] == 1
    assert "綜合" in rows[0]["basis"]
    assert len(rows[0]["comment"]) <= COMMENT_MAX_CHARS
    assert {r["race_id"] for r in rows} <= {"R1", "R2", "R3"}


def test_social_copy_roundtrip(tmp_path: Path):
    payload = {"title": "t", "featured": [], "hashtags": ["#J18"], "tone": "high_interaction"}
    p = save_social_copy(tmp_path, payload)
    assert p.is_file()
    assert load_social_copy(tmp_path)["title"] == "t"


def test_format_social_day_meeting_no_tonight_or_system():
    from ad_llm_copy import format_social_post_text

    copy_data = {
        "meeting": {
            "racing_date": "2026-09-13",
            "course": "ST",
            "session": "日",
        }
    }
    social = {
        "title": "今晚沙田邊場最有睇頭？",
        "subtitle": "LLM 暫時未能完成，已用推介自動補齊精選",
        "featured": [
            {
                "race_no": 1,
                "horse_no": 7,
                "horse_name": "增旺",
                "comment": "能量：18% 1W1W 直路望空",
            }
        ],
        "hashtags": ["#賽馬", "#J18HK", "#extra1", "#extra2"],
        "footer": post_footer_text(),
    }
    text = format_social_post_text(social, copy_data=copy_data)
    assert "今晚" not in text
    assert ("聽日" in text) or ("今日" in text)
    assert "LLM 暫時未能" not in text
    assert "自動補齊" not in text
    assert "能量" not in text
    assert "1W1W" not in text
    assert "#沙田" in text
    assert "#日馬" in text
    assert text.count("#") <= 12  # ≤6 tags roughly
    assert "j18.hk" in text.lower() or "J18.hk" in text


def test_normalize_strips_system_subtitle_for_day():
    writer = DummyWriter()
    data = writer._normalize_result(
        {
            "title": "今晚邊場最有睇頭？",
            "subtitle": "LLM 暫時未能完成，已用推介自動補齊精選",
            "featured": [
                {
                    "race_no": 1,
                    "race_id": "R1",
                    "horse_no": 1,
                    "horse_name": "金光飛馳",
                    "comment": "能量：20% 有睇頭",
                },
                {
                    "race_no": 2,
                    "race_id": "R2",
                    "horse_no": 5,
                    "horse_name": "銀河之星",
                    "comment": "末段走勢唔錯",
                },
                {
                    "race_no": 3,
                    "race_id": "R3",
                    "horse_no": 8,
                    "horse_name": "疾風少年",
                    "comment": "值得留意",
                },
            ],
            "hashtags": ["#賽馬"],
        },
        "",
        tone="高互動型",
        copy_data={
            "meeting": {"racing_date": "2026-09-13", "course": "ST", "session": "日"},
            "races": _sample_copy()["races"],
        },
        source="fallback:timeout",
    )
    assert "今晚" not in data["title"]
    assert ("聽日" in data["title"]) or ("今日" in data["title"]) or ("邊場" in data["title"])
    assert data["subtitle"] == ""
    assert "能量" not in data["featured"][0]["comment"]
    assert any(h in data["hashtags"] for h in ["#J18", "#賽事數據", "#模型分析"]) or "#賽事數據" in data["hashtags"]
    assert len(data["hashtags"]) <= 6
    assert "LLM 暫時未能" not in data["post_text"]
