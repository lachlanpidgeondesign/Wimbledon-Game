"""Small shared helpers: config loading, name normalisation, slugs, logging."""
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import yaml

LOG_FORMAT = "%(asctime)s  %(levelname)-7s %(name)s  %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Return a module logger, configuring root once."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%H:%M:%S")
    return logging.getLogger(name)


def project_root() -> Path:
    """Repository root (the folder containing config/ and src/)."""
    return Path(__file__).resolve().parents[1]


def load_config(name: str) -> dict:
    """Load a YAML config file from the config/ directory by stem name."""
    path = project_root() / "config" / f"{name}.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_all_config() -> dict:
    """Load and merge the three config files into one dict keyed by stem."""
    return {
        "sources": load_config("sources"),
        "weights": load_config("weights"),
        "selection": load_config("selection"),
    }


def tour_source(cfg: dict, tour: str) -> dict:
    """Resolve per-tour data source: base URL + effective year window.

    A tour entry under sources.sackmann.tours may override year_start/year_end;
    anything unset falls back to the global window. This lets each tour fetch
    only the seasons its mirror actually carries.
    """
    src = cfg["sources"]
    tcfg = src["sackmann"]["tours"][tour]
    return {
        "base": tcfg["base"],
        "year_start": tcfg.get("year_start", src["year_start"]),
        "year_end": tcfg.get("year_end", src["year_end"]),
    }


def strip_accents(text: str) -> str:
    """Remove diacritics so 'Cilic' and 'Čilić' compare equal."""
    if text is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_name(name: str) -> str:
    """Lower-case, de-accented, punctuation-stripped key for matching names."""
    text = strip_accents(name).lower()
    text = re.sub(r"[.'`-]", " ", text)
    text = re.sub(r"[^a-z\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(name: str) -> str:
    """Stable output player_id, e.g. 'Carlos Alcaraz' -> 'carlos-alcaraz'."""
    return re.sub(r"\s+", "-", normalize_name(name))


def clean_id(series):
    """Normalise an id column to plain integer strings.

    Sackmann files sometimes load id columns as floats when the column contains
    NaNs (e.g. '103819.0'), which then fails to join against clean integer ids
    ('103819'). This strips the trailing '.0' so every id join is robust.
    """
    import pandas as pd
    return pd.Series(series).astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
