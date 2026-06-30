#!/usr/bin/env python3
"""LOCKED CANDIDATE: 19:00 ET anchor, sigma_mult=1.00, offset=0, ib_minutes=90.

Top result from the scripts/nq_anchor1900_grid.py sweep (75 configs at the
19:00 anchor). Same downstream system as the 9:30 baseline (cond@45 risk,
BE@45, SAL, entry window 19:00-11:00 ET, session cutoff 15:00 ET) -- only
the level-placement inputs change: anchor time 19:00 instead of 09:30,
sigma_mult=1.00 instead of 1.25, offset=0 instead of the fixed 15.75pt,
ib_minutes=90 instead of 60.

Reports year-by-year: n, net, PF, tWR (TP/(TP+SL)), true/outright win
rate (pnl>0 / n), and annualized Sharpe from the daily net-pnl series
(mean/std * sqrt(252)).

Usage:
    python3 scripts/nq_anchor1900_best_locked.py \
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
from volgen.levels import InstrumentParams, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B
from scripts.nq_cond_be45 import simulate_cond_be, apply_sal, profit_factor, max_drawdown

RTH_START, RTH_END = "19:00", "01:30"
PARAMS = InstrumentParams(sigma_mult=1.00, offset_pct=0.0, ib_minutes=90, fixed_offset=0.0)
TRADING_DAYS = 252


def build_ledger(bars, vxn, params):
    levels = generate_levels(bars, vxn, params=params, rth_start=RTH_START, rth_end=RTH_END)
    ranges = B.bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    records = []
    for i, lv in enumerate(lvls):
        expiry = lvls[i + B.LINE_DAYS].created_at if i + B.LINE_DAYS < len(lvls) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col)
            ft = _first_touch(search, lvl)
            if ft is None or not B.entry_allowed(ft):
                continue
            anchor = B.prev_completed_range(ranges, ft)
            if anchor is None:
                continue
            co = B.session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue
            cap = min(1.5 * anchor, B.SL_CAP)
            sign = -1.0 if side == "upper" else 1.0
            pnl, ex = simulate_cond_be(path, lvl, sign, cap)
            records.append({
                "sess_date": B.session_date(ft), "year": pd.Timestamp(B.session_date(ft)).year,
                "side": side, "touched_at": ft, "level": lvl,
                "anchor": anchor, "cap": cap, "pnl": pnl, "exit": ex,
            })
    return pd.DataFrame(records)


def ann_sharpe(daily_pnl):
    if daily_pnl.std(ddof=1) == 0 or len(daily_pnl) < 2:
        return float("nan")
    return float(daily_pnl.mean() / daily_pnl.std(ddof=1) * np.sqrt(TRADING_DAYS))


def stats_block(df):
    p = df["pnl"]
    ex = df["exit"].value_counts()
    tp, sl = ex.get("TP", 0), ex.get("SL", 0)
    twr = tp / (tp + sl) * 100 if (tp + sl) > 0 else float("nan")
    true_wr = (p > 0.1).sum() / len(df) * 100 if len(df) else float("nan")
    daily = df.groupby("sess_date")["pnl"].sum()
    return {
        "n": len(df), "net": float(p.sum()), "PF": profit_factor(p), "maxDD": max_drawdown(p),
        "TP": int(tp), "SL": int(sl), "BE": int(ex.get("BE", 0)), "cut": int(ex.get("cutoff", 0)),
        "tWR": twr, "true_WR": true_wr, "sharpe": ann_sharpe(daily),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    raw = build_ledger(bars, vxn, PARAMS)
    kept = apply_sal(raw)
    print(f"raw touches (pre-SAL): {len(raw)}   kept (post-SAL): {len(kept)}\n")

    print(f"{'Year':>6} {'n':>5} {'net':>9} {'PF':>7} {'maxDD':>8} {'tWR':>6} {'trueWR':>7} {'Sharpe':>7} "
          f"{'TP':>4} {'SL':>4} {'BE':>4} {'cut':>4}")
    for yr in sorted(kept["year"].unique()):
        s = stats_block(kept[kept["year"] == yr])
        print(f"{yr:>6} {s['n']:>5} {s['net']:>9.0f} {s['PF']:>7.3f} {s['maxDD']:>8.0f} "
              f"{s['tWR']:>5.1f}% {s['true_WR']:>6.1f}% {s['sharpe']:>7.2f} "
              f"{s['TP']:>4} {s['SL']:>4} {s['BE']:>4} {s['cut']:>4}")

    s = stats_block(kept)
    print("-" * 88)
    print(f"{'ALL':>6} {s['n']:>5} {s['net']:>9.0f} {s['PF']:>7.3f} {s['maxDD']:>8.0f} "
          f"{s['tWR']:>5.1f}% {s['true_WR']:>6.1f}% {s['sharpe']:>7.2f} "
          f"{s['TP']:>4} {s['SL']:>4} {s['BE']:>4} {s['cut']:>4}")


if __name__ == "__main__":
    main()
