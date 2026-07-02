"""Editorial workflow: auto-flag low-confidence ratings and apply manual overrides.

The pipeline is deliberately a two-pass system:
  1. data draft  - everything computed automatically
  2. editorial   - reviewers inspect flagged ratings and record adjustments in
                   config/editorial_overrides.csv, which this module applies.

Auto-flags (a rating is flagged if ANY hold):
  * modelled       - tier == "model" (all forehand/backhand; net without charting)
  * low_sample     - fewer than min_grass_matches grass matches
  * outlier        - rating in the top/bottom 5% within its tour+attribute
"""
from __future__ import annotations

import pandas as pd

from .utils import get_logger, project_root

log = get_logger("editorial")


def auto_flag(explain: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    e = explain.copy()
    min_matches = cfg["sources"]["min_grass_matches"]

    e["flag_modelled"] = e["tier"].eq("model")
    e["flag_low_sample"] = e["n_grass_matches"] < min_matches

    lo = e.groupby(["tour", "attribute"])["rating"].transform(lambda s: s.quantile(0.05))
    hi = e.groupby(["tour", "attribute"])["rating"].transform(lambda s: s.quantile(0.95))
    e["flag_outlier"] = (e["rating"] <= lo) | (e["rating"] >= hi)

    e["needs_review"] = e[["flag_modelled", "flag_low_sample", "flag_outlier"]].any(axis=1)
    e["overridden"] = False
    e["reviewer"] = ""
    e["note"] = ""
    log.info("auto-flag: %d/%d ratings need review (%.0f%%)",
             int(e["needs_review"].sum()), len(e),
             100 * e["needs_review"].mean())
    return e


def apply_overrides(ratings: pd.DataFrame, explain: pd.DataFrame
                    ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply config/editorial_overrides.csv to both the wide ratings + explain."""
    path = project_root() / "config" / "editorial_overrides.csv"
    if not path.exists():
        return ratings, explain
    ov = pd.read_csv(path, comment="#")
    ov = ov.dropna(subset=["player_id", "attribute", "value"])
    if ov.empty:
        log.info("no editorial overrides to apply")
        return ratings, explain

    r = ratings.set_index("player_id")
    e = explain.set_index(["player_id", "attribute"])
    applied = 0
    for _, row in ov.iterrows():
        pid, attr, val = row["player_id"], row["attribute"], int(row["value"])
        if pid in r.index and attr in r.columns:
            r.at[pid, attr] = val
            if (pid, attr) in e.index:
                e.at[(pid, attr), "rating"] = val
                e.at[(pid, attr), "overridden"] = True
                e.at[(pid, attr), "reviewer"] = str(row.get("reviewer", ""))
                e.at[(pid, attr), "note"] = str(row.get("note", ""))
            applied += 1
        else:
            log.warning("override skipped (unknown player/attr): %s / %s", pid, attr)
    log.info("applied %d editorial override(s)", applied)
    return r.reset_index(), e.reset_index()
