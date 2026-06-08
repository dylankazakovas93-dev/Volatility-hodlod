#!/usr/bin/env python3
"""Parameter sweep for the FracDiff-gated reversion (fade-only) signal: combine
the mu+/-k*sigma levels with the FracDiff Gate (5m) z-score, varying integration
order (d), lag truncation (N), band width, and entry-confirmation method/lookback.

Per the user's directive: continuation is off the table — only fade trades,
confirmed by FracDiff in "trend sense" (lower-level fade needs z >= +band,
upper-level fade needs z <= -band). This loads the data ONCE and reuses levels
across the whole grid (only the FracDiff gate depends on d/N/zlen/band).

Outputs one row per (d, N, band, entry_method, lookback) combo: confirmation
counts/rates plus 60m fade-reaction stats (avg pts, win%, MAE/drawdown) so we
can see at a glance whether ANY corner of this space produces a usable n and a
real-looking edge, or whether the joint (touch AND gate-confirm) event is just
too rare to say anything.

Usage:
    python3 scripts/fracdiff_reversion_sweep.py --ohlcv data/gc_1m/gc_continuous_1m.csv --out out/fracdiff_sweep.csv
"""
import argparse
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import GC_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.fracdiff import FracDiffParams, compute_gate, resample_ohlcv
from volgen.fracdiff_reversion import EntryConfig, find_confirmed_touches, measure_fade_reactions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ohlcv", required=True)
    parser.add_argument("--gvz", default="data/gvz_daily.csv")
    parser.add_argument("--d", type=float, nargs="+", default=[0.3, 0.45, 0.6])
    parser.add_argument("--N", type=int, nargs="+", default=[50, 100])
    parser.add_argument("--zlen", type=int, default=100)
    parser.add_argument("--band", type=float, nargs="+", default=[0.5, 0.75, 1.0, 1.5])
    parser.add_argument("--methods", nargs="+", default=["instant", "lookback15", "lookback30", "fired_returned15"])
    parser.add_argument("--horizon", type=int, default=60)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    print(f"loading 1m OHLCV from {args.ohlcv} ...")
    ohlcv = load_1m_ohlcv(args.ohlcv)
    gvz = load_gvz_daily(args.gvz)
    print("generating levels ...")
    levels = generate_levels(ohlcv, gvz, params=GC_PARAMS)
    print(f"  {len(levels)} sessions -> {len(levels) * 2} levels (n_touches will be <= this per side)")
    print("resampling to 5m ...")
    ohlcv5 = resample_ohlcv(ohlcv, "5min")

    method_specs = {
        "instant": EntryConfig(method="instant"),
        "lookback15": EntryConfig(method="lookback", lookback_minutes=15),
        "lookback30": EntryConfig(method="lookback", lookback_minutes=30),
        "lookback60": EntryConfig(method="lookback", lookback_minutes=60),
        "fired_returned15": EntryConfig(method="fired_returned", lookback_minutes=15),
        "fired_returned30": EntryConfig(method="fired_returned", lookback_minutes=30),
    }
    cfgs = [(name, method_specs[name]) for name in args.methods]

    rows = []
    grid = list(product(args.d, args.N, args.band))
    print(f"\nsweeping {len(grid)} (d, N, band) combos x {len(cfgs)} entry configs = {len(grid) * len(cfgs)} runs ...\n")
    for gi, (d, N, band) in enumerate(grid, start=1):
        fd_params = FracDiffParams(d=d, N=N, zlen=args.zlen, band=band, fast=True)
        gate = compute_gate(ohlcv5, fd_params)
        print(f"[{gi}/{len(grid)}] d={d} N={N} band={band}  (long_ok={gate['long_ok'].mean():.3f} short_ok={gate['short_ok'].mean():.3f})")
        for method_name, cfg in cfgs:
            touches = find_confirmed_touches(ohlcv, levels, gate, cfg)
            confirmed = touches[touches["confirmed"]]
            if confirmed.empty:
                rows.append(dict(d=d, N=N, band=band, method=method_name,
                                 side="ALL", n=0, win_rate=np.nan, avg_pts=np.nan,
                                 median_pts=np.nan, total_pts=np.nan, avg_dd=np.nan, p90_dd=np.nan))
                continue
            reactions = measure_fade_reactions(ohlcv, touches, horizons_minutes=(args.horizon,))
            pcol, ddcol = f"pts_{args.horizon}m", f"max_dd_{args.horizon}m"
            for side in ("upper", "lower", "ALL"):
                sub = reactions if side == "ALL" else reactions[reactions["side"] == side]
                if sub.empty:
                    continue
                rows.append(dict(
                    d=d, N=N, band=band, method=method_name, side=side,
                    n=len(sub),
                    win_rate=round(float((sub[pcol] > 0).mean()), 3),
                    avg_pts=round(float(sub[pcol].mean()), 3),
                    median_pts=round(float(sub[pcol].median()), 3),
                    total_pts=round(float(sub[pcol].sum()), 1),
                    avg_dd=round(float(sub[ddcol].mean()), 3),
                    p90_dd=round(float(sub[ddcol].quantile(0.9)), 3),
                ))

    out = pd.DataFrame(rows)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        out.to_csv(args.out, index=False)
        print(f"\nwrote {len(out)} rows -> {args.out}")

    print()
    print(f"=== sweep summary @ {args.horizon}m horizon (sorted by n, ALL-side rows only) ===")
    all_side = out[out["side"] == "ALL"].sort_values("n", ascending=False)
    print(all_side.head(40).to_string(index=False))

    print()
    print("=== combos with n >= 30 (only these have any chance of being meaningful) ===")
    usable = out[(out["side"] == "ALL") & (out["n"] >= 30)].sort_values("avg_pts", ascending=False)
    if usable.empty:
        print("  NONE — every (d, N, band, method) combo produces fewer than 30 confirmed+touched fade setups.")
        print("  This itself is the headline finding: touch AND FracDiff-trend-sense-confirm is a RARE joint event.")
    else:
        print(usable.to_string(index=False))


if __name__ == "__main__":
    main()
