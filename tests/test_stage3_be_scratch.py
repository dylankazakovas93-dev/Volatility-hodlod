"""Stage 3 invariants: next-bar activation (except historical BE45's
documented same-bar exception), no lookahead, no overlap, control
reproduction. Run with:

    python3 -m pytest tests/test_stage3_be_scratch.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
OUT_DIR = os.path.join(REPO_ROOT, "outputs")

import scripts.stage3_engine as s3  # noqa: E402


def make_bars(rows):
    idx = pd.date_range("2024-01-01 08:00", periods=len(rows), freq="1min", tz="UTC")
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


def test_control_matches_no_management_first_passage():
    bars = make_bars([(100, 100, 100, 100), (100, 106, 100, 106)])
    pnl, reason, ts, audit = s3.simulate_no_management(bars, bars.index[0], bars.index[-1], 100.0, 1.0, 5.0, 5.0)
    assert reason == "TP" and pnl == 5.0


def test_exact_r_be_activates_next_bar_not_trigger_bar():
    """Trigger bar reaches +0.5R (2.5 of a 5-point SL) via its high, but
    also dips to the ORIGINAL stop on THAT SAME bar -- since activation is
    next-bar only, this must exit SL at the original stop, not BE."""
    bars = make_bars([
        (100, 100, 100, 100),          # touch bar
        (100, 102.5, 95.0, 96.0),      # trigger bar: hits +0.5R high AND original stop low, same bar
        (96.0, 100.0, 96.0, 99.0),
    ])
    pnl, reason, ts, audit = s3.simulate_exact_r_be(
        bars, bars.index[0], bars.index[-1], 100.0, 1.0, 20.0, 5.0, trigger_r=0.5)
    assert reason == "SL"
    assert pnl == -5.0


def test_exact_r_be_activates_on_bar_after_trigger():
    bars = make_bars([
        (100, 100, 100, 100),
        (100, 102.5, 100, 102.5),   # trigger bar: +0.5R reached, no stop hit
        (102, 103, 99.5, 100),      # next bar: dips to entry (100) -- BE should catch this
    ])
    pnl, reason, ts, audit = s3.simulate_exact_r_be(
        bars, bars.index[0], bars.index[-1], 100.0, 1.0, 20.0, 5.0, trigger_r=0.5)
    assert reason == "BE"
    assert pnl == 0.0
    assert audit["trigger_activated_ts"] == bars.index[2]


def test_scratch_never_exits_on_arming_bar_itself():
    """Arms on bar 1 (adverse -0.5R), and bar 1 ALSO happens to touch
    entry -- scratch must not fire until a STRICTLY LATER bar."""
    bars = make_bars([
        (100, 100, 100, 100),
        (100, 100.0, 97.5, 100.0),   # adverse -0.5R reached AND touches entry, same bar
        (99, 100.5, 98, 100),        # next bar also touches entry -- scratch should fire here
    ])
    pnl, reason, ts, audit = s3.simulate_scratch_on_recovery(
        bars, bars.index[0], bars.index[-1], 100.0, 1.0, 20.0, 5.0, adverse_r=0.5)
    assert reason == "SCRATCH"
    assert ts == bars.index[2]


def test_be45_uses_same_bar_activation_by_design():
    """Historical BE45: checkpoint bar's own low/high IS checked against
    the new stop in the same iteration -- documented, deliberate exception."""
    rows = [(100, 100, 100, 100)]  # touch bar
    for _ in range(45):
        rows.append((100, 100.1, 99.9, 100))  # i=0..44: pre-checkpoint, orig stop only
    rows.append((101, 101, 94.0, 94.0))  # i=45: checkpoint bar (open=101 >= entry -> armed)
    rows.append((94, 94, 94, 94))
    bars = make_bars(rows)
    pnl, reason, ts, audit = s3.simulate_be45(
        bars, bars.index[0], bars.index[-1], 100.0, 1.0, 50.0, 5.0, be_bar=45)
    # open of checkpoint bar (101) >= entry (100) -> armed; same bar's low (94) breaches
    # the new stop (100) -- exits BE, same bar, at entry-relative pnl 0
    assert reason == "BE"
    assert pnl == 0.0


def test_no_overlap_in_committed_ledgers():
    p = os.path.join(OUT_DIR, "stage3_ledger_no_be_control.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/run_stage3_be_scratch.py first")
    df = pd.read_csv(p)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df = df.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(df)):
        assert df.loc[i, "entry_time"] >= df.loc[i - 1, "exit_time"]


def test_control_reproduces_expected_headline():
    p = os.path.join(OUT_DIR, "stage3_candidate_summary.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/run_stage3_be_scratch.py first")
    df = pd.read_csv(p)
    control = df[df["candidate"] == "no_be_control"].iloc[0]
    assert control["n_trades"] == 247
    assert control["net_pts"] == pytest.approx(2132.91, abs=0.01)
    assert control["PF"] == pytest.approx(1.3836, abs=0.0001)


def test_reserved_years_never_in_any_ledger():
    import glob
    files = glob.glob(os.path.join(OUT_DIR, "stage3_ledger_*.csv"))
    if not files:
        pytest.skip("no stage3 ledgers present")
    reserved = {2019, 2021, 2022, 2024, 2025}
    for f in files:
        df = pd.read_csv(f)
        if len(df):
            assert set(df["year"].unique()).isdisjoint(reserved)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
