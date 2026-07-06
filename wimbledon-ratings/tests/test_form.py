"""Tests for the score parser + clutch/stamina aggregates (facts -> clean)."""
import numpy as np
import pandas as pd

from src import form
from src.utils import load_config


def _cfg():
    return {"sources": load_config("sources")}


def test_parse_sets_basic_and_tiebreak():
    sets, completed = form.parse_sets("7-6(5) 4-6 6-3")
    assert completed is True
    assert sets == [(7, 6, True), (4, 6, False), (6, 3, False)]


def test_parse_sets_marks_retirement_incomplete():
    _sets, completed = form.parse_sets("6-3 2-1 RET")
    assert completed is False


def test_parse_sets_long_final_set_is_not_tiebreak():
    sets, _ = form.parse_sets("6-4 3-6 70-68")   # Isner-Mahut-style marathon
    assert sets[-1] == (70, 68, False)           # 70-68 is not a 7-6 tiebreak


def test_parse_sets_handles_blank():
    assert form.parse_sets("") == ([], False)
    assert form.parse_sets(np.nan) == ([], False)


def _matches():
    """Two grass matches so both a winner and loser accrue clutch/stamina."""
    return pd.DataFrame({
        "winner_id": ["1", "1"],
        "loser_id": ["2", "3"],
        "winner_ioc": ["SUI", "SUI"],
        "loser_ioc": ["ESP", "SRB"],
        "surface": ["Grass", "Grass"],
        "year": [2015, 2016],
        # match 1 goes the full five sets (a real deciding set); match 2 is a
        # straight-sets Bo3 with no tiebreak and no decider.
        "score": ["7-6(5) 6-7(4) 3-6 6-4 6-3", "6-4 7-5"],
        "best_of": [5, 3],
        "minutes": [210, 95],
        "tour": ["atp", "atp"],
    })


def test_clutch_stamina_aggregates_shape_and_values():
    agg = form.clutch_stamina_aggregates(_matches(), _cfg()).set_index("player_id")
    # sample counts
    assert agg.at["1", "n_clutch_matches"] == 2
    assert agg.at["2", "n_clutch_matches"] == 1
    # minutes are a plain mean (not shrunk): (210 + 95) / 2
    assert agg.at["1", "avg_minutes"] == (210 + 95) / 2
    # rates are empirical-Bayes shrunk, so assert robust properties, not exacts:
    # every rate stays within [0, 1] ...
    for col in ("tiebreak_win_pct", "decider_win_pct", "long_match_win_pct"):
        vals = agg[col].dropna()
        assert (vals >= 0).all() and (vals <= 1).all()
    # ... and the player who WON the five-set decider out-scores the one who lost.
    assert agg.at["1", "decider_win_pct"] > agg.at["2", "decider_win_pct"]


def test_shrinkage_regresses_small_samples():
    """A 3-of-3 tiebreak record must not out-rank a high-volume ~60% player."""
    rows = []
    # fluke: 3 grass matches, won all 3 tiebreaks
    for _ in range(3):
        rows.append({"winner_id": "fluke", "loser_id": "x", "surface": "Grass",
                     "year": 2015, "score": "7-6(2) 7-6(3)", "best_of": 3,
                     "minutes": 90, "tour": "atp", "winner_ioc": "USA", "loser_ioc": "X"})
    # grinder: 40 grass matches, won ~60% of two tiebreaks each
    for i in range(40):
        won_both = i % 5 < 3           # 3 of every 5 -> 60%-ish
        s = "7-6(4) 7-6(4)" if won_both else "6-7(4) 6-7(4)"
        wid, lid = ("grind", "x") if won_both else ("x", "grind")
        rows.append({"winner_id": wid, "loser_id": lid, "surface": "Grass",
                     "year": 2015, "score": s, "best_of": 3, "minutes": 90,
                     "tour": "atp", "winner_ioc": "SRB", "loser_ioc": "X"})
    agg = form.clutch_stamina_aggregates(pd.DataFrame(rows), _cfg()).set_index("player_id")
    assert agg.at["grind", "tiebreak_win_pct"] > agg.at["fluke", "tiebreak_win_pct"]


def test_clutch_stamina_skips_non_grass():
    m = _matches()
    m.loc[0, "surface"] = "Hard"
    agg = form.clutch_stamina_aggregates(m, _cfg()).set_index("player_id")
    assert "2" not in agg.index                          # player 2 only had that match
