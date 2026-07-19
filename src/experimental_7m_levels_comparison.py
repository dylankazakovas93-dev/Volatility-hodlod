"""EXPERIMENTAL -- NOT part of the frozen baseline.

Answers: given the material level differences measured between 1-minute-IB
and 7-minute-IB level generation (see docs/TIMEFRAME_DIVERGENCE_7M.md),
which one actually performs better when run through the identical, frozen
execution engine?

Design: apples-to-apples swap. Both runs use:
  - the same 1-minute bars for trade SIMULATION (touch detection, BE
    timing, SAL, cutoff -- all identical minute-by-minute precision)
  - the same session_date / created_at (so entry-window timing and level
    lifetime/expiry are identical)
  - the SAME frozen src.strict_engine.run_strict state machine

Only the upper_level / lower_level VALUES differ: one run uses levels
computed from a clean 60-bar (60-minute) 1-minute IB; the other uses levels
computed from an 8.57-bar (uneven) 7-minute-resampled IB, then substituted
in before simulation. This isolates exactly the one variable in question --
not a different engine, not different execution timing, not a parameter
search.

Usage:
    python3 -m src.experimental_7m_levels_comparison \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
        --out-dir outputs_experimental
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv, load_gvz_daily  # noqa: E402
from src.level_generation import NQ_PARAMS, generate_levels  # noqa: E402
from src.strict_engine import bar_ranges, physical_touches, run_strict  # noqa: E402


def build_hybrid_levels(levels_1m, levels_7m):
    """Same session_date/created_at as the 1m levels; upper/lower level
    VALUES substituted from the 7m-derived computation."""
    hybrid = levels_1m.set_index("session_date")
    lvl7 = levels_7m.set_index("session_date")[["upper_level", "lower_level"]]
    hybrid.update(lvl7)
    return hybrid.reset_index()


def run_variant(bars_1m, ranges, levels_df, label):
    lvls = list(levels_df.itertuples(index=False))
    events = physical_touches(bars_1m, lvls)
    summary, ex_df, _ = run_strict(bars_1m, ranges, events)
    summary["label"] = label
    return summary, ex_df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", default="outputs_experimental")
    args = ap.parse_args()

    out_dir = os.path.join(REPO_ROOT, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bars_1m = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    levels_1m = generate_levels(bars_1m, vxn, params=NQ_PARAMS)

    bars_7m = bars_1m.resample("7min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    levels_7m = generate_levels(bars_7m, vxn, params=NQ_PARAMS)

    hybrid = build_hybrid_levels(levels_1m, levels_7m)
    ranges = bar_ranges(bars_1m)

    s1, ex1 = run_variant(bars_1m, ranges, levels_1m, "1m_levels_canonical")
    s7, ex7 = run_variant(bars_1m, ranges, hybrid, "7m_derived_levels")

    print("=== SIDE BY SIDE ===")
    print(f"{'metric':20s} {'1m levels':>14s} {'7m levels':>14s}")
    for k in ["executed", "net_pts", "PF", "TP", "SL", "BE", "cutoff", "max_drawdown"]:
        print(f"{k:20s} {str(s1.get(k)):>14s} {str(s7.get(k)):>14s}")
    print(f"negative years, 1m levels: {s1['negative_years']}")
    print(f"negative years, 7m levels: {s7['negative_years']}")

    ex1.to_csv(os.path.join(out_dir, "levels_1m_executed.csv"), index=False)
    ex7.to_csv(os.path.join(out_dir, "levels_7m_derived_executed.csv"), index=False)
    with open(os.path.join(out_dir, "levels_1m_vs_7m_summary.json"), "w") as f:
        json.dump({"1m_levels": s1, "7m_derived_levels": s7}, f, indent=2, default=str)

    print(f"\noutputs written to {out_dir}/")


if __name__ == "__main__":
    main()
