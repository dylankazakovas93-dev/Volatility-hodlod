#!/usr/bin/env python3
"""Quick test: anchor the IB/level placement at a different time of day
instead of the 09:30 ET cash open, everything else (cond@45 risk, BE,
SAL, entry window 19:00-11:00 ET, session cutoff 15:00 ET) unchanged.

generate_levels() takes rth_start/rth_end -- that's the window used to
pick the session's "cash open" and the IB high/low. This just sweeps
that anchor across a few candidate session-open times (Globex open,
London open, etc.) and reruns the exact same downstream system.

Usage:
    python3 scripts/nq_ib_anchor_test.py \
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
from scripts.nq_cond_be45 import simulate_cond_be, apply_sal, profit_factor, max_drawdown

CANONICAL_RAW_PRE_SAL = 1841

# (label, rth_start, rth_end)
ANCHORS = [
    ("09:30 cash open (baseline)", "09:30", "16:00"),
    ("18:00 Globex/Sunday open",    "18:00", "00:30"),
    ("20:00 evening session",       "20:00", "02:30"),
    ("03:00 London open",           "03:00", "09:30"),
    ("07:00 pre-market",            "07:00", "13:30"),
    ("08:00 pre-market",            "08:00", "14:30"),
]


def build_ledger(bars, vxn, rth_start, rth_end):
    levels = generate_levels(bars, vxn, params=NQ_PARAMS, rth_start=rth_start, rth_end=rth_end)
    if levels.empty:
        return pd.DataFrame(), 0
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
    return pd.DataFrame(records), len(levels)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    print(f"{'anchor':>32} {'sessions':>8} {'raw':>5} {'n':>5} {'net':>9} {'PF':>7} {'maxDD':>8} "
          f"{'TP':>5} {'SL':>5} {'BE':>5} {'cut':>5}")
    base_net = None
    for label, rs, re_ in ANCHORS:
        raw, n_sessions = build_ledger(bars, vxn, rs, re_)
        if raw.empty:
            print(f"{label:>32}   no levels generated")
            continue
        kept = apply_sal(raw)
        p = kept["pnl"]
        ex = kept["exit"].value_counts()
        net, p_pf, dd = p.sum(), profit_factor(p), max_drawdown(p)
        if base_net is None:
            base_net = net
        delta = f"{net-base_net:+.0f}" if base_net is not None else ""
        print(f"{label:>32} {n_sessions:>8} {len(raw):>5} {len(kept):>5} {net:>9.0f} {p_pf:>7.3f} {dd:>8.0f} "
              f"{ex.get('TP',0):>5} {ex.get('SL',0):>5} {ex.get('BE',0):>5} {ex.get('cutoff',0):>5}  delta={delta}")


if __name__ == "__main__":
    main()
