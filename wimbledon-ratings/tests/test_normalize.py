"""Tests for the reusable normaliser - the core of the rating methodology."""
import numpy as np
import pandas as pd

from src import normalize as N


def test_bounds_within_envelope():
    s = pd.Series(range(200))
    r = N.scale_to_rating(s, floor=40, ceil=98, round_=False)
    assert r.min() > 40 and r.max() < 98          # strictly inside (no 0/100, no exact 40/98)
    assert r.between(40, 98).all()


def test_monotonic_non_decreasing():
    s = pd.Series([1, 2, 3, 10, 50, 51, 99, 100, 1000], dtype="float64")
    r = N.scale_to_rating(s, round_=False)
    ordered = r.iloc[s.argsort().values].values
    assert np.all(np.diff(ordered) >= -1e-9)      # higher input -> higher-or-equal rating


def test_nan_passthrough():
    s = pd.Series([1.0, np.nan, 3.0])
    r = N.scale_to_rating(s, round_=False)
    assert pd.isna(r.iloc[1])
    assert r.iloc[0] < r.iloc[2]


def test_ties_equal_rating():
    s = pd.Series([5.0, 5.0, 5.0, 9.0])
    r = N.scale_to_rating(s, round_=False)
    assert r.iloc[0] == r.iloc[1] == r.iloc[2]
    assert r.iloc[3] > r.iloc[0]


def test_single_value_maps_mid():
    s = pd.Series([7.0])
    pct = N.percentile_rank(s)
    assert pct.iloc[0] == 0.5
    assert abs(N.to_rating(pct).iloc[0] - 69.0) < 1e-9   # midpoint of 40..98


def test_winsor_limits_outlier_influence():
    # A massive outlier should not blow past the ceiling for the rest.
    s = pd.Series([1, 2, 3, 4, 5, 10_000], dtype="float64")
    r = N.scale_to_rating(s, round_=False)
    assert r.max() < 98


def test_per_group_percentile_independent_tours():
    df = pd.DataFrame({
        "tour": ["atp", "atp", "wta", "wta"],
        "x": [1.0, 2.0, 1.0, 2.0],
    })
    p = N.percentile_by_group(df, "x", "tour")
    # Within each tour the lower value ranks below the higher value.
    assert p.iloc[0] < p.iloc[1]
    assert p.iloc[2] < p.iloc[3]
    # Same relative position across tours.
    assert abs(p.iloc[0] - p.iloc[2]) < 1e-9


def test_weighted_percentile_renormalises_over_missing():
    parts = {"a": pd.Series([0.8, np.nan]), "b": pd.Series([0.4, 0.6])}
    weights = {"a": 0.5, "b": 0.5}
    comp = N.weighted_percentile(parts, weights)
    assert abs(comp.iloc[0] - 0.6) < 1e-9   # (0.8+0.4)/2
    assert abs(comp.iloc[1] - 0.6) < 1e-9   # only b present -> equals b
