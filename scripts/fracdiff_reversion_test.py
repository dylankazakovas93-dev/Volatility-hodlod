#!/usr/bin/env python3
"""Reversion-only test: combine μ±k·σ levels with the FracDiff Gate (5m)
z-score confirmation and measure fade-trade outcomes.

Per the user's directive: forget continuation entirely — only test fades
(buy lower-level touches confirmed by z >= +band, sell upper-level touches
confirmed by z <= -band), gated by the FracDiff indicator on the 5-minute
chart (computed on close, per the indicator's own settings).

Reports, for each (entry method) config:
  1. confirmation rates (how many touches actually get a FracDiff signal)
  2. raw 30m/60m fade-reaction stats: avg pts, MFE/MAE percentiles (to inform
     TP/SL choices)
  3. fixed-bracket P&L for a few target/stop combos

Usage:
    python3 scripts/fracdiff_reversion_test.py --ohlcv data/gc_1m/gc_continuous_1m.csv \
        --d 0.45 --N 100 --zlen 100 --band 1.0 --entry-method instant
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import GC_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.fracdiff import FracDiffParams, compute_gate, resample_ohlcv
from volgen.fracdiff_reversion import (
    EntryConfig,
    find_confirmed_touches,
    measure_fade_reactions,
    run_fade_bracket_test,
    summarize_confirmation_rates,
)


def _pct(s: pd.Series, q) -> float:
    return float(s.quantile(q)) if len(s) else float("nan")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ohlcv", required=True)
    parser.add_argument("--gvz", default="data/gvz_daily.csv")
    parser.add_argument("--d", type=float, default=0.45)
    parser.add_argument("--N", type=int, default=100)
    parser.add_argument("--zlen", type=int, default=100)
    parser.add_argument("--band", type=float, default=1.0)
    parser.add_argument("--fast", action="store_true", default=True)
    parser.add_argument("--price-col", default="close")
    parser.add_argument("--entry-method", choices=["instant", "lookback", "fired_returned"], default="instant")
    parser.add_argument("--lookback-minutes", type=int, default=15)
    parser.add_argument("--horizons", type=int, nargs="+", default=[30, 60])
    parser.add_argument("--brackets", type=str, nargs="+", default=["10:10", "15:10", "10:15", "20:15"],
                        help="target:stop pairs in points, e.g. 10:10 15:10")
    parser.add_argument("--max-bars", type=int, default=240)
    parser.add_argument("--out-touches", default=None)
    parser.add_argument("--out-reactions", default=None)
    args = parser.parse_args()

    print(f"loading 1m OHLCV from {args.ohlcv} ...")
    ohlcv = load_1m_ohlcv(args.ohlcv)
    gvz = load_gvz_daily(args.gvz)

    print("generating levels (mu +/- k*sigma, GC params) ...")
    levels = generate_levels(ohlcv, gvz, params=GC_PARAMS)
    print(f"  {len(levels)} sessions -> {len(levels) * 2} levels")

    print("resampling to 5-minute bars and computing FracDiff gate ...")
    ohlcv5 = resample_ohlcv(ohlcv, "5min")
    fd_params = FracDiffParams(d=args.d, N=args.N, zlen=args.zlen, band=args.band, fast=args.fast, price_col=args.price_col)
    gate = compute_gate(ohlcv5, fd_params)
    print(f"  {len(ohlcv5)} 5m bars; long_ok rate {gate['long_ok'].mean():.3f}, short_ok rate {gate['short_ok'].mean():.3f}")

    cfg = EntryConfig(method=args.entry_method, lookback_minutes=args.lookback_minutes)
    print(f"\nfinding level touches + checking FracDiff confirmation (method={cfg.method}, lookback={cfg.lookback_minutes}m) ...")
    touches = find_confirmed_touches(ohlcv, levels, gate, cfg)
    if args.out_touches:
        os.makedirs(os.path.dirname(args.out_touches) or ".", exist_ok=True)
        touches.to_csv(args.out_touches, index=False)

    print()
    print(f"=== confirmation rates: d={args.d} N={args.N} zlen={args.zlen} band={args.band} method={cfg.method} ===")
    print(summarize_confirmation_rates(touches).to_string(index=False))

    n_confirmed = int(touches["confirmed"].sum())
    if n_confirmed == 0:
        print("\nNo confirmed touches under this config — nothing further to report.")
        return

    print(f"\nmeasuring fade-reaction excursions on {n_confirmed} confirmed touches (horizons={args.horizons}) ...")
    reactions = measure_fade_reactions(ohlcv, touches, horizons_minutes=tuple(args.horizons))
    if args.out_reactions:
        os.makedirs(os.path.dirname(args.out_reactions) or ".", exist_ok=True)
        reactions.to_csv(args.out_reactions, index=False)

    print()
    print("=== raw fade-reaction stats (signed pts in the fade's favor; MFE/MAE = best/worst excursion) ===")
    for side in ("upper", "lower"):
        sub = reactions[reactions["side"] == side]
        if sub.empty:
            print(f"  {side}: no confirmed touches")
            continue
        print(f"  -- {side} (n={len(sub)}) --")
        for h in args.horizons:
            pts, mfe, mae, dd = sub[f"pts_{h}m"], sub[f"mfe_{h}m"], sub[f"mae_{h}m"], sub[f"max_dd_{h}m"]
            print(
                f"    {h:>3}m: pts mean={pts.mean():+6.2f} median={pts.median():+6.2f} | "
                f"win%(>0)={100*(pts > 0).mean():5.1f}% | "
                f"MFE p50/p75/p90={_pct(mfe,.5):5.2f}/{_pct(mfe,.75):5.2f}/{_pct(mfe,.9):5.2f} | "
                f"MAE(dd) p50/p75/p90={_pct(dd,.5):5.2f}/{_pct(dd,.75):5.2f}/{_pct(dd,.9):5.2f}"
            )

    print()
    print("=== fixed-bracket fade P&L (reusing the raw-edge bracket simulator, FADE direction only) ===")
    for spec in args.brackets:
        tgt_s, stop_s = spec.split(":")
        target_pts, stop_pts = float(tgt_s), float(stop_s)
        trades = run_fade_bracket_test(ohlcv, touches, target_pts=target_pts, stop_pts=stop_pts, max_bars=args.max_bars)
        if trades.empty:
            print(f"  target={target_pts}/stop={stop_pts}: no trades")
            continue
        for side in ("upper", "lower", "ALL"):
            sub = trades if side == "ALL" else trades[trades["side"] == side]
            if sub.empty:
                continue
            win_rate = (sub["result"] == "target").mean()
            print(
                f"  target={target_pts:>4}/stop={stop_pts:>4}  side={side:<5} n={len(sub):>4}  "
                f"win%={100*win_rate:5.1f}  avg_pts={sub['pts'].mean():+6.2f}  total_pts={sub['pts'].sum():+8.1f}"
            )


if __name__ == "__main__":
    main()
