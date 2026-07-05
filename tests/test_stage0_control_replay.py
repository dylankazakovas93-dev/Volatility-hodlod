"""Invariants for the Stage 0 one-position cutoff-only control replay
(scripts/run_stage0_control_replay.py, dataset B). Run with:

    python3 -m pytest tests/test_stage0_control_replay.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "outputs")


@pytest.fixture(scope="module")
def executed():
    p = os.path.join(OUT_DIR, "stage0_control_executed.csv")
    if not os.path.exists(p):
        pytest.skip(f"{p} not present -- run scripts/run_stage0_control_replay.py first")
    df = pd.read_csv(p)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    return df.sort_values("entry_time").reset_index(drop=True)


def test_no_overlapping_positions(executed):
    for i in range(1, len(executed)):
        assert executed.loc[i, "entry_time"] >= executed.loc[i - 1, "exit_time"]


def test_chronological_order(executed):
    assert executed["entry_time"].is_monotonic_increasing


def test_all_exits_are_cutoff(executed):
    assert (executed["exit_reason"] == "cutoff").all()


def test_no_level_id_executes_twice(executed):
    dupes = executed["level_id"][executed["level_id"].duplicated()]
    assert dupes.empty


def test_pnl_reconciles_with_prices(executed):
    long_mask = executed["side"] == "lower"
    computed = pd.Series(index=executed.index, dtype=float)
    computed[long_mask] = executed.loc[long_mask, "exit_price"] - executed.loc[long_mask, "entry_price"]
    computed[~long_mask] = executed.loc[~long_mask, "entry_price"] - executed.loc[~long_mask, "exit_price"]
    assert (computed - executed["pnl"]).abs().max() < 1e-6


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
