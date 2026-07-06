"""Phase A (load + validate): read cached CSVs into tidy DataFrames.

Produces a single `Data` container the rest of the pipeline consumes. Match
files are concatenated across seasons and tagged with `tour`. Missing optional
files (e.g. Match Charting) yield empty frames so downstream code degrades
gracefully rather than crashing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .utils import clean_id, get_logger, project_root, tour_source

log = get_logger("ingest")

# Columns we rely on; validated so failures are loud and early.
_MATCH_REQUIRED = [
    "tourney_name", "surface", "tourney_date", "round", "best_of",
    "winner_id", "winner_name", "loser_id", "loser_name",
]
_SERVE_COLS = [
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon",
    "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon",
    "l_SvGms", "l_bpSaved", "l_bpFaced",
]


@dataclass
class Data:
    """All ingested raw data, keyed for convenience."""
    players: dict[str, pd.DataFrame] = field(default_factory=dict)   # tour -> players
    rankings: dict[str, pd.DataFrame] = field(default_factory=dict)  # tour -> rankings
    matches: dict[str, pd.DataFrame] = field(default_factory=dict)   # tour -> matches
    mcp_overview: pd.DataFrame = field(default_factory=pd.DataFrame)
    mcp_net: pd.DataFrame = field(default_factory=pd.DataFrame)
    mcp_matches: pd.DataFrame = field(default_factory=pd.DataFrame)


def _read(cache: Path, name: str, **kw) -> pd.DataFrame:
    path = cache / name
    if not path.exists():
        return pd.DataFrame()
    # Sackmann players/matches CSVs are Latin-1 (accented names); MCP files are
    # UTF-8. Try UTF-8 first, fall back to Latin-1 so both load cleanly.
    try:
        return pd.read_csv(path, low_memory=False, **kw)
    except UnicodeDecodeError:
        return pd.read_csv(path, low_memory=False, encoding="latin-1", **kw)


# Older Sackmann mirrors ship these files WITHOUT a header row, in this column
# order. Newer copies include a header (and extra trailing columns); we sniff the
# first line and handle both.
_PLAYER_COLS = ["player_id", "name_first", "name_last", "hand", "dob", "ioc"]
_RANKING_COLS = ["ranking_date", "rank", "player", "points"]


def _has_header(path: Path, first_token: str) -> bool:
    try:
        with open(path, encoding="latin-1") as fh:
            return fh.readline().lstrip().lower().startswith(first_token)
    except OSError:
        return False


def _load_players(cache: Path, tour: str) -> pd.DataFrame:
    name = f"{tour}_players.csv"
    path = cache / name
    if not path.exists():
        raise FileNotFoundError(f"{name} missing - run fetch first")
    if _has_header(path, "player_id"):
        df = _read(cache, name)
    else:
        df = _read(cache, name, header=None)
        df = df.iloc[:, :len(_PLAYER_COLS)]
        df.columns = _PLAYER_COLS
    df["player_id"] = clean_id(df["player_id"])
    first = df.get("name_first", "").fillna("").astype(str)
    last = df.get("name_last", "").fillna("").astype(str)
    df["full_name"] = (first + " " + last).str.strip()
    df["tour"] = tour
    return df


def _load_rankings(cache: Path, tour: str) -> pd.DataFrame:
    frames = []
    for decade in ("00s", "10s", "20s", "current"):
        name = f"{tour}_rankings_{decade}.csv"
        path = cache / name
        if not path.exists():
            continue
        if _has_header(path, "ranking_date"):
            d = _read(cache, name)
        else:
            d = _read(cache, name, header=None)
            d = d.iloc[:, :len(_RANKING_COLS)]
            d.columns = _RANKING_COLS
        if not d.empty:
            frames.append(d)
    if not frames:
        return pd.DataFrame(columns=_RANKING_COLS + ["tour"])
    df = pd.concat(frames, ignore_index=True)
    df["player"] = clean_id(df["player"])
    df["tour"] = tour
    return df


def _load_matches(cache: Path, tour: str, y0: int, y1: int) -> pd.DataFrame:
    frames = []
    for year in range(y0, y1 + 1):
        d = _read(cache, f"{tour}_matches_{year}.csv")
        if not d.empty:
            frames.append(d)
    if not frames:
        raise FileNotFoundError(f"no {tour} match files {y0}-{y1} - run fetch first")
    df = pd.concat(frames, ignore_index=True)

    missing = [c for c in _MATCH_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{tour} matches missing required columns: {missing}")

    df["winner_id"] = clean_id(df["winner_id"])
    df["loser_id"] = clean_id(df["loser_id"])
    df["tour"] = tour
    # Parse YYYYMMDD integer dates; keep a usable year for windowing.
    df["date"] = pd.to_datetime(df["tourney_date"], format="%Y%m%d", errors="coerce")
    df["year"] = df["date"].dt.year
    for col in _SERVE_COLS:  # ensure numeric; absent in some old WTA seasons
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    return df


def load(cache: Path, cfg: dict) -> Data:
    """Load every cached file into a `Data` container."""
    data = Data()
    for tour in ("atp", "wta"):
        ts = tour_source(cfg, tour)
        data.players[tour] = _load_players(cache, tour)
        data.rankings[tour] = _load_rankings(cache, tour)
        data.matches[tour] = _load_matches(cache, tour, ts["year_start"], ts["year_end"])
        log.info("%s: %d players, %d ranking rows, %d matches",
                 tour, len(data.players[tour]), len(data.rankings[tour]),
                 len(data.matches[tour]))

    # Match Charting Project (optional enrichment for net + FH/BH).
    data.mcp_overview = pd.concat(
        [_read(cache, f"charting-{g}-stats-Overview.csv") for g in ("m", "w")],
        ignore_index=True,
    )
    data.mcp_net = pd.concat(
        [_read(cache, f"charting-{g}-stats-NetPoints.csv") for g in ("m", "w")],
        ignore_index=True,
    )
    data.mcp_matches = pd.concat(
        [_read(cache, f"charting-{g}-matches.csv") for g in ("m", "w")],
        ignore_index=True,
    )
    log.info("MCP: %d overview rows, %d net rows, %d charted matches",
             len(data.mcp_overview), len(data.mcp_net), len(data.mcp_matches))
    return data


def load_default(cfg: dict) -> Data:
    """Convenience: load from the configured cache directory."""
    cache = project_root() / cfg["sources"]["cache_dir"]
    return load(cache, cfg)
