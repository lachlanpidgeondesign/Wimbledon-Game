"""Tests for the rating formulas: bounds, tiers, ordering, and data-less fallback."""
import numpy as np
import pandas as pd

from src import ratings
from src.utils import load_config


def _weights():
    # The full weights config, exactly as the pipeline loads it.
    return load_config("weights")


def _features(n=10):
    """Synthetic ATP field: player i has steadily stronger serve, weaker return."""
    i = np.arange(n)
    return pd.DataFrame({
        "player_id": [f"p{j}" for j in i],
        "tour": "atp",
        "name": [f"P{j}" for j in i],
        "peak_rank": (n - i),                       # p(n-1) is world #1-ish
        "grass_elo_peak": 1700 + i * 30,
        "elo_peak": 1700 + i * 30,
        "grass_win_pct": np.linspace(0.4, 0.85, n),
        "ace_pct": np.linspace(0.04, 0.20, n),      # rising serve
        "first_won_pct": np.linspace(0.62, 0.82, n),
        "hold_pct": np.linspace(0.70, 0.95, n),
        "second_won_pct": np.linspace(0.45, 0.60, n),
        "ret_pts_won_pct": np.linspace(0.45, 0.30, n),  # falling return
        "break_pct": np.linspace(0.30, 0.12, n),
        "first_ret_won_pct": np.linspace(0.40, 0.28, n),
        "serve_sample_ok": True,
        "net_win_pct": np.nan,
        "net_volume": np.nan,
        "fh_index": np.nan,
        "bh_index": np.nan,
        "is_one_hander": False,
        "n_grass_matches": 30,
        # facts-derived clutch/stamina inputs (rising with i)
        "tiebreak_win_pct": np.linspace(0.30, 0.75, n),
        "decider_win_pct": np.linspace(0.35, 0.80, n),
        "long_match_win_pct": np.linspace(0.30, 0.85, n),
        "avg_minutes": np.linspace(90, 150, n),
        "best_wim_round": np.linspace(1, 8, n),
        "n_clutch_matches": 25,
    })


def test_all_ratings_in_envelope():
    rate, _ = ratings.compute_ratings(_features(), _weights())
    for a in ratings.ATTRS:
        vals = rate[a].astype("float")
        assert vals.between(40, 98).all()


def test_serve_orders_with_serve_metrics():
    f = _features()
    rate, _ = ratings.compute_ratings(f, _weights())
    # strongest server (last row) should out-rate the weakest server (first row)
    assert rate.iloc[-1]["serve"] > rate.iloc[0]["serve"]


def test_return_orders_opposite_to_serve():
    rate, _ = ratings.compute_ratings(_features(), _weights())
    assert rate.iloc[0]["return"] > rate.iloc[-1]["return"]


def test_tiers_tagged_correctly():
    rate, _ = ratings.compute_ratings(_features(), _weights())
    assert (rate["forehand_tier"] == "model").all()
    assert (rate["backhand_tier"] == "model").all()
    assert (rate["consistency_tier"] == "data").all()
    assert (rate["net_volley_tier"] == "model").all()   # no charting data supplied
    assert (rate["serve_tier"] == "data").all()


def test_dataless_player_still_rated_via_fallback():
    f = _features()
    # wipe serve/return data for one player + mark sample not ok
    for col in ["ace_pct", "first_won_pct", "hold_pct", "second_won_pct",
                "ret_pts_won_pct", "break_pct", "first_ret_won_pct"]:
        f.loc[0, col] = np.nan
    f.loc[0, "serve_sample_ok"] = False
    rate, _ = ratings.compute_ratings(f, _weights())
    row = rate.iloc[0]
    assert pd.notna(row["serve"]) and pd.notna(row["return"])
    assert row["serve_tier"] == "model"                 # fell back to quality index


def test_clutch_and_stamina_in_envelope_and_ordered():
    rate, _ = ratings.compute_ratings(_features(), _weights())
    for a in ("clutch", "stamina"):
        assert rate[a].astype("float").between(40, 98).all()
    # strongest clutch/stamina inputs (last row) should out-rate the weakest
    assert rate.iloc[-1]["clutch"] > rate.iloc[0]["clutch"]
    assert rate.iloc[-1]["stamina"] > rate.iloc[0]["stamina"]
    assert (rate["clutch_tier"] == "data").all()
    assert (rate["stamina_tier"] == "data").all()


def test_clutch_falls_back_when_no_score_data():
    f = _features().drop(columns=[
        "tiebreak_win_pct", "decider_win_pct", "long_match_win_pct",
        "avg_minutes", "n_clutch_matches", "best_wim_round"])
    rate, _ = ratings.compute_ratings(f, _weights())
    assert rate["clutch"].astype("float").between(40, 98).all()
    assert rate["stamina"].astype("float").between(40, 98).all()
    assert (rate["clutch_tier"] == "model").all()       # no facts -> model fallback


def test_archetype_is_nonempty_string():
    rate, _ = ratings.compute_ratings(_features(), _weights())
    assert rate["archetype"].map(lambda s: isinstance(s, str) and len(s) > 0).all()
