"""賽績評價對外文字：不漏內部術語，長度與賽前文案對齊。"""
import os

from form_ai_analyst import fit_public_summary, http_deadline_sec, summary_leaks_internal


def test_summary_rejects_model_jargon():
    assert summary_leaks_internal("模型勝率 18%，近績領放。")
    assert summary_leaks_internal("AI 份額偏高，步速快。")
    assert not summary_leaks_internal("上仗同程領放，末段仍留有餘速。")


def test_fit_public_summary_stops_on_punctuation():
    raw = "出閘後沿欄搶前，上仗一千四百米直路仍能留在前列。" + "這句是多餘的補充，不應該整段硬切在字中間讓人讀不完。"
    out = fit_public_summary(raw, limit=50)
    assert len(out) <= 50
    assert out.endswith("。")


def test_http_deadline_stays_in_bounds():
    old = os.environ.get("FORM_AI_HTTP_DEADLINE_SEC")
    try:
        os.environ["FORM_AI_HTTP_DEADLINE_SEC"] = "5"
        assert http_deadline_sec() == 20.0
        os.environ["FORM_AI_HTTP_DEADLINE_SEC"] = "999"
        assert http_deadline_sec() == 180.0
    finally:
        if old is None:
            os.environ.pop("FORM_AI_HTTP_DEADLINE_SEC", None)
        else:
            os.environ["FORM_AI_HTTP_DEADLINE_SEC"] = old
