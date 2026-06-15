#!/usr/bin/env python3
"""Prop-firm sizing reality check for the locked cond@45 config.

Takes the trade-by-trade pnl series (in NQ points, post-SAL) and sweeps a
$/point position size against a $2,000 trailing-drawdown limit:
  - monthly $ income at that size (raw net pnl / months in sample)
  - max historical trailing DD in $ at that size
  - how many times a $2,000 trailing-DD reset would have been triggered
    over the sample, and the implied blows/year

This answers: at what size does the $2k limit get hit ~once over the whole
8+ year sample (vs. how much $/month that size produces), and at what size
does $1k/month require -- and how often the $2k limit would then blow.

Usage:
    python3 scripts/nq_prop_sizing.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import load_1m_ohlcv, load_gvz_daily
import scripts.nq_cond_be45 as C

DD_LIMIT = 2000.0


def count_blows(eq_dollars, limit):
    """Trailing-DD reset count: peak resets every time DD >= limit."""
    blows = 0
    peak = eq_dollars[0]
    for e in eq_dollars:
        if e > peak:
            peak = e
        if peak - e >= limit:
            blows += 1
            peak = e
    return blows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    raw = C.build_ledger(bars, vxn)
    kept = C.apply_sal(raw).sort_values("touched_at")
    pnl_pts = kept["pnl"].values

    span_days = (kept["touched_at"].iloc[-1] - kept["touched_at"].iloc[0]).days
    years = span_days / 365.25
    months = years * 12
    print(f"sample: {len(kept)} trades, {kept['touched_at'].iloc[0].date()} -> "
          f"{kept['touched_at'].iloc[-1].date()}  ({years:.2f} yrs)")
    print(f"net = {pnl_pts.sum():.1f} pts  -> {pnl_pts.sum()/months:.1f} pts/month\n")

    eq_pts = np.cumsum(pnl_pts)
    peak_pts = np.maximum.accumulate(eq_pts)
    max_dd_pts = float((peak_pts - eq_pts).max())

    sizes = [1, 1.5, 2, 2.5, 2.86, 3, 4, 5, 6, 6.45, 7, 8, 10]
    print(f"{'$/pt':>6} {'monthly$':>9} {'maxDD$':>8} {'blows/'+f'{years:.1f}yr':>10} {'blows/yr':>9}")
    for sz in sizes:
        eq_d = eq_pts * sz
        monthly = pnl_pts.sum() * sz / months
        dd_d = max_dd_pts * sz
        blows = count_blows(eq_d, DD_LIMIT)
        print(f"{sz:>6.2f} {monthly:>9.0f} {dd_d:>8.0f} {blows:>10d} {blows/years:>9.2f}")


if __name__ == "__main__":
    main()
