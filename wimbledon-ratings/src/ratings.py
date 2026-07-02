"""Phase C/D: turn per-player grass metrics + Elo into the six 0-100 ratings.

Each attribute is a weighted blend of percentile-ranked sub-metrics (computed
WITHIN tour) mapped onto the 40-98 envelope. Serve, return and consistency are
grounded in real data. Net/volley is data where Match Charting exists, else a
compressed model fallback. Forehand and backhand have no free per-wing metric,
so they are modelled from a quality index (peak Elo + peak ranking) plus small,
signed, fully-documented nudges - and are always flagged for editorial review.

Returns two frames:
  ratings  - tidy player_id + the six integer ratings + tier flags
  detail   - every intermediate percentile/composite, for explainability
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import normalize as N
from .utils import get_logger

log = get_logger("ratings")

# The six shot ratings, plus the two facts-derived temperament/endurance ratings.
SHOT_ATTRS = ["serve", "return", "forehand", "backhand", "net_volley", "consistency"]
ATTRS = SHOT_ATTRS + ["clutch", "stamina"]

# Grass matches with a parseable score needed before clutch/stamina are trusted
# as data rather than the quality-index fallback (mirrors serve's sample gate).
MIN_CLUTCH_MATCHES = 10

# Optional feature columns the newer ratings need; absent in the lean unit-test
# fixtures and safely defaulted to NaN so those attributes fall back to model.
_OPTIONAL_COLS = [
    "tiebreak_win_pct", "decider_win_pct", "long_match_win_pct",
    "avg_minutes", "n_clutch_matches", "best_wim_round",
]

# Short, game-friendly words for the derived archetype tagline.
_SHOT_WORD = {
    "serve": "Serve", "return": "Return", "forehand": "Forehand",
    "backhand": "Backhand", "net_volley": "Net", "consistency": "Consistency",
}


def _archetype(shot_ratings: dict[str, float]) -> str:
    """A short tagline from the shape of the six shot ratings (game vocabulary)."""
    vals = {k: v for k, v in shot_ratings.items() if pd.notna(v)}
    if not vals:
        return "All-court"
    ordered = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)
    spread = ordered[0][1] - ordered[-1][1]
    if spread < 9:
        return "All-court"
    top, second = ordered[0], ordered[1]
    if top[1] - second[1] >= 8:
        return f"{_SHOT_WORD[top[0]]} specialist"
    return f"{_SHOT_WORD[top[0]]} + {_SHOT_WORD[second[0]]}"


def _signed(pct: pd.Series) -> pd.Series:
    """Percentile in (0,1) -> signed nudge in (-1,1); NaN -> 0 (no shift)."""
    return (pct.fillna(0.5) * 2 - 1)


def _pct(df: pd.DataFrame, col: str, w: dict) -> pd.Series:
    return N.percentile_by_group(df, col, "tour",
                                 w["winsor_low"], w["winsor_high"])


def compute_ratings(features: pd.DataFrame, weights: dict
                    ) -> tuple[pd.DataFrame, pd.DataFrame]:
    f = features.copy()
    for col in _OPTIONAL_COLS:           # tolerate lean fixtures / missing data
        if col not in f.columns:
            f[col] = np.nan
    wn = weights["normalize"]
    floor, ceil = wn["floor"], wn["ceil"]
    span = ceil - floor
    d = pd.DataFrame({"player_id": f["player_id"], "tour": f["tour"]})

    # ---- sub-metric percentiles (within tour) -----------------------------
    d["p_ace"] = _pct(f, "ace_pct", wn)
    d["p_first_won"] = _pct(f, "first_won_pct", wn)
    d["p_hold"] = _pct(f, "hold_pct", wn)
    d["p_second_won"] = _pct(f, "second_won_pct", wn)
    d["p_ret"] = _pct(f, "ret_pts_won_pct", wn)
    d["p_break"] = _pct(f, "break_pct", wn)
    d["p_first_ret"] = _pct(f, "first_ret_won_pct", wn)

    f["rank_goodness"] = -f["peak_rank"]               # lower rank number = better
    f["elo_quality"] = f["grass_elo_peak"].fillna(f["elo_peak"])
    d["p_rank"] = _pct(f, "rank_goodness", wn)
    d["p_elo"] = _pct(f, "elo_quality", wn)
    d["p_grass_win"] = _pct(f, "grass_win_pct", wn)

    # quality index + serve-aggression proxy, reused by several attributes
    quality_pct = (d["p_elo"].fillna(0.5) + d["p_rank"].fillna(0.5)) / 2
    serve_aggr_pct = (d["p_ace"].fillna(0.5) + d["p_first_won"].fillna(0.5)) / 2
    d["quality_pct"] = quality_pct
    sample_ok = f["serve_sample_ok"].fillna(False)

    # ---- SERVE (data; falls back to quality where no serve sample) --------
    w = weights["serve"]
    d["serve_comp"] = N.weighted_percentile(
        {"a": d["p_ace"], "b": d["p_first_won"], "c": d["p_hold"], "e": d["p_second_won"]},
        {"a": w["ace_pct"], "b": w["first_won_pct"], "c": w["hold_pct"], "e": w["second_won_pct"]},
    ).fillna(quality_pct)
    d["serve"] = N.to_rating(d["serve_comp"], floor, ceil)
    d["serve_tier"] = np.where(sample_ok, "data", "model")

    # ---- RETURN (data; same fallback) -------------------------------------
    w = weights["return"]
    d["return_comp"] = N.weighted_percentile(
        {"a": d["p_ret"], "b": d["p_break"], "c": d["p_first_ret"]},
        {"a": w["ret_pts_won_pct"], "b": w["break_pct"], "c": w["first_ret_won_pct"]},
    ).fillna(quality_pct)
    d["return"] = N.to_rating(d["return_comp"], floor, ceil)
    d["return_tier"] = np.where(sample_ok, "data", "model")

    # ---- CONSISTENCY (data, CLEAN: facts + in-house Elo) ------------------
    w = weights["consistency"]
    d["consistency_comp"] = N.weighted_percentile(
        {"a": d["p_rank"], "b": d["p_elo"], "c": d["p_grass_win"]},
        {"a": w["rank_pctile"], "b": w["elo_pctile"], "c": w["grass_win_pct"]},
    ).fillna(quality_pct)
    d["consistency"] = N.to_rating(d["consistency_comp"], floor, ceil)
    d["consistency_tier"] = "data"

    # ---- NET / VOLLEY (data where charted, else model) --------------------
    w = weights["net_volley"]
    has_net = f["net_win_pct"].notna()
    d["p_net_win"] = _pct(f, "net_win_pct", wn)
    d["p_net_vol"] = _pct(f, "net_volume", wn)
    net_data_comp = N.weighted_percentile(
        {"a": d["p_net_win"], "b": d["p_net_vol"]},
        {"a": w["net_win_pct"], "b": w["net_volume"]},
    )
    # Model fallback: net propensity from quality + serve aggression, compressed
    # into the mid-band so we never over-claim a net rating we cannot see.
    net_model_comp = (0.25 + 0.5 * (0.5 * quality_pct + 0.5 * serve_aggr_pct)).clip(0, 1)
    d["net_comp"] = net_data_comp.where(has_net, net_model_comp)
    d["net_volley"] = N.to_rating(d["net_comp"], floor, ceil)
    d["net_volley_tier"] = np.where(has_net, "data", "model")

    # ---- FOREHAND (model) -------------------------------------------------
    w = weights["forehand"]
    base = N.to_rating(quality_pct, floor, ceil)
    d["p_fh_index"] = _pct(f, "fh_index", wn)
    fh_shift = (w["aggression_adj"] * _signed(serve_aggr_pct)
                + w["mcp_fh_adj"] * _signed(d["p_fh_index"])) * span
    d["forehand"] = (base + fh_shift).clip(floor, ceil)
    d["forehand_tier"] = "model"

    # ---- BACKHAND (model) -------------------------------------------------
    w = weights["backhand"]
    d["p_bh_index"] = _pct(f, "bh_index", wn)
    one_hander = f["is_one_hander"].fillna(False).astype(float)
    bh_shift = (w["return_strength_adj"] * _signed(d["p_ret"])
                + w["one_hander_adj"] * (one_hander * 2 - 1)
                + w["mcp_bh_adj"] * _signed(d["p_bh_index"])) * span
    d["backhand"] = (base + bh_shift).clip(floor, ceil)
    d["backhand_tier"] = "model"

    # ---- CLUTCH (data, CLEAN: tiebreak + deciding-set win %, from scores) --
    w = weights["clutch"]
    n_clutch = f["n_clutch_matches"].fillna(0)
    clutch_ok = n_clutch >= MIN_CLUTCH_MATCHES
    has_clutch = f["tiebreak_win_pct"].notna() | f["decider_win_pct"].notna()
    d["p_tiebreak"] = _pct(f, "tiebreak_win_pct", wn)
    d["p_decider"] = _pct(f, "decider_win_pct", wn)
    d["clutch_comp"] = N.weighted_percentile(
        {"a": d["p_tiebreak"], "b": d["p_decider"]},
        {"a": w["tiebreak_win_pct"], "b": w["decider_win_pct"]},
    ).fillna(quality_pct)
    d["clutch"] = N.to_rating(d["clutch_comp"], floor, ceil)
    d["clutch_tier"] = np.where(has_clutch & clutch_ok, "data", "model")

    # ---- STAMINA (data, CLEAN: long-match win% + deep runs + court-time) ---
    w = weights["stamina"]
    d["p_long"] = _pct(f, "long_match_win_pct", wn)
    d["p_deep"] = _pct(f, "best_wim_round", wn)
    d["p_minutes"] = _pct(f, "avg_minutes", wn)      # ATP only; WTA renormalises
    d["stamina_comp"] = N.weighted_percentile(
        {"a": d["p_long"], "b": d["p_deep"], "c": d["p_minutes"]},
        {"a": w["long_match_win_pct"], "b": w["deep_run"], "c": w["avg_minutes"]},
    ).fillna(quality_pct)
    d["stamina"] = N.to_rating(d["stamina_comp"], floor, ceil)
    has_stamina = (f["long_match_win_pct"].notna() | f["best_wim_round"].notna())
    d["stamina_tier"] = np.where(has_stamina & clutch_ok, "data", "model")

    # ---- finalise ---------------------------------------------------------
    ratings = d[["player_id", "tour"]].copy()
    for a in ATTRS:
        ratings[a] = d[a].round().astype("Int64")
        ratings[f"{a}_tier"] = d[f"{a}_tier"]
    # Derived, licence-clean tagline from the shape of the six shot ratings.
    ratings["archetype"] = [
        _archetype({k: row[k] for k in SHOT_ATTRS})
        for _, row in ratings[SHOT_ATTRS].iterrows()
    ]
    log.info("rated %d players across %d attributes", len(ratings), len(ATTRS))
    return ratings, d
