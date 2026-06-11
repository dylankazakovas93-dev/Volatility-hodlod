#!/usr/bin/env python3
"""Ad-hoc test: same locked config as nq_oos_2019.py but with the 200-pt
TP/SL cap REMOVED, i.e. cap = 1.5 x previous completed 1h range, uncapped.

Everything else (entry window, SAL, lineDays, level math) is identical to
the locked tp_sl_cap200 config.

Usage:
    python3 scripts/nq_uncapped_test.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.nq_oos_2019 as base  # noqa: E402


def build_ledger_uncapped(bars, vxn):
    all_levels = base.generate_levels(bars, vxn, params=base.NQ_PARAMS)
    ranges = base.bar_ranges(bars)
    lvl_list = list(all_levels.itertuples(index=False))
    records = []
    for i, lv in enumerate(lvl_list):
        expiry = lvl_list[i + base.LINE_DAYS].created_at if i + base.LINE_DAYS < len(lvl_list) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col)
            ft = base._first_touch(search, lvl)
            if ft is None or not base.entry_allowed(ft):
                continue
            anchor = base.prev_completed_range(ranges, ft)
            if anchor is None:
                continue
            co = base.session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue
            cap = 1.5 * anchor  # NO 200-pt cap
            sign = -1.0 if side == "upper" else 1.0
            ps, es = base.simulate_standard(path, lvl, sign, cap, cap)
            records.append({
                "sess_date": base.session_date(ft),
                "year": pd.Timestamp(base.session_date(ft)).year,
                "side": side,
                "touched_at": ft,
                "level": lvl,
                "anchor": anchor,
                "cap": cap,
                "pnl_standard": ps, "exit_standard": es,
            })
    return pd.DataFrame(records)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    print("Loading data …")
    bars = base.load_1m_ohlcv(args.bars)
    vxn = base.load_gvz_daily(args.vxn)
    print(f"  bars {bars.index[0]} -> {bars.index[-1]}  ({len(bars):,})")

    print("Building raw ledger (lineDays=20, UNCAPPED tp=sl=1.5xanchor) …")
    raw = build_ledger_uncapped(bars, vxn)
    all_years = sorted(raw["year"].unique())
    print(f"  raw touches (before SAL): {len(raw)}   years: {all_years}")
    print(f"  cap stats: min={raw['cap'].min():.1f}  median={raw['cap'].median():.1f}  "
          f"max={raw['cap'].max():.1f}  mean={raw['cap'].mean():.1f}")
    print(f"  trades with cap > 200: {(raw['cap'] > 200).sum()}  "
          f"(of which > 700: {(raw['cap'] > 700).sum()}, max-anchor day cap={raw['cap'].max():.1f})")

    std = base.sal_standard(raw, "pnl_standard")

    base.year_table(std, "pnl_standard", "exit_standard",
                     "STANDARD UNCAPPED  (TP=SL=1.5xanchor, no 200 cap, SAL after first loss)",
                     all_years)
    print()


if __name__ == "__main__":
    main()
