"""Confirms the independently-coded engine (src/independent_strict_engine.py)
reproduces the canonical strict ledger (outputs/baseline_executed.csv) exactly,
row for row. This is a second, freshly-written implementation of the frozen
mechanics -- it does not import or call the reference engine's simulation code.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "outputs")


def _read_with_ts(path, ts_cols):
    df = pd.read_csv(path)
    for c in ts_cols:
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


@pytest.fixture(scope="module")
def reference():
    p = os.path.join(OUT_DIR, "baseline_executed.csv")
    if not os.path.exists(p):
        pytest.skip("run src/strict_engine.py first")
    return _read_with_ts(p, ["entry_time", "exit_time"])


@pytest.fixture(scope="module")
def independent():
    p = os.path.join(OUT_DIR, "independent_executed.csv")
    if not os.path.exists(p):
        pytest.skip("run src/independent_strict_engine.py first")
    return _read_with_ts(p, ["entry_time", "exit_time"])


def _key(df):
    return (df["level_id"].astype(str) + "|" + df["entry_time"].astype(str) + "|" +
            df["side"].astype(str) + "|" + df["session_date"].astype(str))


def test_same_row_count(reference, independent):
    assert len(reference) == len(independent) == 1107


def test_same_headline_numbers(reference, independent):
    assert round(float(reference["pnl"].sum()), 2) == round(float(independent["pnl"].sum()), 2) == 6648.17

    def pf(s):
        g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
        return g / l if l > 0 else float("inf")

    assert round(pf(reference["pnl"]), 4) == round(pf(independent["pnl"]), 4) == 1.2924


def test_every_row_matches_by_identity_key(reference, independent):
    ref_keys = set(_key(reference))
    ind_keys = set(_key(independent))
    assert ref_keys == ind_keys
    assert len(ref_keys) == 1107


def test_no_pnl_or_exit_reason_divergence(reference, independent):
    ref_i = reference.set_index(_key(reference))
    ind_i = independent.set_index(_key(independent))
    ind_i = ind_i.loc[ref_i.index]
    assert (ref_i["exit_reason"].values == ind_i["exit_reason"].values).all()
    assert (abs(ref_i["pnl"].values - ind_i["pnl"].values) < 0.01).all()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
