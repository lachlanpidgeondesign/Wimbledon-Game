"""Explainability: a traceable record for every (player, attribute) rating.

For each rating we capture the formula, the source fields used, the raw metric
values, the percentile/composite, the data tier and the licence status, plus the
grass sample size. Emitted as ratings_explain.json and flattened into review.csv
for the editorial pass.
"""
from __future__ import annotations

import json

import pandas as pd

from .utils import get_logger

log = get_logger("explain")

# Per-attribute provenance spec: formula text, the raw source columns, the
# percentile columns feeding the composite, the composite column, and licence.
#   licence: "clean"      -> facts / CC0 / in-house, commercially usable now
#            "prototype"  -> derived from CC BY-NC-SA data, license/replace pre-launch
SPEC = {
    "serve": {
        "formula": "0.35*pctl(ace%) + 0.30*pctl(1stWon%) + 0.25*pctl(hold%) + 0.10*pctl(2ndWon%) -> [40,98]",
        "sources": ["ace_pct", "first_won_pct", "hold_pct", "second_won_pct"],
        "pcts": ["p_ace", "p_first_won", "p_hold", "p_second_won"],
        "composite": "serve_comp",
        "licence": "prototype",
    },
    "return": {
        "formula": "0.50*pctl(retPtsWon%) + 0.35*pctl(break%) + 0.15*pctl(1stRetWon%) -> [40,98]",
        "sources": ["ret_pts_won_pct", "break_pct", "first_ret_won_pct"],
        "pcts": ["p_ret", "p_break", "p_first_ret"],
        "composite": "return_comp",
        "licence": "prototype",
    },
    "net_volley": {
        "formula": "data: 0.65*pctl(netWin%) + 0.35*pctl(netVolume); else model from quality+serve-aggression -> [40,98]",
        "sources": ["net_win_pct", "net_volume"],
        "pcts": ["p_net_win", "p_net_vol"],
        "composite": "net_comp",
        "licence": "prototype",
    },
    "consistency": {
        "formula": "0.40*pctl(rankGoodness) + 0.35*pctl(grassEloPeak) + 0.25*pctl(grassWin%) -> [40,98]",
        "sources": ["peak_rank", "elo_quality", "grass_win_pct"],
        "pcts": ["p_rank", "p_elo", "p_grass_win"],
        "composite": "consistency_comp",
        "licence": "clean",
    },
    "clutch": {
        "formula": "0.50*pctl(tiebreakWin%) + 0.50*pctl(deciderWin%); model fallback -> [40,98]",
        "sources": ["tiebreak_win_pct", "decider_win_pct", "n_clutch_matches"],
        "pcts": ["p_tiebreak", "p_decider"],
        "composite": "clutch_comp",
        "licence": "clean",
    },
    "stamina": {
        "formula": "0.50*pctl(longMatchWin%) + 0.30*pctl(deepRun) + 0.20*pctl(avgMinutes); model fallback -> [40,98]",
        "sources": ["long_match_win_pct", "best_wim_round", "avg_minutes"],
        "pcts": ["p_long", "p_deep", "p_minutes"],
        "composite": "stamina_comp",
        "licence": "clean",
    },
    "forehand": {
        "formula": "to_rating(quality=peakElo+peakRank) +/- 0.15*aggression +/- 0.15*MCP_FH(win-err) -> [40,98]",
        "sources": ["elo_quality", "peak_rank", "fh_index"],
        "pcts": ["quality_pct", "p_fh_index"],
        "composite": None,
        "licence": "prototype",
    },
    "backhand": {
        "formula": "to_rating(quality) +/- 0.12*returnStrength +/- 0.08*oneHander +/- 0.15*MCP_BH(win-err) -> [40,98]",
        "sources": ["elo_quality", "peak_rank", "is_one_hander", "bh_index"],
        "pcts": ["quality_pct", "p_ret", "p_bh_index"],
        "composite": None,
        "licence": "prototype",
    },
}


def _round(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return round(float(value), 4)


def build_explain(features: pd.DataFrame, detail: pd.DataFrame,
                  ratings: pd.DataFrame) -> pd.DataFrame:
    """Return a long frame: one row per (player, attribute) with full provenance."""
    f = features.set_index("player_id")
    d = detail.set_index("player_id")
    r = ratings.set_index("player_id")
    rows = []

    for pid in r.index:
        name = f.at[pid, "name"]
        tour = f.at[pid, "tour"]
        n_grass = int(f.at[pid, "n_grass_matches"]) if pd.notna(f.at[pid, "n_grass_matches"]) else 0
        for attr, spec in SPEC.items():
            raw = {c: _round(f.at[pid, c]) for c in spec["sources"] if c in f.columns}
            pcts = {c: _round(d.at[pid, c]) for c in spec["pcts"] if c in d.columns}
            comp = _round(d.at[pid, spec["composite"]]) if spec["composite"] else None
            rows.append({
                "player_id": pid,
                "name": name,
                "tour": tour,
                "attribute": attr,
                "rating": int(r.at[pid, attr]) if pd.notna(r.at[pid, attr]) else None,
                "tier": r.at[pid, f"{attr}_tier"],
                "licence": spec["licence"],
                "formula": spec["formula"],
                "source_fields": ", ".join(spec["sources"]),
                "raw": json.dumps(raw),
                "percentiles": json.dumps(pcts),
                "composite": comp,
                "n_grass_matches": n_grass,
            })
    out = pd.DataFrame(rows)
    log.info("explain: %d records (%d players x %d attrs)",
             len(out), len(r), len(SPEC))
    return out
