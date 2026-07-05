"""Deterministic unit tests for scripts/stage1_engine.py's first-passage
logic, using small synthetic OHLCV frames (no dependency on the 211MB
canonical bars file). Run with:

    python3 -m pytest tests/test_stage1_first_passage.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from scripts.stage1_engine import round_tp, round_sl, first_passage_exit, run_replay  # noqa: E402


def make_bars(rows):
    idx = pd.date_range("2024-01-01 18:00", periods=len(rows), freq="1min", tz="UTC")
    df = pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])
    return df


def test_tick_rounding():
    assert round_tp(pd.Series([10.01]))[0] == 10.25
    assert round_tp(pd.Series([10.25]))[0] == 10.25
    assert round_sl(pd.Series([10.24]))[0] == 10.0
    assert round_sl(pd.Series([0.01]))[0] == 0.25  # floored at minimum tick


def test_entry_bar_stop_only_no_optimistic_tp():
    """Entry bar itself hits both TP and SL range-wise -- must exit SL, not TP,
    since an entry-bar TP is never credited without causal proof."""
    bars = make_bars([
        (100, 110, 90, 100),   # touch bar: range spans both target(+5) and stop(-5)
        (100, 100, 100, 100),
    ])
    pnl, reason, exit_ts = first_passage_exit(bars, bars.index[0], bars.index[-1], 100.0, 1.0, 5.0, 5.0)
    assert reason == "SL"
    assert pnl == -5.0


def test_only_tp_hit_later_bar():
    bars = make_bars([
        (100, 100, 100, 100),   # touch bar, no move
        (100, 106, 100, 106),   # TP (target=105) hit, SL(95) not hit
    ])
    pnl, reason, exit_ts = first_passage_exit(bars, bars.index[0], bars.index[-1], 100.0, 1.0, 5.0, 5.0)
    assert reason == "TP"
    assert pnl == 5.0


def test_only_sl_hit_later_bar():
    bars = make_bars([
        (100, 100, 100, 100),
        (100, 100, 94, 94),   # SL(95) hit
    ])
    pnl, reason, exit_ts = first_passage_exit(bars, bars.index[0], bars.index[-1], 100.0, 1.0, 5.0, 5.0)
    assert reason == "SL"
    assert pnl == -5.0


def test_same_bar_ambiguity_resolves_to_sl():
    bars = make_bars([
        (100, 100, 100, 100),
        (100, 108, 92, 100),   # both target(105) and stop(95) inside this bar's range
    ])
    pnl, reason, exit_ts = first_passage_exit(bars, bars.index[0], bars.index[-1], 100.0, 1.0, 5.0, 5.0)
    assert reason == "SL"
    assert pnl == -5.0


def test_cutoff_when_neither_hit():
    bars = make_bars([
        (100, 100, 100, 100),
        (100, 102, 98, 101),
        (101, 103, 99, 102),
    ])
    pnl, reason, exit_ts = first_passage_exit(bars, bars.index[0], bars.index[-1], 100.0, 1.0, 5.0, 5.0)
    assert reason == "cutoff"
    assert pnl == pytest.approx(2.0)


def test_short_direction_mirrors_long():
    bars = make_bars([
        (100, 100, 100, 100),
        (100, 104, 94, 94),   # for a short, stop=105 (above, not touched), target=95 (below, hit) -> TP
    ])
    pnl, reason, exit_ts = first_passage_exit(bars, bars.index[0], bars.index[-1], 100.0, -1.0, 5.0, 5.0)
    assert reason == "TP"
    assert pnl == 5.0


def test_no_overlapping_positions_in_replay():
    bars = make_bars([(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1) for i in range(500)])
    touches = pd.DataFrame({
        "level_id": ["a", "b", "c"],
        "touched_at": [bars.index[0], bars.index[5], bars.index[400]],
        "forced_liquidation_ts": [bars.index[-1]] * 3,
        "side": ["lower", "lower", "lower"],
        "entry_price": [100.0, 100.5, 140.0],
        "session_date": ["2024-01-02"] * 3,
        "year": [2024, 2024, 2024],
        "tp_dist_stage1": [50.0, 50.0, 1.0],
        "sl_dist_stage1": [50.0, 50.0, 1.0],
    })
    executed, skipped = run_replay(bars, touches, "tp_dist_stage1", "sl_dist_stage1", cost_pts=0.0)
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(ex)):
        assert ex.loc[i, "entry_time"] >= ex.loc[i - 1, "exit_time"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
