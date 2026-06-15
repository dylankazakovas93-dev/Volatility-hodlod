#!/usr/bin/env python3
"""MAE ("breathing room") analysis for the locked cond@45 config.

For every trade taken under the locked tp_sl_cap200 + cond-BE45 rules, track
the maximum adverse excursion (MAE) -- how far the trade goes underwater,
in points, before it resolves (TP / SL / BE / cutoff). Reported both in raw
points and as a fraction of that trade's `cap` (= min(1.5 x prev completed
1h range, 200), the SL/TP distance), broken out by year for:
  - TP-only trades  (how much room a winner needs before it gets there)
  - ALL trades      (general per-trade drawdown profile)

Usage:
    python3 scripts/nq_mae_analysis.py \
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
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B

BE_BARS = 45


def simulate_cond_be_mae(path, entry, sign, cap, be_bars=BE_BARS):
    """Same as nq_cond_be45.simulate_cond_be but also returns MAE (points).

    MAE = max(adverse excursion) over all bars up to and including the exit
    bar, where adverse excursion on a bar is (entry - low) for longs or
    (high - entry) for shorts.
    """
    target = entry + sign * cap
    orig_stop = entry - sign * cap
    hi, lo, op, cl = (path["high"].values, path["low"].values,
                      path["open"].values, path["close"].values)
    armed = checked = False
    mae = 0.0
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        adverse = (entry - l) if sign > 0 else (h - entry)
        if adverse > mae:
            mae = adverse
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry) if sign > 0 else (o <= entry)
            stop = entry if armed else orig_stop
        if sign > 0:
            if l <= stop:
                return sign * (stop - entry), ("BE" if (i >= be_bars and armed) else "SL"), mae
            if h >= target:
                return cap, "TP", mae
        else:
            if h >= stop:
                return sign * (stop - entry), ("BE" if (i >= be_bars and armed) else "SL"), mae
            if l <= target:
                return cap, "TP", mae
    return sign * (float(cl[-1]) - entry), "cutoff", mae


def build_ledger(bars, vxn):
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
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
            pnl, ex, mae = simulate_cond_be_mae(path, lvl, sign, cap)
            records.append({
                "sess_date": B.session_date(ft),
                "year": pd.Timestamp(B.session_date(ft)).year,
                "side": side, "touched_at": ft, "level": lvl,
                "anchor": anchor, "cap": cap, "pnl": pnl, "exit": ex,
                "mae": mae, "mae_frac": mae / cap,
            })
    return pd.DataFrame(records)


def apply_sal(df):
    """SAL: first real loss (pnl<0 and exit!=BE) stops the rest of the session."""
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row["pnl"] < -0.1 and row["exit"] != "BE":
                    lost = True
    return pd.DataFrame(kept).sort_values("touched_at").reset_index(drop=True)


def summarize(df, label):
    rows = []
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]
        m, f = sub["mae"], sub["mae_frac"]
        rows.append({
            "year": yr, "n": len(sub),
            "mean": m.mean(), "median": m.median(), "p75": m.quantile(.75),
            "p90": m.quantile(.90), "max": m.max(),
            "mean_f": f.mean(), "median_f": f.median(), "p90_f": f.quantile(.90),
        })
    m, f = df["mae"], df["mae_frac"]
    rows.append({
        "year": "ALL", "n": len(df),
        "mean": m.mean(), "median": m.median(), "p75": m.quantile(.75),
        "p90": m.quantile(.90), "max": m.max(),
        "mean_f": f.mean(), "median_f": f.median(), "p90_f": f.quantile(.90),
    })
    print(f"\n{label}")
    print(f"{'Year':>6} {'n':>5} {'mean':>7} {'med':>7} {'p75':>7} {'p90':>7} {'max':>7}"
          f"   {'mean/cap':>8} {'med/cap':>8} {'p90/cap':>8}")
    for r in rows:
        print(f"{r['year']:>6} {r['n']:>5} {r['mean']:>7.1f} {r['median']:>7.1f} "
              f"{r['p75']:>7.1f} {r['p90']:>7.1f} {r['max']:>7.1f}"
              f"   {r['mean_f']:>8.1%} {r['median_f']:>8.1%} {r['p90_f']:>8.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    raw = build_ledger(bars, vxn)
    kept = apply_sal(raw)

    print(f"raw touches (pre-SAL): {len(raw)}   kept (post-SAL): {len(kept)}")

    summarize(kept, "ALL TRADES -- MAE before resolution (points, and as fraction of cap)")

    tp = kept[kept["exit"] == "TP"]
    summarize(tp, f"TP-ONLY TRADES (n={len(tp)}) -- MAE before hitting TP (points, and as fraction of cap)")


if __name__ == "__main__":
    main()
