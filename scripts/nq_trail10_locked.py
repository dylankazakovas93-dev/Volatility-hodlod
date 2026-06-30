#!/usr/bin/env python3
"""LOCKED CONFIG: NQ level-fade, cond@45 + 10% trail-after-TP engagement.

Identical entries/risk/BE/SAL machinery as the canonical baseline
(scripts/nq_cond_be45.py), with ONE change: instead of closing flat at
+cap, the stop trails 10% of cap behind the best price reached once price
first reaches +cap. No hard target -- trail runs until stopped out or
session cutoff.

This is the single config (trail_frac=0.10, hard_exit=None) identified in
the nq_trail_pct_grid.py sweep as beating the locked baseline in net, PF,
and every one of the 9 tested years -- not a fresh sweep, just that one
result locked down as a standalone, reproducible script the same way the
baseline was frozen.

Before trusting any printed delta, this script checks that the raw
pre-SAL touch count matches the canonical baseline's (1841) -- i.e. the
trail change only affects exit handling, not which touches qualify as
entries.

Usage:
    python3 scripts/nq_trail10_locked.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import load_1m_ohlcv, load_gvz_daily
from scripts.nq_trail_pct_grid import build_trades, sim_trail, pf, maxdd

TRAIL_FRAC = 0.10
HARD_EXIT = None
CANONICAL_RAW_PRE_SAL = 1841


def run_sal(trades, results):
    rows = [{"sd": t["sd"], "yr": t["yr"], "ta": t["ta"], "p": r[0], "ex": r[1]}
            for t, r in zip(trades, results)]
    df = pd.DataFrame(rows).sort_values("ta")
    kept = []
    for _, day in df.groupby("sd"):
        lost = False
        for _, r in day.iterrows():
            if not lost:
                kept.append(r.to_dict())
                if r["p"] < -0.1 and r["ex"] != "BE":
                    lost = True
    return pd.DataFrame(kept).sort_values("ta").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--export", action="store_true", help="write ledger CSV")
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    trades = build_trades(bars, vxn)
    print(f"raw touches (pre-SAL): {len(trades)}")
    if len(trades) != CANONICAL_RAW_PRE_SAL:
        print(f"*** MISMATCH vs canonical raw_pre_sal={CANONICAL_RAW_PRE_SAL} -- "
              f"entry set has drifted, do not trust deltas below ***\n")
    else:
        print("entry set matches canonical baseline (same touches, risk, BE) -- OK\n")

    results = [sim_trail(t, TRAIL_FRAC, HARD_EXIT) for t in trades]
    kept = run_sal(trades, results)
    years = sorted(kept["yr"].unique())

    print(f"{'Year':6} {'n':>5} {'net':>10} {'PF':>7} {'maxDD':>8} {'TR':>5} {'SL':>5} {'BE':>5} {'cut':>5}")
    for yr in years:
        sub = kept[kept["yr"] == yr]
        p = sub["p"]
        ex = sub["ex"].value_counts()
        print(f"{yr:<6} {len(sub):>5} {p.sum():>10.1f} {pf(p):>7.3f} {maxdd(p):>8.1f} "
              f"{ex.get('TR', 0):>5} {ex.get('SL', 0):>5} {ex.get('BE', 0):>5} "
              f"{ex.get('cutoff', 0) + ex.get('cutoff_eng', 0):>5}")

    p = kept["p"]
    ex = kept["ex"].value_counts()
    print("-" * 60)
    print(f"{'ALL':<6} {len(kept):>5} {p.sum():>10.1f} {pf(p):>7.3f} {maxdd(p):>8.1f} "
          f"{ex.get('TR', 0):>5} {ex.get('SL', 0):>5} {ex.get('BE', 0):>5} "
          f"{ex.get('cutoff', 0) + ex.get('cutoff_eng', 0):>5}")

    if args.export:
        path = "data/canonical/canonical_nq_trail10_locked_ledger.csv"
        kept.rename(columns={"sd": "sess_date", "yr": "year", "ta": "touched_at",
                              "p": "pnl", "ex": "exit"}).to_csv(path, index=False)
        print(f"\nexported: {path}")


if __name__ == "__main__":
    main()
