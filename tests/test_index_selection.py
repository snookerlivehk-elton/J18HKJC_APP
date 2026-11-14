"""指数评选排序与入围计数。"""
from index_selection import (
    finish_marks,
    hit_rate,
    implied_shares,
    placed_count,
    strategy_picks,
)
from index_selection_feed import parse_pools


def _horses():
    # 1 大热；2 独赢冷但位置热；3、4 在中间带；8 冷门
    odds = {
        1: (2.2, 1.4),
        2: (18.0, 1.6),
        3: (8.0, 2.8),
        4: (6.5, 2.4),
        5: (12.0, 3.5),
        6: (9.0, 3.0),
        7: (15.0, 4.0),
        8: (40.0, 8.0),
    }
    horses = []
    for no, (win, place) in odds.items():
        horses.append(
            {
                "no": no,
                "scratched": False,
                "win_odds": win,
                "place_odds": place,
                "win_drop": 0,
                "model_share": {1: 0.08, 2: 0.22, 3: 0.16, 4: 0.14, 5: 0.12, 6: 0.11, 7: 0.1, 8: 0.07}[no],
                "fused_share": {1: 0.09, 2: 0.2, 3: 0.18, 4: 0.15, 5: 0.12, 6: 0.1, 7: 0.09, 8: 0.07}[no],
            }
        )
    return horses


def test_place_gap_ranks_place_money_ahead_of_win_favourite():
    picks = strategy_picks("place_gap", _horses())
    assert picks[0] == 2
    assert 1 not in picks[:2]


def test_mid_band_excludes_hot_favourite_and_longshot():
    picks = strategy_picks("mid_band", _horses())
    shares = implied_shares({h["no"]: h["win_odds"] for h in _horses()})
    assert 1 not in picks
    assert 8 not in picks
    assert picks
    assert all(0.08 <= shares[no] <= 0.25 for no in picks)


def test_shorten_uses_previous_odds():
    now = _horses()
    prev = []
    for horse in now:
        before = dict(horse)
        before["win_odds"] = horse["win_odds"] * (1.4 if horse["no"] == 6 else 1.0)
        prev.append(before)
    picks = strategy_picks("shorten", now, prev_horses=prev)
    assert picks[0] == 6


def test_qin_and_fct_and_partner():
    horses = _horses()
    qin = {(1, 4): 8.0, (1, 3): 12.0, (2, 8): 6.0, (4, 5): 30.0}
    fct = {(4, 1): 9.0, (1, 4): 15.0, (2, 1): 40.0}
    qin_picks = strategy_picks("qin_lead", horses, qin_odds=qin)
    assert qin_picks[0] in {2, 8}
    partners = strategy_picks("qin_partner", horses, qin_odds=qin)
    assert 1 not in partners
    assert partners[0] == 4
    fct_picks = strategy_picks("fct_lead", horses, fct_odds=fct)
    assert fct_picks[0] == 4


def test_new_low_only_keeps_horses_still_at_the_low():
    horses = _horses()
    history = {no: [20.0, 12.0] for no in range(1, 9)}
    history[3] = [12.0, 9.0]
    horses[2]["win_odds"] = 7.0
    horses[5]["win_odds"] = 14.0
    picks = strategy_picks("new_low", horses, odds_history=history)
    assert 3 in picks
    assert 6 not in picks


def test_model_and_divergence_use_model_share():
    horses = _horses()
    assert strategy_picks("model", horses)[0] == 2
    diverge = strategy_picks("diverge", horses)
    assert diverge[0] == 2


def test_finish_marks_and_hit_rate():
    picks = [2, 4, 6, 8, 1, 3]
    finishes = {2: 1, 4: 5, 6: 3, 8: 8, 1: 2, 3: 7}
    assert finish_marks(picks, finishes) == [1, None, 3, None, 2, None]
    assert placed_count(picks, finishes) == 3
    assert hit_rate(3, 6) == 0.5


def test_parse_pools_reads_win_place_qin_fct():
    parsed = parse_pools(
        [
            {
                "id": "MTG_20261114_0001WIN1",
                "oddsType": "WIN",
                "sellStatus": "START_SELL",
                "leg": {"races": [1]},
                "oddsNodes": [
                    {"combString": "01", "oddsValue": "3.2", "oddsDropValue": 10},
                    {"combString": "02", "oddsValue": "SCR", "oddsDropValue": 0},
                ],
            },
            {
                "oddsType": "PLA",
                "oddsNodes": [{"combString": "01", "oddsValue": "1.6"}],
            },
            {
                "oddsType": "QIN",
                "oddsNodes": [{"combString": "01,03", "oddsValue": "12"}],
            },
            {
                "oddsType": "FCT",
                "oddsNodes": [{"combString": "03,01", "oddsValue": "20"}],
            },
        ]
    )
    assert parsed["meeting_date"] == "20261114"
    assert parsed["sell_status"] == "START_SELL"
    assert parsed["horses"][0]["win_odds"] == 3.2
    assert parsed["horses"][1]["scratched"] is True
    assert parsed["qin"]["1,3"] == 12.0
    assert parsed["fct"]["3,1"] == 20.0
