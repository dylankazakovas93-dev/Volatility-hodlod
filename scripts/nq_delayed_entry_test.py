#!/usr/bin/env python3
"""Delayed-entry test: enter N bars after the first touch instead of at the
touch price, keeping cap (and therefore TP/SL distance) identical to the
immediate-entry baseline.

Hypothesis: if the level has predictive value (price keeps drifting in the
fade direction right after touch), a small delay should hand you a better
entry price "for free" -- same risk (cap unchanged, computed from the
anchor at touch time as before), but better expected fill -> higher PF.

Everything else (BE@45, SAL, lineDays, level math, entry window) is
unchanged from the locked cond@45 config.

Usage:
    python3 scripts/nq_delayed_entry_test.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B
from scripts.nq_cond_be45 import simulate_cond_be

BE_BARS = 45


def build_ledger(bars, vxn, delay_bars):
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
            if len(path) <= delay_bars:
                continue
            entry = lvl if delay_bars == 0 else float(path["open"].values[delay_bars])
            sim_path = path.iloc[delay_bars:]
            cap = min(1.5 * anchor, B.SL_CAP)
            sign = -1.0 if side == "upper" else 1.0
            pnl, ex = simulate_cond_be(sim_path, entry, sign, cap, be_bars=BE_BARS)
            records.append({
                "sess_date": B.session_date(ft),
                "year": pd.Timestamp(B.session_date(ft)).year,
                "side": side, "touched_at": ft, "level": lvl, "entry": entry,
                "anchor": anchor, "cap": cap, "pnl": pnl, "exit": ex,
            })
    return pd.DataFrame(records)


def apply_sal(df):
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row["pnl"] < -0.1 and row["exit"] != "BE":
                    lost = True
    return pd.DataFrame(kept).sort_values("touched_at").reset_index(drop=True)


def pf(s):
    g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def maxdd(s):
    e = s.cumsum()
    return float((e - e.cummax()).min())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    delays = [0, 1, 2, 3, 5, 10]
    base_net = None
    print(f"{'delay':>5} {'n':>5} {'net':>9} {'PF':>6} {'maxDD':>8} {'TP':>5} {'SL':>5} {'BE':>5} {'cut':>5}"
          f"   {'dNet':>8} {'dDD':>7}")
    for d in delays:
        raw = build_ledger(bars, vxn, d)
        kept = apply_sal(raw)
        p = kept["pnl"]
        ex = kept["exit"].value_counts()
        net, p_pf, dd = p.sum(), pf(p), maxdd(p)
        if base_net is None:
            base_net, base_dd = net, dd
        print(f"{d:>5} {len(kept):>5} {net:>9.0f} {p_pf:>6.3f} {dd:>8.0f} "
              f"{ex.get('TP', 0):>5} {ex.get('SL', 0):>5} {ex.get('BE', 0):>5} {ex.get('cutoff', 0):>5}"
              f"   {net - base_net:>+8.0f} {dd - base_dd:>+7.0f}")


if __name__ == "__main__":
    main()
