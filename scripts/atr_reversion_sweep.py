#!/usr/bin/env python3
"""ATR-scaled reversion (fade-only) sweep on the RAW, unfiltered mu+/-k*sigma
levels — per the user's pivot away from FracDiff filtering and back to "find
the common denominator of which touches actually produce clean reversions."

Sizes TP/SL off the prior session's ATR(14) instead of fixed point values:
    target_pts = atr_pct * ATR(prior session)
    stop_pts   = target_pts / rr            (rr = reward:risk multiple)

Sweeps atr_pct x rr, reports aggregate + year-by-year stats (win rate, avg/total
pts, drawdown) so a single hot year can't silently carry the average. No
slippage/commission modeled (per the user, those don't exist in this sandbox).

Usage:
    python3 scripts/atr_reversion_sweep.py --ohlcv data/gc_1m/gc_continuous_1m.csv \
        --atr-pct 0.10 0.15 0.20 0.25 0.40 --rr 1 2 3 4 --out out/atr_fade_sweep.csv
"""
import argparse
import os
import sys
from itertools import product

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import GC_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.atr import build_atr_lookup
from volgen.atr_reversion import run_atr_fade_test, summarize_atr_fade, summarize_by_year


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ohlcv", required=True)
    parser.add_argument("--gvz", default="data/gvz_daily.csv")
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--atr-pct", type=float, nargs="+", default=[0.10, 0.15, 0.20, 0.25, 0.40])
    parser.add_argument("--rr", type=float, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--max-bars", type=int, default=240)
    parser.add_argument("--out", default=None)
    parser.add_argument("--out-trades-best", default=None, help="dump per-trade rows for the best (atr_pct,rr) combo")
    args = parser.parse_args()

    print(f"loading 1m OHLCV from {args.ohlcv} ...")
    ohlcv = load_1m_ohlcv(args.ohlcv)
    gvz = load_gvz_daily(args.gvz)
    print("generating levels (raw, unfiltered mu+/-k*sigma) ...")
    levels = generate_levels(ohlcv, gvz, params=GC_PARAMS)
    print(f"  {len(levels)} sessions -> {len(levels) * 2} levels")
    print(f"building daily ATR({args.atr_period}) lookup ...")
    atr_lookup = build_atr_lookup(ohlcv, period=args.atr_period)
    print(f"  ATR series: {len(atr_lookup)} sessions, range {atr_lookup.min():.2f}-{atr_lookup.max():.2f} pts, "
          f"median {atr_lookup.median():.2f}")

    grid = list(product(args.atr_pct, args.rr))
    print(f"\nsweeping {len(grid)} (atr_pct, rr) combos -- fade BOTH sides, no slippage/fees ...\n")

    summary_rows = []
    yearly_rows = []
    cache = {}
    for i, (atr_pct, rr) in enumerate(grid, start=1):
        trades = run_atr_fade_test(ohlcv, levels, atr_lookup, atr_pct=atr_pct, rr=rr, max_bars=args.max_bars)
        cache[(atr_pct, rr)] = trades
        if trades.empty:
            print(f"[{i}/{len(grid)}] atr_pct={atr_pct:.2f} rr={rr}: no trades")
            continue
        summ = summarize_atr_fade(trades)
        summ.insert(0, "rr", rr)
        summ.insert(0, "atr_pct", atr_pct)
        summary_rows.append(summ)

        yearly = summarize_by_year(trades)
        yearly.insert(0, "rr", rr)
        yearly.insert(0, "atr_pct", atr_pct)
        yearly_rows.append(yearly)

        all_row = summ[summ["side"] == "ALL"].iloc[0]
        print(
            f"[{i}/{len(grid)}] atr_pct={atr_pct:.2f} rr={rr:.0f}  "
            f"tgt~{all_row['avg_target_pts']:.1f}/sl~{all_row['avg_stop_pts']:.1f}pts  "
            f"n={int(all_row['n']):>4}  win%={100*all_row['win_rate']:5.1f}  "
            f"avg_pts={all_row['avg_pts']:+6.2f}  total={all_row['total_pts']:+9.1f}  "
            f"avg_dd={all_row['avg_dd']:5.2f}  p90_dd={all_row['p90_dd']:6.2f}"
        )

    summary = pd.concat(summary_rows, ignore_index=True) if summary_rows else pd.DataFrame()
    yearly = pd.concat(yearly_rows, ignore_index=True) if yearly_rows else pd.DataFrame()
    if args.out and not summary.empty:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        summary.to_csv(args.out, index=False)
        yearly.to_csv(args.out.replace(".csv", "_by_year.csv"), index=False)
        print(f"\nwrote {len(summary)} summary rows -> {args.out}")
        print(f"wrote {len(yearly)} yearly rows -> {args.out.replace('.csv', '_by_year.csv')}")

    if summary.empty:
        return

    all_summary = summary[summary["side"] == "ALL"].sort_values("total_pts", ascending=False)
    print()
    print("=== ranked by total pts (ALL sides combined, ties broken by avg_pts) ===")
    print(all_summary[["atr_pct", "rr", "n", "win_rate", "avg_pts", "total_pts", "avg_dd", "p90_dd",
                       "avg_target_pts", "avg_stop_pts"]].to_string(index=False))

    print()
    print("=== year-by-year for the TOP-ranked combo (robustness check: does one year carry it?) ===")
    if not all_summary.empty:
        best_atr_pct, best_rr = all_summary.iloc[0][["atr_pct", "rr"]]
        ybest = yearly[(yearly["atr_pct"] == best_atr_pct) & (yearly["rr"] == best_rr) & (yearly["side"] == "ALL")]
        print(f"  best combo: atr_pct={best_atr_pct} rr={best_rr}")
        print(ybest[["year", "n", "win_rate", "avg_pts", "total_pts", "avg_dd"]].to_string(index=False))

        if args.out_trades_best:
            os.makedirs(os.path.dirname(args.out_trades_best) or ".", exist_ok=True)
            cache[(best_atr_pct, best_rr)].to_csv(args.out_trades_best, index=False)
            print(f"  wrote per-trade rows for the best combo -> {args.out_trades_best}")

    print()
    print("=== side breakdown for the top 5 combos ===")
    for _, r in all_summary.head(5).iterrows():
        sub = summary[(summary["atr_pct"] == r["atr_pct"]) & (summary["rr"] == r["rr"]) & (summary["side"] != "ALL")]
        print(f"  atr_pct={r['atr_pct']} rr={r['rr']}:")
        print("    " + sub[["side", "n", "win_rate", "avg_pts", "total_pts", "avg_dd"]].to_string(index=False).replace("\n", "\n    "))


if __name__ == "__main__":
    main()
