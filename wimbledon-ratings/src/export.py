"""Phase D (Load): write the JSON ratings + explainability + editorial artefacts.

Outputs (under data/processed/):
  players.json         - the deliverable, in the brief's schema
  ratings_explain.json - full provenance per (player, attribute)
  review.csv           - flat, flag-sorted worksheet for the editorial pass
  licence_map.csv      - which fields are clean vs prototype-only (pre-launch TODO)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .ratings import ATTRS
from .utils import get_logger, project_root

log = get_logger("export")

# Methodology-level licence map: clean (usable now) vs prototype (license/replace).
_LICENCE_MAP = [
    {"attribute": "serve", "licence_status": "prototype",
     "nc_source_fields": "ace, svpt, 1stIn, 1stWon, 2ndWon, SvGms, bpSaved, bpFaced (Sackmann)",
     "clean_source_fields": "-",
     "commercial_action": "License Sackmann data, or replace with official/Opta serve stats"},
    {"attribute": "return", "licence_status": "prototype",
     "nc_source_fields": "opponent serve columns (Sackmann)",
     "clean_source_fields": "-",
     "commercial_action": "License Sackmann data, or replace with official/Opta return stats"},
    {"attribute": "net_volley", "licence_status": "prototype",
     "nc_source_fields": "Match Charting net points; serve-aggression fallback (Sackmann)",
     "clean_source_fields": "in-house Elo base (model fallback only)",
     "commercial_action": "License Match Charting/Opta net data, or keep as editorial estimate"},
    {"attribute": "consistency", "licence_status": "clean",
     "nc_source_fields": "-",
     "clean_source_fields": "rankings (facts), in-house grass Elo, grass win% (facts)",
     "commercial_action": "None - usable commercially as-is"},
    {"attribute": "forehand", "licence_status": "prototype",
     "nc_source_fields": "serve-aggression + Match Charting FH winners/errors",
     "clean_source_fields": "in-house Elo + peak ranking (quality base)",
     "commercial_action": "Replace NC adjustments with licensed shot data or editorial sign-off"},
    {"attribute": "backhand", "licence_status": "prototype",
     "nc_source_fields": "return-strength (serve-derived) + Match Charting BH winners/errors",
     "clean_source_fields": "in-house Elo + peak ranking + one-hander config",
     "commercial_action": "Replace NC adjustments with licensed shot data or editorial sign-off"},
    {"attribute": "clutch", "licence_status": "clean",
     "nc_source_fields": "-",
     "clean_source_fields": "tiebreak & deciding-set win% parsed from match scores (facts)",
     "commercial_action": "None - usable commercially as-is"},
    {"attribute": "stamina", "licence_status": "clean",
     "nc_source_fields": "-",
     "clean_source_fields": "long-match win%, furthest Wimbledon round, mean court-time (facts)",
     "commercial_action": "None - usable commercially as-is"},
    {"attribute": "country", "licence_status": "clean",
     "nc_source_fields": "-",
     "clean_source_fields": "IOC country code (bio fact)",
     "commercial_action": "None - usable commercially as-is"},
    {"attribute": "archetype", "licence_status": "clean",
     "nc_source_fields": "-",
     "clean_source_fields": "derived tagline from the shape of the six ratings",
     "commercial_action": "None - usable commercially as-is"},
]


def _processed_dir(cfg: dict) -> Path:
    out = project_root() / cfg["sources"]["processed_dir"]
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_players_json(ratings: pd.DataFrame, features: pd.DataFrame,
                       cfg: dict) -> Path:
    """Emit players.json (brief schema + the game's extra clean dimensions)."""
    meta = features.set_index("player_id")[["name", "peak_rank", "country"]]
    df = ratings.set_index("player_id").join(meta)
    records = []
    for pid, row in df.iterrows():
        records.append({
            "player_id": pid,
            "name": row["name"],
            "tour": row["tour"],
            "country": row["country"] if pd.notna(row["country"]) else "",
            "ranking": int(row["peak_rank"]) if pd.notna(row["peak_rank"]) else None,
            "serve": int(row["serve"]),
            "return": int(row["return"]),
            "forehand": int(row["forehand"]),
            "backhand": int(row["backhand"]),
            "net_volley": int(row["net_volley"]),
            "consistency": int(row["consistency"]),
            "clutch": int(row["clutch"]),
            "stamina": int(row["stamina"]),
            "archetype": row["archetype"],
        })
    records.sort(key=lambda r: (r["tour"], r["name"]))
    path = _processed_dir(cfg) / "players.json"
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("wrote %s (%d players)", path.name, len(records))
    return path


def write_game_roster(ratings: pd.DataFrame, features: pd.DataFrame,
                      cfg: dict) -> Path:
    """Emit game_roster.json in build-a-champion's ROSTER shape.

    Renames the pipeline's schema onto the game's compact keys so the HTML can
    inline it directly: {n, a, serve, ret, fh, bh, net, con, clutch, stam, country}.
    """
    meta = features.set_index("player_id")[["name", "country"]]
    df = ratings.set_index("player_id").join(meta)
    records = []
    for _pid, row in df.iterrows():
        records.append({
            "n": row["name"],
            "a": row["archetype"],
            "country": row["country"] if pd.notna(row["country"]) else "",
            "tour": row["tour"],
            "serve": int(row["serve"]),
            "ret": int(row["return"]),
            "fh": int(row["forehand"]),
            "bh": int(row["backhand"]),
            "net": int(row["net_volley"]),
            "con": int(row["consistency"]),
            "clutch": int(row["clutch"]),
            "stam": int(row["stamina"]),
        })
    records.sort(key=lambda r: (r["tour"], r["n"]))
    path = _processed_dir(cfg) / "game_roster.json"
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("wrote %s (%d players, game schema)", path.name, len(records))
    return path


def write_explain_json(explain: pd.DataFrame, cfg: dict) -> Path:
    path = _processed_dir(cfg) / "ratings_explain.json"
    records = json.loads(explain.to_json(orient="records"))
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("wrote %s (%d records)", path.name, len(records))
    return path


def write_review_csv(explain: pd.DataFrame, cfg: dict) -> Path:
    cols = [
        "needs_review", "tour", "attribute", "name", "player_id", "rating",
        "tier", "licence", "flag_modelled", "flag_low_sample", "flag_outlier",
        "n_grass_matches", "overridden", "reviewer", "note",
        "formula", "source_fields", "raw", "percentiles", "composite",
    ]
    cols = [c for c in cols if c in explain.columns]
    review = explain[cols].sort_values(
        ["needs_review", "tour", "attribute", "rating"],
        ascending=[False, True, True, False],
    )
    path = _processed_dir(cfg) / "review.csv"
    review.to_csv(path, index=False)
    log.info("wrote %s (%d rows, %d flagged)", path.name, len(review),
             int(explain["needs_review"].sum()))
    return path


def write_licence_map(cfg: dict) -> Path:
    path = _processed_dir(cfg) / "licence_map.csv"
    pd.DataFrame(_LICENCE_MAP).to_csv(path, index=False)
    log.info("wrote %s", path.name)
    return path


def write_all(ratings: pd.DataFrame, explain: pd.DataFrame,
              features: pd.DataFrame, cfg: dict) -> dict[str, Path]:
    return {
        "players": write_players_json(ratings, features, cfg),
        "game_roster": write_game_roster(ratings, features, cfg),
        "explain": write_explain_json(explain, cfg),
        "review": write_review_csv(explain, cfg),
        "licence_map": write_licence_map(cfg),
    }
