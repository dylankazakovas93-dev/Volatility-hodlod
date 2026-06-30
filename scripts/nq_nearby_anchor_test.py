#!/usr/bin/env python3
"""Test nearby evening IB anchors with default NQ level constants.

This is the companion sweep to nq_ib_anchor_test.py. It keeps the whole
downstream locked system unchanged (cond@45, cap=min(1.5*prev 1h range,200),
SAL, 19:00-11:00 entry window, 15:00 cutoff) and only changes the
generate_levels() anchor window.

The script first rebuilds the 09:30 canonical baseline and refuses to print
anchor deltas unless the frozen fingerprint matches. Wrong bars file -> no
research.

Usage:
    python3 scripts/nq_nearby_anchor_test.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
        --out outputs/nq_nearby_anchor_test.csv
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

CANONICAL = {
    "trades": 1256,
    "net_pts": 15665,
    "PF": 1.678,
    "TP": 487,
    "SL": 342,
    "BE": 316,
    "cutoff": 111,
    "raw_pre_sal": 1841,
    "bars_rows": 2964655,
    "bars_start": "2018-01-01 18:00:00-05:00",
    "bars_end": "2026-06-07 19:59:00-04:00",
    "vxn_file": "vxn_daily_2018_2026.csv",
}

# Same 6.5-hour window length used by nq_ib_anchor_test.py.
ANCHORS = [
    ("09:30 cash open baseline", "09:30", "16:00"),
    ("17:00 post-cash close", "17:00", "23:30"),
    ("18:00 Globex open", "18:00", "00:30"),
    ("19:00 post-close", "19:00", "01:30"),
    ("20:00 evening", "20:00", "02:30"),
    ("21:00 evening", "21:00", "03:30"),
    ("22:00 evening", "22:00", "04:30"),
    ("23:00 overnight", "23:00", "05:30"),
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
            cutoff = B.session_cutoff(ft)
            if cutoff is None:
                continue
            path = bars.loc[ft: cutoff].iloc[1:]
            if path.empty:
                continue
            cap = min(1.5 * anchor, B.SL_CAP)
            sign = -1.0 if side == "upper" else 1.0
            pnl, ex = simulate_cond_be(path, lvl, sign, cap)
            records.append({
                "sess_date": B.session_date(ft),
                "year": pd.Timestamp(B.session_date(ft)).year,
                "side": side,
                "touched_at": ft,
                "level": lvl,
                "anchor": anchor,
                "cap": cap,
                "pnl": pnl,
                "exit": ex,
            })
    return pd.DataFrame(records), len(levels)


def summarize(raw):
    kept = apply_sal(raw)
    p = kept["pnl"]
    ex = kept["exit"].value_counts()
    return {
        "raw_pre_sal": len(raw),
        "trades": len(kept),
        "net_pts": round(float(p.sum())),
        "net": float(p.sum()),
        "PF": round(profit_factor(p), 3),
        "maxDD": max_drawdown(p),
        "TP": int(ex.get("TP", 0)),
        "SL": int(ex.get("SL", 0)),
        "BE": int(ex.get("BE", 0)),
        "cutoff": int(ex.get("cutoff", 0)),
        "kept": kept,
    }


def verify_canonical_data(bars, vxn_path):
    got = {
        "bars_rows": len(bars),
        "bars_start": str(bars.index[0]),
        "bars_end": str(bars.index[-1]),
        "vxn_file": os.path.basename(vxn_path),
    }
    mismatches = [k for k, v in got.items() if v != CANONICAL[k]]
    if not mismatches:
        return

    print("*** DATA FINGERPRINT MISMATCH -- TEST INVALID. DO NOT INTERPRET RESULTS. ***")
    for k, got_value in got.items():
        expected = CANONICAL[k]
        flag = "OK" if got_value == expected else "MISMATCH"
        print(f"  {k:>10}: expected {expected}  got {got_value}  {flag}")
    raise SystemExit(1)


def verify_baseline(summary):
    keys = ("trades", "net_pts", "PF", "TP", "SL", "BE", "cutoff", "raw_pre_sal")
    mismatches = [k for k in keys if summary[k] != CANONICAL[k]]
    if not mismatches:
        print("canonical 09:30 baseline matched -- anchor research may proceed\n")
        return

    print("*** BASELINE MISMATCH -- TEST INVALID. DO NOT INTERPRET RESULTS. ***")
    for k in keys:
        flag = "OK" if summary[k] == CANONICAL[k] else "MISMATCH"
        print(f"  {k:>12}: expected {CANONICAL[k]}  got {summary[k]}  {flag}")
    raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out", help="optional CSV summary output path")
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    verify_canonical_data(bars, args.vxn)

    rows = []
    base_net = None
    print(f"{'anchor':>25} {'window':>11} {'sessions':>8} {'raw':>5} {'n':>5} "
          f"{'net':>9} {'dNet':>8} {'PF':>7} {'maxDD':>8} {'TP':>5} {'SL':>5} "
          f"{'BE':>5} {'cut':>5}")
    for label, start, end in ANCHORS:
        raw, sessions = build_ledger(bars, vxn, start, end)
        if raw.empty:
            row = {
                "anchor": label, "rth_start": start, "rth_end": end,
                "sessions": sessions, "raw_pre_sal": 0, "trades": 0,
                "net": 0.0, "dNet": None, "PF": None, "maxDD": None,
                "TP": 0, "SL": 0, "BE": 0, "cutoff": 0,
            }
            rows.append(row)
            print(f"{label:>25} {start+'-'+end:>11} {sessions:>8} no trades")
            continue

        summary = summarize(raw)
        if start == "09:30":
            verify_baseline(summary)
            base_net = summary["net"]
        d_net = summary["net"] - base_net if base_net is not None else 0.0
        row = {
            "anchor": label,
            "rth_start": start,
            "rth_end": end,
            "sessions": sessions,
            "raw_pre_sal": summary["raw_pre_sal"],
            "trades": summary["trades"],
            "net": summary["net"],
            "dNet": d_net,
            "PF": summary["PF"],
            "maxDD": summary["maxDD"],
            "TP": summary["TP"],
            "SL": summary["SL"],
            "BE": summary["BE"],
            "cutoff": summary["cutoff"],
        }
        rows.append(row)
        print(f"{label:>25} {start+'-'+end:>11} {sessions:>8} {row['raw_pre_sal']:>5} "
              f"{row['trades']:>5} {row['net']:>9.0f} {row['dNet']:>+8.0f} "
              f"{row['PF']:>7.3f} {row['maxDD']:>8.0f} {row['TP']:>5} {row['SL']:>5} "
              f"{row['BE']:>5} {row['cutoff']:>5}")

    if args.out:
        out = pd.DataFrame(rows)
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        out.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
