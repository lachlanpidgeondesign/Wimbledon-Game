"""End-to-end pipeline runner.

    python run.py                # fetch (cached) + build everything
    python run.py --offline      # use only already-cached data
    python run.py --force-fetch  # re-download raw data
    python run.py --limit 25     # debug: keep top-25 per tour (faster)

Outputs land in data/processed/. See README.md for the full design.
"""
from __future__ import annotations

import argparse

import pandas as pd

from src import editorial, elo, explain, export, fetch, form, grass, ingest, net, players, ratings
from src.utils import get_logger, load_all_config

log = get_logger("run")

# Charting signal columns that must exist on the feature table for ratings.
_NET_COLS = ["net_win_pct", "net_volume", "fh_index", "bh_index"]


def build_features(data, cfg) -> pd.DataFrame:
    """Selection + grass aggregates + charting signals -> one row per player."""
    ecfg = cfg["weights"]["elo"]
    grass_surfaces = tuple(cfg["sources"]["grass_surfaces"])
    elo_by_tour = {
        tour: elo.compute_elo(data.matches[tour], ecfg["k"], ecfg["init"], grass_surfaces)
        for tour in ("atp", "wta")
    }

    feats = players.select(data, elo_by_tour, cfg)

    all_matches = pd.concat([data.matches["atp"], data.matches["wta"]], ignore_index=True)
    long = grass.build_player_match_long(all_matches)
    grass_agg = grass.grass_aggregates(long, cfg).drop(columns=["tour"])
    signals = net.net_and_wing_signals(
        data.mcp_overview, data.mcp_net, data.mcp_matches, data.players)
    form_agg = form.clutch_stamina_aggregates(all_matches, cfg).drop(columns=["tour"])

    feats = feats.merge(grass_agg, on="player_id", how="left")
    feats = feats.merge(signals, on="player_id", how="left")
    feats = feats.merge(form_agg, on="player_id", how="left")
    for col in _NET_COLS:
        if col not in feats.columns:
            feats[col] = pd.NA
    feats["n_grass_matches"] = feats["n_grass_matches"].fillna(0)
    feats["serve_sample_ok"] = feats["serve_sample_ok"].fillna(False)
    return feats


def main() -> None:
    ap = argparse.ArgumentParser(description="Free-data Wimbledon ratings pipeline")
    ap.add_argument("--offline", action="store_true", help="use cached data only")
    ap.add_argument("--force-fetch", action="store_true", help="re-download raw data")
    ap.add_argument("--limit", type=int, default=0, help="debug: keep top-N per tour")
    args = ap.parse_args()

    cfg = load_all_config()

    if not args.offline:
        fetch.fetch_all(cfg, force=args.force_fetch)
    data = ingest.load_default(cfg)

    feats = build_features(data, cfg)
    if args.limit:
        feats = feats.groupby("tour", group_keys=False).head(args.limit)
        log.info("debug limit: %d players", len(feats))

    # Switch the working key from Sackmann's numeric id to the output slug so the
    # editorial overrides + JSON all share one stable, human-readable id.
    feats = feats.rename(columns={"player_id": "sackmann_id", "slug": "player_id"})

    rate, detail = ratings.compute_ratings(feats, cfg["weights"])
    exp = explain.build_explain(feats, detail, rate)
    exp = editorial.auto_flag(exp, cfg)
    rate, exp = editorial.apply_overrides(rate, exp)

    paths = export.write_all(rate, exp, feats, cfg)

    # ---- console summary --------------------------------------------------
    log.info("=" * 60)
    log.info("DONE - %d players rated", len(rate))
    for tour in ("atp", "wta"):
        n = int((rate["tour"] == tour).sum())
        log.info("  %s: %d players", tour, n)
    tier_counts = {a: exp[exp["attribute"] == a]["tier"].value_counts().to_dict()
                   for a in ratings.ATTRS}
    log.info("tier mix per attribute (data vs model):")
    for a, counts in tier_counts.items():
        log.info("  %-12s %s", a, counts)
    log.info("flagged for editorial review: %d/%d",
             int(exp["needs_review"].sum()), len(exp))
    for name, path in paths.items():
        log.info("  -> %s", path)


if __name__ == "__main__":
    main()
