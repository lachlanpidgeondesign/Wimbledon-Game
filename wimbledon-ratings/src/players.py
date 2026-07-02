"""Phase B: choose the top-N-per-tour "most notable of 2006-2025" field.

A composite notability score (peak grass Elo, furthest Wimbledon round, weeks in
the top 10, grass titles) ranks everyone who played a Wimbledon main draw in the
window. The top N per tour (``n_per_tour`` in config/selection.yaml, default 50)
are kept and enriched with the bits ratings need
(name, peak ranking, one-handed-backhand flag).
"""
from __future__ import annotations

import pandas as pd

from . import normalize as N
from .utils import get_logger, normalize_name, project_root, slugify

log = get_logger("players")

_ROUND_DEPTH = {"R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7}
_CHAMPION_DEPTH = 8


def _load_one_handers() -> set[str]:
    path = project_root() / "config" / "backhand_type.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path, comment="#")
    one = df[df["backhand"].str.lower() == "one"]
    return {normalize_name(n) for n in one["name"]}


def _wimbledon_round(matches: pd.DataFrame) -> pd.DataFrame:
    """Furthest Wimbledon round reached per player (champion = 8)."""
    wim = matches[matches["tourney_name"].str.contains("Wimbledon", case=False, na=False)]
    if wim.empty:
        return pd.DataFrame(columns=["player_id", "best_wim_round"])
    depth = wim["round"].map(_ROUND_DEPTH)
    rows = pd.concat([
        pd.DataFrame({"player_id": wim["winner_id"], "d": depth}),
        pd.DataFrame({"player_id": wim["loser_id"], "d": depth}),
    ], ignore_index=True)
    champs = wim.loc[wim["round"] == "F", "winner_id"]
    rows = pd.concat([rows, pd.DataFrame({"player_id": champs, "d": _CHAMPION_DEPTH})],
                     ignore_index=True)
    best = rows.groupby("player_id")["d"].max().reset_index()
    return best.rename(columns={"d": "best_wim_round"})


def _ranking_features(rankings: pd.DataFrame) -> pd.DataFrame:
    if rankings.empty:
        return pd.DataFrame(columns=["player_id", "peak_rank", "weeks_top10"])
    r = rankings.copy()
    r["rank"] = pd.to_numeric(r["rank"], errors="coerce")
    peak = r.groupby("player")["rank"].min().rename("peak_rank")
    weeks = r[r["rank"] <= 10].groupby("player").size().rename("weeks_top10")
    out = pd.concat([peak, weeks], axis=1).reset_index()
    out = out.rename(columns={"player": "player_id"})
    out["weeks_top10"] = out["weeks_top10"].fillna(0)
    return out


def _grass_titles(matches: pd.DataFrame, grass_surfaces) -> pd.DataFrame:
    finals = matches[(matches["surface"].isin(grass_surfaces)) & (matches["round"] == "F")]
    if finals.empty:
        return pd.DataFrame(columns=["player_id", "grass_titles"])
    t = finals.groupby("winner_id").size().rename("grass_titles").reset_index()
    return t.rename(columns={"winner_id": "player_id"})


def _name_map(players: pd.DataFrame, matches: pd.DataFrame) -> dict[str, str]:
    names = dict(zip(players["player_id"].astype(str), players["full_name"]))
    for col_id, col_nm in (("winner_id", "winner_name"), ("loser_id", "loser_name")):
        for pid, nm in zip(matches[col_id].astype(str), matches[col_nm]):
            names.setdefault(pid, nm)
    return {k: v for k, v in names.items() if isinstance(v, str) and v.strip()}


def _country_map(players: pd.DataFrame, matches: pd.DataFrame) -> dict[str, str]:
    """player_id -> IOC country code (facts / CC0-grade bio; commercially clean).

    Prefer the players file's `ioc`, fall back to the country carried on match
    rows so fringe players still get a flag/code for the game token.
    """
    country: dict[str, str] = {}
    if "ioc" in players.columns:
        country.update(dict(zip(players["player_id"].astype(str), players["ioc"])))
    for col_id, col_ioc in (("winner_id", "winner_ioc"), ("loser_id", "loser_ioc")):
        if col_ioc in matches.columns:
            for pid, ioc in zip(matches[col_id].astype(str), matches[col_ioc]):
                country.setdefault(pid, ioc)
    return {k: str(v).strip().upper() for k, v in country.items()
            if isinstance(v, str) and v.strip()}


def select(data, elo_by_tour: dict, cfg: dict) -> pd.DataFrame:
    sel_cfg = cfg["selection"]
    wcfg = sel_cfg["notability"]
    grass_surfaces = cfg["sources"]["grass_surfaces"]
    n_per_tour = sel_cfg["n_per_tour"]
    one_handers = _load_one_handers()

    frames = []
    for tour in ("atp", "wta"):
        matches = data.matches[tour]
        players = data.players[tour]
        names = _name_map(players, matches)
        countries = _country_map(players, matches)

        feats = _wimbledon_round(matches)
        feats = feats.merge(_ranking_features(data.rankings[tour]), on="player_id", how="outer")
        feats = feats.merge(_grass_titles(matches, grass_surfaces), on="player_id", how="left")
        feats = feats.merge(elo_by_tour[tour], on="player_id", how="left")

        if sel_cfg["require_wimbledon_appearance"]:
            feats = feats[feats["best_wim_round"].notna()]
        for col in ("best_wim_round", "weeks_top10", "grass_titles"):
            feats[col] = feats[col].fillna(0)
        feats["tour"] = tour

        # notability = weighted blend of percentile-ranked components
        p_elo = N.percentile_rank(feats["grass_elo_peak"])
        p_round = N.percentile_rank(feats["best_wim_round"])
        p_weeks = N.percentile_rank(feats["weeks_top10"])
        p_titles = N.percentile_rank(feats["grass_titles"])
        feats["notability"] = (
            wcfg["peak_grass_elo"] * p_elo.fillna(0)
            + wcfg["best_wimbledon_round"] * p_round.fillna(0)
            + wcfg["weeks_top10"] * p_weeks.fillna(0)
            + wcfg["grass_titles"] * p_titles.fillna(0)
        )
        feats = feats.sort_values("notability", ascending=False).head(n_per_tour).copy()

        feats["name"] = feats["player_id"].map(names).fillna(feats["player_id"])
        feats["slug"] = feats["name"].map(slugify)
        feats["country"] = feats["player_id"].map(countries).fillna("")
        feats["is_one_hander"] = feats["name"].map(
            lambda n: normalize_name(n) in one_handers)
        # peak_rank may be NaN for fringe players; fill with a weak sentinel.
        feats["peak_rank"] = feats["peak_rank"].fillna(2000)
        frames.append(feats)
        log.info("%s: selected %d players (of %d candidates)",
                 tour, len(feats), len(elo_by_tour[tour]))

    out = pd.concat(frames, ignore_index=True)
    # Guard against duplicate slugs across tours (rare name collisions).
    dupes = out["slug"].duplicated(keep=False)
    if dupes.any():
        out.loc[dupes, "slug"] = out.loc[dupes, "slug"] + "-" + out.loc[dupes, "tour"]
    return out
