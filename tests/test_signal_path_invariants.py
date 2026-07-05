"""Stage 0 invariants for the independent all-hours signal-path dataset
(scripts/build_signal_paths.py). Run with:

    python3 -m pytest tests/test_signal_path_invariants.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
OUT_DIR = os.path.join(REPO_ROOT, "outputs")

from scripts.build_signal_paths import gap_or_liquidation_bar  # noqa: E402


def _read(path, ts_cols):
    p = os.path.join(OUT_DIR, path)
    if not os.path.exists(p):
        pytest.skip(f"{p} not present -- run scripts/build_signal_paths.py first")
    df = pd.read_csv(p)
    for c in ts_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


@pytest.fixture(scope="module")
def physical_touches():
    return _read("stage0_physical_touches.csv", ["created_at", "expiry_at", "touched_at"])


@pytest.fixture(scope="module")
def signal_paths():
    return _read("stage0_signal_paths.csv", ["created_at", "expiry_at", "touched_at",
                                              "forced_liquidation_ts", "mfe_ts", "mae_ts"])


@pytest.fixture(scope="module")
def excluded():
    return _read("stage0_excluded_touches.csv", ["touched_at"])


@pytest.fixture(scope="module")
def summary():
    import json
    p = os.path.join(OUT_DIR, "stage0_signal_summary.json")
    if not os.path.exists(p):
        pytest.skip("stage0_signal_summary.json not present")
    with open(p) as f:
        return json.load(f)


def test_physical_touch_reconciliation(summary):
    assert summary["physical_touches"] == summary["verified_baseline_physical_touches"] == 3486
    assert summary["reconciled"] is True


def test_no_entry_before_level_exists(signal_paths):
    assert (signal_paths["touched_at"] > signal_paths["created_at"]).all()


def test_expiry_excluded(signal_paths):
    assert (signal_paths["touched_at"] < signal_paths["expiry_at"]).all()


def test_at_most_one_physical_touch_per_side(physical_touches):
    dupes = physical_touches["level_id"][physical_touches["level_id"].duplicated()]
    assert dupes.empty


def test_signal_paths_are_subset_of_physical_touches(physical_touches, signal_paths):
    touched_ids = set(physical_touches.loc[physical_touches["touched_at"].notna(), "level_id"])
    signal_ids = set(signal_paths["level_id"])
    assert signal_ids <= touched_ids


def test_excluded_plus_qualifying_equals_all_physical_touches(physical_touches, signal_paths, excluded):
    n_touched = physical_touches["touched_at"].notna().sum()
    assert len(signal_paths) + len(excluded) == n_touched


def test_no_qualifying_signal_in_the_gap_or_on_liquidation_bar(signal_paths):
    for ts in signal_paths["touched_at"]:
        assert gap_or_liquidation_bar(ts) == "active"


def test_forced_liquidation_is_after_touch(signal_paths):
    assert (signal_paths["forced_liquidation_ts"] > signal_paths["touched_at"]).all()


def test_mfe_mae_timestamps_within_path(signal_paths):
    assert (signal_paths["mfe_ts"] >= signal_paths["touched_at"]).all()
    assert (signal_paths["mfe_ts"] <= signal_paths["forced_liquidation_ts"]).all()
    assert (signal_paths["mae_ts"] >= signal_paths["touched_at"]).all()
    assert (signal_paths["mae_ts"] <= signal_paths["forced_liquidation_ts"]).all()


def test_mfe_at_least_mae(signal_paths):
    # Neither MFE nor MAE is floored at zero -- a trade that never moves
    # favourably has a negative "best" point, and one that never moves
    # adversely has a positive "worst" point. Both are legitimate (72 and 76
    # of 3,331 signals respectively in this dataset). What must always hold
    # is mfe >= mae, since a bar's high is always >= its low, so the best
    # point reached can never be worse than the worst point reached.
    assert (signal_paths["mfe"] >= signal_paths["mae"]).all()


def test_exactly_one_of_mae_before_mfe_or_mfe_before_mae_when_distinct(signal_paths):
    both_true = signal_paths[signal_paths["mae_before_mfe"] & signal_paths["mfe_before_mae"]]
    # only valid when mae_ts == mfe_ts (tie)
    assert (both_true["mae_ts"] == both_true["mfe_ts"]).all()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
