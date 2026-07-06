"""In-house Elo from match results (overall + grass), per tour.

Elo is computed only from match WINNERS and LOSERS - i.e. facts - so it is
licence-clean and commercially usable. We track each player's current overall
Elo and a separate grass-only Elo, and record the PEAK each reached (the
career/peak basis the ratings use).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import get_logger

log = get_logger("elo")


def _expected(r_a: float, r_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))


def compute_elo(matches: pd.DataFrame, k: float = 24, init: float = 1500,
                grass_surfaces: tuple[str, ...] = ("Grass",)) -> pd.DataFrame:
    """Return per-player Elo summary for one tour's matches.

    Columns: player_id, elo_peak, elo_last, grass_elo_peak, grass_elo_last,
    n_matches, n_grass.
    """
    df = matches.sort_values(["date", "match_num"], na_position="last") \
        if "match_num" in matches.columns else matches.sort_values("date")

    overall: dict[str, float] = {}
    grass: dict[str, float] = {}
    peak: dict[str, float] = {}
    grass_peak: dict[str, float] = {}
    n: dict[str, int] = {}
    n_grass: dict[str, int] = {}

    def get(d: dict, pid: str) -> float:
        return d.get(pid, init)

    for w, l, surf in zip(df["winner_id"].values, df["loser_id"].values,
                          df["surface"].values):
        rw, rl = get(overall, w), get(overall, l)
        ew = _expected(rw, rl)
        overall[w] = rw + k * (1 - ew)
        overall[l] = rl - k * (1 - ew)
        peak[w] = max(get(peak, w), overall[w])
        peak[l] = max(get(peak, l), overall[l])
        n[w] = n.get(w, 0) + 1
        n[l] = n.get(l, 0) + 1

        if surf in grass_surfaces:
            gw, gl = get(grass, w), get(grass, l)
            egw = _expected(gw, gl)
            grass[w] = gw + k * (1 - egw)
            grass[l] = gl - k * (1 - egw)
            grass_peak[w] = max(get(grass_peak, w), grass[w])
            grass_peak[l] = max(get(grass_peak, l), grass[l])
            n_grass[w] = n_grass.get(w, 0) + 1
            n_grass[l] = n_grass.get(l, 0) + 1

    players = sorted(overall.keys())
    out = pd.DataFrame({
        "player_id": players,
        "elo_peak": [peak.get(p, init) for p in players],
        "elo_last": [overall.get(p, init) for p in players],
        "grass_elo_peak": [grass_peak.get(p, np.nan) for p in players],
        "grass_elo_last": [grass.get(p, np.nan) for p in players],
        "n_matches": [n.get(p, 0) for p in players],
        "n_grass": [n_grass.get(p, 0) for p in players],
    })
    log.info("elo: %d players (%d with grass history)",
             len(out), int((out["n_grass"] > 0).sum()))
    return out
