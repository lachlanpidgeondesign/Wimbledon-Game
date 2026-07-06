"""Clutch + stamina aggregates, parsed from match scores (facts -> CLEAN).

Everything here is derived from match *results and scorelines* - who won, how
many sets, which sets were tiebreaks, how long the match ran. Scorelines and
results are facts (not copyrightable), so unlike the serve/return detail these
two dimensions are commercially clean.

Two per-player grass aggregates come out of this module:

  clutch  <- tiebreak win %  +  deciding-set win %
  stamina <- long-match win %  +  (deep runs, added later)  +  mean court-time

`deep_run` (furthest Wimbledon round) is already computed during selection, so
it is blended in over in ratings.py; here we produce the score-derived parts.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .utils import get_logger

log = get_logger("form")

# Empirical-Bayes shrinkage pseudo-counts: how many "average" matches of evidence
# a player must accrue before their observed rate outweighs the population prior.
# Deciders / long matches are rarer than tiebreaks, so they shrink a touch harder.
_K_TIEBREAK = 12
_K_DECIDER = 8
_K_LONG = 8

# A single set token: "6-4", "7-6(5)", "6-7(10)". The optional (n) is the
# loser's tiebreak points and only appears on 7-6 / 6-7 sets.
_SET_RE = re.compile(r"^(\d+)-(\d+)(?:\((\d+)\))?$")
# Tokens that mean the match did not finish normally -> exclude from rates.
_INCOMPLETE = re.compile(r"ret|w/?o|def|abn|walk|unfinished|\bunk\b", re.IGNORECASE)


def parse_sets(score: str) -> tuple[list[tuple[int, int, bool]], bool]:
    """Parse a Sackmann scoreline from the MATCH WINNER's perspective.

    Returns ``(sets, completed)`` where each set is
    ``(winner_games, loser_games, is_tiebreak)`` and ``completed`` is False for
    retirements / walkovers / defaults.
    """
    if not isinstance(score, str) or not score.strip():
        return [], False
    completed = not bool(_INCOMPLETE.search(score))
    sets: list[tuple[int, int, bool]] = []
    for tok in score.split():
        m = _SET_RE.match(tok)
        if not m:
            continue  # skip stray tokens ("RET", "[10-7]", etc.)
        a, b = int(m.group(1)), int(m.group(2))
        is_tb = {min(a, b), max(a, b)} == {6, 7}
        sets.append((a, b, is_tb))
    return sets, completed


def _player_match_rows(matches: pd.DataFrame) -> pd.DataFrame:
    """One row per (player, match): won flag + score + format + court-time."""
    minutes = matches["minutes"] if "minutes" in matches.columns else np.nan
    common = {
        "score": matches["score"],
        "best_of": pd.to_numeric(matches["best_of"], errors="coerce"),
        "minutes": pd.to_numeric(minutes, errors="coerce"),
        "tour": matches["tour"],
    }
    win = pd.DataFrame({"player_id": matches["winner_id"].astype(str), "won": True, **common})
    los = pd.DataFrame({"player_id": matches["loser_id"].astype(str), "won": False, **common})
    return pd.concat([win, los], ignore_index=True)


def _row_signals(won: bool, score: str, best_of: float) -> dict | None:
    """Per-(player, match) clutch/stamina counters, or None if unusable."""
    sets, completed = parse_sets(score)
    if not completed or not sets or pd.isna(best_of):
        return None
    best_of = int(best_of)
    n_sets = len(sets)

    tb_played = tb_won = 0
    for a, b, is_tb in sets:
        if not is_tb:
            continue
        tb_played += 1
        my, opp = (a, b) if won else (b, a)   # orient to this player
        tb_won += int(my > opp)

    went_distance = (best_of == 5 and n_sets == 5) or (best_of == 3 and n_sets == 3)
    is_long = (best_of == 5 and n_sets >= 4) or (best_of == 3 and n_sets == 3)
    return {
        "tb_played": tb_played,
        "tb_won": tb_won,
        "decider_played": int(went_distance),
        "decider_won": int(went_distance and won),
        "long_played": int(is_long),
        "long_won": int(is_long and won),
    }


def clutch_stamina_aggregates(matches: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Per-player grass clutch/stamina raw metrics (keyed by Sackmann id)."""
    grass_surfaces = cfg["sources"]["grass_surfaces"]
    y0, y1 = cfg["sources"]["year_start"], cfg["sources"]["year_end"]
    g = matches[
        matches["surface"].isin(grass_surfaces) & matches["year"].between(y0, y1)
    ]
    long = _player_match_rows(g)

    records: dict[str, dict] = {}
    for row in long.itertuples(index=False):
        sig = _row_signals(row.won, row.score, row.best_of)
        if sig is None:
            continue
        acc = records.setdefault(row.player_id, {
            "tour": row.tour, "n_clutch_matches": 0, "minutes_sum": 0.0, "minutes_n": 0,
            "tb_played": 0, "tb_won": 0, "decider_played": 0, "decider_won": 0,
            "long_played": 0, "long_won": 0,
        })
        acc["n_clutch_matches"] += 1
        for k, v in sig.items():
            acc[k] += v
        if not pd.isna(row.minutes):
            acc["minutes_sum"] += float(row.minutes)
            acc["minutes_n"] += 1

    if not records:
        return pd.DataFrame(columns=[
            "player_id", "tour", "n_clutch_matches",
            "tiebreak_win_pct", "decider_win_pct", "long_match_win_pct", "avg_minutes",
        ])

    # Rate stats on small denominators are wildly noisy (a player who won 3 of 3
    # grass tiebreaks is not "better than Djokovic"). Shrink every rate toward the
    # pooled mean via empirical-Bayes: adj = (won + k*prior) / (played + k). High-
    # volume players keep their true rate; low-volume flukes regress to the mean.
    def _prior(win_key: str, played_key: str) -> float:
        w = sum(a[win_key] for a in records.values())
        p = sum(a[played_key] for a in records.values())
        return w / p if p else 0.5

    tb_prior = _prior("tb_won", "tb_played")
    dec_prior = _prior("decider_won", "decider_played")
    long_prior = _prior("long_won", "long_played")

    def _shrink(won: float, played: int, k: float, prior: float) -> float:
        return (won + k * prior) / (played + k) if played else np.nan

    rows = []
    for pid, a in records.items():
        rows.append({
            "player_id": pid,
            "tour": a["tour"],
            "n_clutch_matches": a["n_clutch_matches"],
            "tiebreak_win_pct": _shrink(a["tb_won"], a["tb_played"], _K_TIEBREAK, tb_prior),
            "decider_win_pct": _shrink(a["decider_won"], a["decider_played"], _K_DECIDER, dec_prior),
            "long_match_win_pct": _shrink(a["long_won"], a["long_played"], _K_LONG, long_prior),
            "avg_minutes": a["minutes_sum"] / a["minutes_n"] if a["minutes_n"] else np.nan,
        })
    out = pd.DataFrame(rows)
    log.info("clutch/stamina: %d players (%d with tiebreak sample)",
             len(out), int((out["tiebreak_win_pct"].notna()).sum()))
    return out
