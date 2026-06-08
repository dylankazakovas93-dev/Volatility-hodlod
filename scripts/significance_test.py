#!/usr/bin/env python3
"""Is the indicator's specific level placement informative, or would any
similarly-sized offset from the day's open show the same pattern (because GC
just trended hard over this window)?

Permutation test: shuffle each session's (level - cash_open) offset across
sessions (preserving the empirical "how far levels sit from the open"
distribution and each session's real timing/context), recompute touches +
net-bias stats on these "fake" levels many times, and compare the real
result's position in that null distribution (empirical p-value).

Usage:
    python3 scripts/significance_test.py --ohlcv data/gc_1m/gc_continuous_1m.csv --n-perm 100
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import GC_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.significance import empirical_p_value, run_permutation_test


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ohlcv", required=True)
    parser.add_argument("--gvz", default="data/gvz_daily.csv")
    parser.add_argument("--horizon", type=int, default=60)
    parser.add_argument("--n-perm", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-null", default=None, help="optional CSV to dump the null distribution")
    args = parser.parse_args()

    print("loading data and generating real levels ...")
    ohlcv = load_1m_ohlcv(args.ohlcv)
    gvz = load_gvz_daily(args.gvz)
    levels = generate_levels(ohlcv, gvz, params=GC_PARAMS)
    print(f"  {len(levels)} sessions -> {len(levels) * 2} levels\n")

    print(f"running permutation test (horizon={args.horizon}m, n_perm={args.n_perm}) ...")
    real, null = run_permutation_test(ohlcv, levels, horizon=args.horizon, n_perm=args.n_perm, seed=args.seed)

    if args.out_null:
        os.makedirs(os.path.dirname(args.out_null) or ".", exist_ok=True)
        null.to_csv(args.out_null, index=False)
        print(f"wrote null distribution -> {args.out_null}")

    print()
    print(f"=== results @ {args.horizon}m horizon (net_bias = reaction - continuation; >0 favors reversal) ===")
    print(f"{'metric':<32} {'real':>10}   {'null mean':>10} {'null std':>10}   {'p-value':>8}")
    for side in ("upper", "lower"):
        for stat in ("mean_net_bias", "median_net_bias", "pct_reaction_wins"):
            key = f"{side}_{stat}"
            real_val = real[key]
            null_vals = null[key].to_numpy()
            p = empirical_p_value(real_val, null_vals)
            print(
                f"{key:<32} {real_val:>10.4f}   {null_vals.mean():>10.4f} {null_vals.std():>10.4f}   {p:>8.3f}"
            )
    print()
    print("p-value here = fraction of random-offset trials that produced a result")
    print("at least as extreme as the real one. Small p (e.g. < 0.05) => the real")
    print("levels' specific placement looks meaningfully different from a random")
    print("offset of similar size. Large p => indistinguishable from luck/regime.")


if __name__ == "__main__":
    main()
