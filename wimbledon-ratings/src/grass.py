"""Career-grass serve / return / win% aggregates per player.

We reshape matches into a "player-match" long table (one row per player per
match, with their own serve line and their opponent's serve line) then sum over
all grass matches in the window. Rate metrics are derived from those sums.

All metrics here are derived from Sackmann serve columns -> NON-COMMERCIAL,
flagged prototype-only in the licence map. (Win% alone is a fact and clean, but
it is bundled here for convenience.)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import get_logger

log = get_logger("grass")

# Map the raw Sackmann serve-column suffixes (some start with a digit) to safe
# snake_case names we use everywhere downstream.
_STAT_MAP = {
    "ace": "ace", "df": "df", "svpt": "svpt",
    "1stIn": "first_in", "1stWon": "first_won", "2ndWon": "second_won",
    "SvGms": "sv_gms", "bpSaved": "bp_saved", "bpFaced": "bp_faced",
}
_STATS = list(_STAT_MAP.values())


def build_player_match_long(matches: pd.DataFrame) -> pd.DataFrame:
    """One row per (player, match): own serve stats + opponent serve stats."""
    def side(win: bool) -> pd.DataFrame:
        me, opp = ("w", "l") if win else ("l", "w")
        me_id, opp_id = ("winner", "loser") if win else ("loser", "winner")
        cols = {
            "player_id": matches[f"{me_id}_id"].astype(str),
            "tour": matches["tour"],
            "date": matches["date"],
            "year": matches["year"],
            "surface": matches["surface"],
            "round": matches["round"],
            "tourney_name": matches["tourney_name"],
            "won": win,
        }
        for raw, safe in _STAT_MAP.items():
            cols[safe] = matches[f"{me}_{raw}"]
            cols[f"opp_{safe}"] = matches[f"{opp}_{raw}"]
        return pd.DataFrame(cols)

    long = pd.concat([side(True), side(False)], ignore_index=True)
    return long


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    den = den.replace(0, np.nan)
    return num / den


def grass_aggregates(long: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Per-player career-grass serve/return rate metrics + sample sizes."""
    grass_surfaces = cfg["sources"]["grass_surfaces"]
    y0, y1 = cfg["sources"]["year_start"], cfg["sources"]["year_end"]
    g = long[
        long["surface"].isin(grass_surfaces)
        & long["year"].between(y0, y1)
    ].copy()

    sum_cols = _STATS + [f"opp_{s}" for s in _STATS]
    agg = g.groupby("player_id").agg(
        tour=("tour", "first"),
        n_grass_matches=("won", "size"),
        grass_wins=("won", "sum"),
        **{c: (c, lambda s: s.sum(min_count=1)) for c in sum_cols},
    ).reset_index()

    # ---- serve metrics (player's own serve) -------------------------------
    agg["ace_pct"] = _safe_div(agg["ace"], agg["svpt"])
    agg["first_in_pct"] = _safe_div(agg["first_in"], agg["svpt"])
    agg["first_won_pct"] = _safe_div(agg["first_won"], agg["first_in"])
    second_pts = agg["svpt"] - agg["first_in"]
    agg["second_won_pct"] = _safe_div(agg["second_won"], second_pts)
    breaks_against = (agg["bp_faced"] - agg["bp_saved"]).clip(lower=0)
    agg["hold_pct"] = (1 - _safe_div(breaks_against, agg["sv_gms"])).clip(0, 1)

    # ---- return metrics (from opponent's serve line) ----------------------
    opp_pts_won = agg["opp_first_won"] + agg["opp_second_won"]
    agg["ret_pts_won_pct"] = (1 - _safe_div(opp_pts_won, agg["opp_svpt"])).clip(0, 1)
    breaks_for = (agg["opp_bp_faced"] - agg["opp_bp_saved"]).clip(lower=0)
    agg["break_pct"] = _safe_div(breaks_for, agg["opp_sv_gms"]).clip(0, 1)
    agg["first_ret_won_pct"] = _safe_div(
        agg["opp_first_in"] - agg["opp_first_won"], agg["opp_first_in"]
    ).clip(0, 1)

    # ---- overall ----------------------------------------------------------
    agg["grass_win_pct"] = _safe_div(agg["grass_wins"], agg["n_grass_matches"])

    # Flag thin serve samples so ratings/editorial know to distrust them.
    min_pts = cfg["sources"]["min_serve_points"]
    agg["serve_sample_ok"] = agg["svpt"] >= min_pts

    keep = [
        "player_id", "tour", "n_grass_matches", "grass_wins", "grass_win_pct",
        "svpt", "serve_sample_ok",
        "ace_pct", "first_in_pct", "first_won_pct", "second_won_pct", "hold_pct",
        "ret_pts_won_pct", "break_pct", "first_ret_won_pct",
    ]
    out = agg[keep].copy()
    log.info("grass aggregates: %d players (%d with usable serve sample)",
             len(out), int(out["serve_sample_ok"].sum()))
    return out
