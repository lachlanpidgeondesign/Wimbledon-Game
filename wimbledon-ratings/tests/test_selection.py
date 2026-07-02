"""Tests for player selection: appearance filter, top-N, notability ordering."""
import pandas as pd

from src import elo, players
from src.ingest import Data


def _matches(rows, tour):
    df = pd.DataFrame(rows)
    df["tour"] = tour
    df["date"] = pd.to_datetime(df["year"], format="%Y")
    df["match_num"] = range(1, len(df) + 1)
    df["winner_id"] = df["winner_id"].astype(str)
    df["loser_id"] = df["loser_id"].astype(str)
    return df


def _wimbledon(winner, loser, rnd, year=2015, surface="Grass"):
    return {"tourney_name": "Wimbledon", "surface": surface, "round": rnd,
            "winner_id": winner, "loser_id": loser,
            "winner_name": f"Player {winner}", "loser_name": f"Player {loser}",
            "year": year}


def _build_data():
    # A beats B in the final (champion); B beat C in SF; C beat D in R16 but D's
    # match is NOT at Wimbledon -> D has no Wimbledon appearance.
    atp_rows = [
        _wimbledon("A", "B", "F"),
        _wimbledon("B", "C", "SF"),
        _wimbledon("C", "E", "R16"),
        {"tourney_name": "Halle", "surface": "Grass", "round": "R16",
         "winner_id": "C", "loser_id": "D",
         "winner_name": "Player C", "loser_name": "Player D", "year": 2015},
    ]
    wta_rows = [
        _wimbledon("W", "X", "F"),
        _wimbledon("X", "Y", "SF"),
        _wimbledon("Y", "Z", "QF"),
    ]
    data = Data()
    for tour, rows, ids in (("atp", atp_rows, list("ABCDE")),
                            ("wta", wta_rows, list("WXYZ"))):
        data.matches[tour] = _matches(rows, tour)
        data.players[tour] = pd.DataFrame({
            "player_id": ids,
            "full_name": [f"Player {i}" for i in ids],
            "tour": tour,
        })
        data.rankings[tour] = pd.DataFrame({
            "player": ids,
            "rank": list(range(1, len(ids) + 1)),
            "ranking_date": 20150101,
        })
    return data


def _cfg(n=3):
    return {
        "sources": {"grass_surfaces": ["Grass"], "year_start": 2006, "year_end": 2025},
        "selection": {
            "n_per_tour": n,
            "require_wimbledon_appearance": True,
            "notability": {"peak_grass_elo": 0.4, "best_wimbledon_round": 0.25,
                           "weeks_top10": 0.2, "grass_titles": 0.15},
        },
    }


def _elo_by_tour(data):
    return {t: elo.compute_elo(data.matches[t]) for t in ("atp", "wta")}


def test_appearance_filter_excludes_non_wimbledon_player():
    data = _build_data()
    sel = players.select(data, _elo_by_tour(data), _cfg(n=10))
    names = set(sel["name"])
    assert "Player D" not in names          # only played a non-Wimbledon grass match
    assert "Player A" in names


def test_respects_n_per_tour():
    data = _build_data()
    sel = players.select(data, _elo_by_tour(data), _cfg(n=2))
    assert (sel["tour"] == "atp").sum() == 2
    assert (sel["tour"] == "wta").sum() == 2


def test_champion_outranks_field_on_notability():
    data = _build_data()
    sel = players.select(data, _elo_by_tour(data), _cfg(n=10))
    atp = sel[sel["tour"] == "atp"].set_index("name")
    assert atp.loc["Player A", "notability"] >= atp.loc["Player C", "notability"]


def test_slug_generated():
    data = _build_data()
    sel = players.select(data, _elo_by_tour(data), _cfg(n=10))
    assert (sel["slug"] == sel["name"].str.lower().str.replace(" ", "-")).all()
