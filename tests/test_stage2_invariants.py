"""Stage 2 invariants: no trade overlap, SAL causality, window-block
consumption. Run with:

    python3 -m pytest tests/test_stage2_invariants.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
OUT_DIR = os.path.join(REPO_ROOT, "outputs")

from scripts.stage2_engine import block_of, BLOCKS  # noqa: E402


def _read(path):
    p = os.path.join(OUT_DIR, path)
    if not os.path.exists(p):
        pytest.skip(f"{p} not present -- run scripts/run_stage2_timewindow_sal.py first")
    df = pd.read_csv(p)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    return df.sort_values("entry_time").reset_index(drop=True)


@pytest.fixture(scope="module")
def baseline_sal_off():
    return _read("stage2_baseline_sal_off_executed.csv")


@pytest.fixture(scope="module")
def baseline_sal_on():
    return _read("stage2_baseline_sal_on_executed.csv")


@pytest.fixture(scope="module")
def selected_window():
    return _read("stage2_window_E-F_sal_off_executed.csv")


def test_no_overlap_baseline_sal_off(baseline_sal_off):
    for i in range(1, len(baseline_sal_off)):
        assert baseline_sal_off.loc[i, "entry_time"] >= baseline_sal_off.loc[i - 1, "exit_time"]


def test_no_overlap_baseline_sal_on(baseline_sal_on):
    for i in range(1, len(baseline_sal_on)):
        assert baseline_sal_on.loc[i, "entry_time"] >= baseline_sal_on.loc[i - 1, "exit_time"]


def test_no_overlap_selected_window(selected_window):
    for i in range(1, len(selected_window)):
        assert selected_window.loc[i, "entry_time"] >= selected_window.loc[i - 1, "exit_time"]


def test_no_same_bar_reentry(baseline_sal_off):
    for i in range(1, len(baseline_sal_off)):
        assert baseline_sal_off.loc[i, "entry_time"] != baseline_sal_off.loc[i - 1, "exit_time"]


@pytest.fixture(scope="module")
def sal_audit():
    p = os.path.join(OUT_DIR, "stage2_sal_audit_baseline.csv")
    if not os.path.exists(p):
        pytest.skip("stage2_sal_audit_baseline.csv not present")
    df = pd.read_csv(p)
    if df.empty:
        pytest.skip("no SAL events recorded")
    df["touched_at"] = pd.to_datetime(df["touched_at"], utc=True)
    if "exit_time" in df.columns:
        df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce", utc=True)
    return df


def test_sal_activation_only_on_negative_realized_pnl(sal_audit):
    activations = sal_audit[sal_audit["event"] == "SAL_activated"]
    assert (activations["pnl"] < 0).all()


def test_sal_blocked_touches_occur_after_activation_same_session(sal_audit):
    activations = sal_audit[sal_audit["event"] == "SAL_activated"]
    blocked = sal_audit[sal_audit["event"] == "blocked_by_SAL"]
    for sess, blocked_sess in blocked.groupby("session_date"):
        act_sess = activations[activations["session_date"] == sess]
        if act_sess.empty:
            continue
        first_activation = act_sess["exit_time"].min()
        assert (blocked_sess["touched_at"] >= first_activation).all()


def test_sal_resets_across_sessions(sal_audit):
    """No SAL_activated event's session carries a blocked touch from a
    different (later) session date -- i.e. blocking is confined to the
    activating session."""
    activations = sal_audit[sal_audit["event"] == "SAL_activated"]
    blocked = sal_audit[sal_audit["event"] == "blocked_by_SAL"]
    blocked_sessions = set(blocked["session_date"])
    activation_sessions = set(activations["session_date"])
    assert blocked_sessions <= activation_sessions


def test_block_assignment_covers_full_session_minus_gap_and_last_bar():
    # every minute from 0 (18:00) to 1319 (15:58) belongs to exactly one block
    for m in range(0, 1319):
        assert block_of(m) is not None
    # block boundaries sum to the full pre-liquidation-bar session length
    total_minutes = sum(hi - lo for lo, hi in BLOCKS.values())
    assert total_minutes == 1319


def test_reserved_years_never_in_selected_window_report(selected_window):
    reserved = {2019, 2021, 2022, 2024, 2025}
    assert set(selected_window["year"].unique()).isdisjoint(reserved)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
