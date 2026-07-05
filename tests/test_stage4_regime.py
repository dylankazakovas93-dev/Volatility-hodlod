"""Stage 4 no-lookahead / causality tests. Run with:

    python3 -m pytest tests/test_stage4_regime.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
OUT_DIR = os.path.join(REPO_ROOT, "outputs")

from scripts.stage4_regime_data import trailing_sessions, session_start_ts  # noqa: E402
from scripts.stage4_garch import forecast_before  # noqa: E402
from scripts.stage4_hmm import state_before  # noqa: E402


def test_trailing_sessions_never_includes_current_or_future():
    all_sessions = [f"2024-01-{d:02d}" for d in range(1, 31)]
    current = "2024-01-15"
    trailing = trailing_sessions(all_sessions, current, max_sessions=120, min_sessions=5)
    assert current not in trailing
    assert all(s < current for s in trailing)


def test_trailing_sessions_respects_max_and_min():
    all_sessions = [f"s{i:04d}" for i in range(300)]
    trailing = trailing_sessions(all_sessions, "s0250", max_sessions=120, min_sessions=20)
    assert len(trailing) == 120
    trailing_short = trailing_sessions(all_sessions, "s0010", max_sessions=120, min_sessions=20)
    assert trailing_short is None  # fewer than min_sessions available


def test_garch_forecast_uses_only_completed_5min_bars():
    idx = pd.date_range("2024-01-01 08:00", periods=10, freq="5min", tz="UTC")
    series = pd.Series(range(10), index=idx, dtype=float)
    cache = {"sess": series}
    # entry exactly at a bar's start: that bar is NOT yet complete -> must
    # use the PRIOR bar's forecast, not this one
    entry_ts = idx[5]
    val = forecast_before(cache, "sess", entry_ts)
    assert val == 4.0  # idx[4]'s forecast, not idx[5]'s
    # entry 5 minutes after a bar started (bar now complete)
    entry_ts2 = idx[5] + pd.Timedelta(minutes=5)
    val2 = forecast_before(cache, "sess", entry_ts2)
    assert val2 == 5.0


def test_hmm_state_before_uses_only_completed_bars():
    idx = pd.date_range("2024-01-01 08:00", periods=5, freq="5min", tz="UTC")
    df = pd.DataFrame({"state_label": ["A", "B", "C", "D", "E"], "max_prob": [0.9] * 5}, index=idx)
    cache = {"sess": df}
    label, prob = state_before(cache, "sess", idx[3])
    assert label == "C"  # idx[2]'s state -- idx[3]'s bar is not yet complete at entry_ts=idx[3]


@pytest.fixture(scope="module")
def regime_features():
    p = os.path.join(OUT_DIR, "stage4_regime_features.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/build_stage4_regime_features.py first")
    return pd.read_csv(p)


def test_regime_features_only_dev_years(regime_features):
    reserved = {2019, 2021, 2022, 2024, 2025}
    assert set(regime_features["year"].unique()).isdisjoint(reserved)


def test_hmm_states_only_documented_labels(regime_features):
    valid2 = {"LOW_VOL", "HIGH_VOL"}
    valid3 = {"LOW_VOL", "MID_VOL", "HIGH_VOL"}
    s2 = set(regime_features["hmm2_state"].dropna().unique())
    s3 = set(regime_features["hmm3_state"].dropna().unique())
    assert s2 <= valid2
    assert s3 <= valid3


def test_garch_percentile_bounded_0_100(regime_features):
    p = regime_features["garch_percentile"].dropna()
    assert (p >= 0).all() and (p <= 100).all()


@pytest.fixture(scope="module")
def gate_eval():
    p = os.path.join(OUT_DIR, "stage4_gate_evaluation.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/evaluate_stage4_gate.py first")
    return pd.read_csv(p)


def test_no_reserved_year_in_any_ledger():
    import glob
    files = glob.glob(os.path.join(OUT_DIR, "stage4_ledger_*.csv"))
    if not files:
        pytest.skip("no stage4 ledgers present")
    reserved = {2019, 2021, 2022, 2024, 2025}
    for f in files:
        df = pd.read_csv(f)
        if len(df):
            assert set(df["year"].unique()).isdisjoint(reserved)


def test_no_overlap_in_selected_candidate_ledger():
    p = os.path.join(OUT_DIR, "stage4_ledger_hmm3_HIGH_VOL_only.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/run_stage4_regime_filters.py first")
    df = pd.read_csv(p)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df = df.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(df)):
        assert df.loc[i, "entry_time"] >= df.loc[i - 1, "exit_time"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
