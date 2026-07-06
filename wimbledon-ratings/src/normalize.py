"""The reusable normaliser: raw metric -> 0-100 rating.

Design goals (from the brief):
  * percentile based (robust to scale / outliers)
  * avoid extreme 0 and 100 values
  * target range ~40-98 for this elite field

Approach: winsorise the reference distribution, rank a value within it to get a
percentile strictly inside (0, 1) using rank / (n + 1), then map linearly onto
[floor, ceil]. Per-tour cohorts are handled by `percentile_by_group` so a WTA
"95 serve" means elite-for-tour rather than being penalised against ATP ace rates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FLOOR = 40
CEIL = 98


def percentile_rank(series, winsor_low: float = 0.02,
                    winsor_high: float = 0.98) -> pd.Series:
    """Percentile of each value within the (winsorised) series, in (0, 1).

    NaNs pass through as NaN. Ties share an averaged rank. A degenerate series
    (all equal / single value) maps to 0.5.
    """
    s = pd.Series(series, dtype="float64")
    out = pd.Series(np.nan, index=s.index, dtype="float64")
    valid = s.dropna()
    if valid.empty:
        return out
    if valid.nunique() == 1:
        out.loc[valid.index] = 0.5
        return out

    lo, hi = valid.quantile(winsor_low), valid.quantile(winsor_high)
    clipped = valid.clip(lo, hi)
    ranks = clipped.rank(method="average")
    # rank / (n + 1) keeps the result strictly inside (0, 1) -> never 0 or 1,
    # so the mapped rating never hits the exact floor/ceil extremes.
    out.loc[valid.index] = (ranks / (len(clipped) + 1)).values
    return out


def to_rating(percentile, floor: int = FLOOR, ceil: int = CEIL):
    """Map a percentile in (0, 1) onto the [floor, ceil] rating envelope.

    Series in -> Series out (index preserved); scalars/arrays pass through as
    NumPy values.
    """
    p = np.asarray(percentile, dtype="float64")
    rating = floor + p * (ceil - floor)
    if isinstance(percentile, pd.Series):
        return pd.Series(rating, index=percentile.index)
    return rating


def scale_to_rating(series, floor: int = FLOOR, ceil: int = CEIL,
                    winsor_low: float = 0.02, winsor_high: float = 0.98,
                    round_: bool = True) -> pd.Series:
    """Convenience: percentile-rank a series then map to ratings."""
    pct = percentile_rank(series, winsor_low, winsor_high)
    rating = pd.Series(to_rating(pct, floor, ceil), index=pct.index)
    return rating.round() if round_ else rating


def percentile_by_group(df: pd.DataFrame, value_col: str, group_col: str,
                        winsor_low: float = 0.02,
                        winsor_high: float = 0.98) -> pd.Series:
    """Percentile-rank `value_col` within each `group_col` cohort (e.g. tour)."""
    return df.groupby(group_col)[value_col].transform(
        lambda s: percentile_rank(s, winsor_low, winsor_high)
    )


def weighted_percentile(parts: dict[str, pd.Series],
                        weights: dict[str, float]) -> pd.Series:
    """Combine sub-metric percentiles into a composite in [0, 1].

    Per row, weights are renormalised over whichever sub-metrics are present, so
    a player missing one input still gets a fair composite from the rest.
    """
    idx = next(iter(parts.values())).index
    num = pd.Series(0.0, index=idx)
    den = pd.Series(0.0, index=idx)
    for key, pct in parts.items():
        w = weights[key]
        present = pct.notna()
        num = num.add(pct.fillna(0) * w * present, fill_value=0)
        den = den.add(present * w, fill_value=0)
    composite = num / den.replace(0, np.nan)
    return composite.clip(0, 1)
