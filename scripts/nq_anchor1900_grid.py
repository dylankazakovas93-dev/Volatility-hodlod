#!/usr/bin/env python3
"""Sweep sigma_mult x fixed_offset x ib_minutes at the 19:00 IB anchor.

The 19:00 anchor test (nq_ib_anchor_test.py) found net +4595 over the
9:30 baseline but at lower PF (1.500 vs 1.678) and worse maxDD, using
the 9:30-calibrated constants (sigma_mult=1.25, fixed_offset=15.75pt,
ib_minutes=60) unchanged. Those constants were tuned for the cash
session's vol profile, not the 19:00 evening session, so this re-tunes
them at the 19:00 anchor specifically.

Same downstream system throughout (cond@45, BE45, SAL, entry window,
session cutoff) -- only the level-placement inputs change.

Usage:
    python3 scripts/nq_anchor1900_grid.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import InstrumentParams, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B
from scripts.nq_cond_be45 import simulate_cond_be, apply_sal, profit_factor, max_drawdown

RTH_START, RTH_END = "19:00", "01:30"

SIGMA_MULTS = [0.75, 1.0, 1.25, 1.5, 1.75]
OFFSETS = [0.0, 10.0, 15.75, 25.0, 40.0]
IB_MINUTES = [30, 60, 90]


def build_ledger(bars, vxn, params):
    levels = generate_levels(bars, vxn, params=params, rth_start=RTH_START, rth_end=RTH_END)
    if levels.empty:
        return pd.DataFrame()
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    print(f"19:00 anchor grid: {len(SIGMA_MULTS)} sigma_mult x {len(OFFSETS)} offset x "
          f"{len(IB_MINUTES)} ib_minutes = {len(SIGMA_MULTS)*len(OFFSETS)*len(IB_MINUTES)} configs\n")
    print(f"{'sigma':>6} {'offset':>7} {'ib':>4} {'n':>5} {'net':>9} {'PF':>7} {'maxDD':>8} "
          f"{'TP':>5} {'SL':>5} {'BE':>5} {'cut':>5}")

    results = []
    for sm in SIGMA_MULTS:
        for off in OFFSETS:
            for ib in IB_MINUTES:
                params = InstrumentParams(sigma_mult=sm, offset_pct=0.0, ib_minutes=ib, fixed_offset=off)
                raw = build_ledger(bars, vxn, params)
                if raw.empty:
                    continue
                kept = apply_sal(raw)
                if kept.empty:
                    continue
                p = kept["pnl"]
                ex = kept["exit"].value_counts()
                net, pf, dd = float(p.sum()), profit_factor(p), max_drawdown(p)
                results.append({"sigma": sm, "offset": off, "ib": ib, "n": len(kept),
                                 "net": net, "PF": pf, "maxDD": dd})
                print(f"{sm:>6.2f} {off:>7.2f} {ib:>4} {len(kept):>5} {net:>9.0f} {pf:>7.3f} {dd:>8.0f} "
                      f"{ex.get('TP',0):>5} {ex.get('SL',0):>5} {ex.get('BE',0):>5} {ex.get('cutoff',0):>5}")

    rdf = pd.DataFrame(results)
    print("\n--- TOP 10 by net ---")
    for _, r in rdf.nlargest(10, "net").iterrows():
        print(f"  sigma={r['sigma']:.2f} offset={r['offset']:.2f} ib={int(r['ib'])}  "
              f"n={int(r['n'])} net={r['net']:.0f} PF={r['PF']:.3f} maxDD={r['maxDD']:.0f}")

    print("\n--- TOP 10 by PF ---")
    for _, r in rdf.nlargest(10, "PF").iterrows():
        print(f"  sigma={r['sigma']:.2f} offset={r['offset']:.2f} ib={int(r['ib'])}  "
              f"n={int(r['n'])} net={r['net']:.0f} PF={r['PF']:.3f} maxDD={r['maxDD']:.0f}")


if __name__ == "__main__":
    main()
