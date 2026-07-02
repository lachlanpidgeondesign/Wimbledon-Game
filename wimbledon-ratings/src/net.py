"""Match Charting Project enrichment: net-point and forehand/backhand signals.

This is best-effort. The Match Charting Project covers a few thousand notable
matches (skewed to top players), so only some of our field will have it. Players
without charting data simply fall back to the model tier for net/FH/BH, and are
auto-flagged for editorial review. Nothing here is required for serve, return,
consistency or Elo.

LICENCE: Match Charting Project is CC BY-NC-SA 4.0 (non-commercial) -> the net
and FH/BH adjustments derived here are prototype-only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import get_logger, normalize_name

log = get_logger("net")

_EMPTY = pd.DataFrame(columns=[
    "player_id", "net_win_pct", "net_volume", "fh_index", "bh_index", "n_charted",
])


def _summary_rows(df: pd.DataFrame, col: str, value: str) -> pd.DataFrame:
    """Keep only the per-match summary rows.

    MCP stats files carry several rows per match. The Overview file's aggregate
    is `set == 'Total'`; the NetPoints file's aggregate is `row == 'NetPoints'`
    (alongside 'Approach' / 'NetPointsRallies' breakdowns we don't want).
    """
    if df.empty or col not in df.columns:
        return df.copy() if not df.empty else df
    return df[df[col].astype(str).str.lower() == value.lower()].copy()


def _resolve_names(stats: pd.DataFrame, matches: pd.DataFrame) -> pd.Series:
    """Return a player-name Series for each stats row.

    Handles both MCP conventions: a 'player' column holding a name, or holding
    '1'/'2' that indexes the matches file's two players.
    """
    player = stats["player"].astype(str)
    looks_indexed = player.isin(["1", "2"]).mean() > 0.5
    if not looks_indexed:
        return player
    if matches.empty or "match_id" not in matches.columns:
        return pd.Series(np.nan, index=stats.index)
    p1 = matches.set_index("match_id").get("Player 1")
    p2 = matches.set_index("match_id").get("Player 2")
    mid = stats["match_id"]
    return pd.Series(
        np.where(player.values == "1", mid.map(p1).values, mid.map(p2).values),
        index=stats.index,
    )


def _name_to_id(names: pd.Series, players: dict[str, pd.DataFrame]) -> pd.Series:
    """Map free-text player names to our internal player_id via normalised name."""
    lookup: dict[str, str] = {}
    for tour_df in players.values():
        for pid, full in zip(tour_df["player_id"], tour_df["full_name"]):
            lookup.setdefault(normalize_name(full), str(pid))
    return names.map(lambda n: lookup.get(normalize_name(n)))


def net_and_wing_signals(mcp_overview: pd.DataFrame, mcp_net: pd.DataFrame,
                         mcp_matches: pd.DataFrame,
                         players: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per-player net win%/volume and forehand/backhand winner-minus-error index."""
    if mcp_overview.empty and mcp_net.empty:
        log.info("no Match Charting data present - net/FH/BH fall back to model")
        return _EMPTY.copy()

    frames = []

    # ---- net points -------------------------------------------------------
    net = _summary_rows(mcp_net, "row", "NetPoints")
    if not net.empty and {"net_pts", "pts_won"}.issubset(net.columns):
        net = net.assign(player_id=_name_to_id(_resolve_names(net, mcp_matches), players))
        net = net.dropna(subset=["player_id"])
        net["net_pts"] = pd.to_numeric(net["net_pts"], errors="coerce")
        net["pts_won"] = pd.to_numeric(net["pts_won"], errors="coerce")
        ng = net.groupby("player_id").agg(
            net_pts=("net_pts", "sum"),
            net_pts_won=("pts_won", "sum"),
            n_charted=("net_pts", "size"),
        )
        ng["net_win_pct"] = (ng["net_pts_won"] / ng["net_pts"]).clip(0, 1)
        ng["net_volume"] = ng["net_pts"] / ng["n_charted"]
        frames.append(ng[["net_win_pct", "net_volume", "n_charted"]])

    # ---- forehand / backhand winner-minus-error index ---------------------
    ov = _summary_rows(mcp_overview, "set", "Total")
    wing_cols = {"winners_fh", "winners_bh", "unforced_fh", "unforced_bh"}
    if not ov.empty and wing_cols.issubset(ov.columns):
        ov = ov.assign(player_id=_name_to_id(_resolve_names(ov, mcp_matches), players))
        ov = ov.dropna(subset=["player_id"])
        for c in wing_cols:
            ov[c] = pd.to_numeric(ov[c], errors="coerce")
        og = ov.groupby("player_id").agg(
            winners_fh=("winners_fh", "sum"), unforced_fh=("unforced_fh", "sum"),
            winners_bh=("winners_bh", "sum"), unforced_bh=("unforced_bh", "sum"),
        )
        og["fh_index"] = og["winners_fh"] - og["unforced_fh"]
        og["bh_index"] = og["winners_bh"] - og["unforced_bh"]
        frames.append(og[["fh_index", "bh_index"]])

    if not frames:
        return _EMPTY.copy()

    out = pd.concat(frames, axis=1).reset_index()
    for col in ("net_win_pct", "net_volume", "fh_index", "bh_index", "n_charted"):
        if col not in out.columns:
            out[col] = np.nan
    log.info("charting signals for %d players", len(out))
    return out
