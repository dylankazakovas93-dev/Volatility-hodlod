#!/usr/bin/env python3
"""CANONICAL BASELINE FINGERPRINT GATE.

Run this BEFORE any optimization, Monte Carlo, or delta analysis. It rebuilds
the locked cond@45 baseline from source data and checks it against the frozen
fingerprint. If anything differs -- data file, date range, trade count, net,
PF, exit mix -- it prints BASELINE MISMATCH and refuses to validate.

No matching fingerprint -> no research. All deltas must be measured against
this exact baseline.

    python3 scripts/verify_canonical.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations
import argparse, hashlib, os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import load_1m_ohlcv, load_gvz_daily
import scripts.nq_cond_be45 as C

# ---- FROZEN CANONICAL FINGERPRINT (do not edit without re-verification) ----
FINGERPRINT = {
    "trades": 1256, "net_pts": 15665, "PF": 1.678,
    "TP": 487, "SL": 342, "BE": 316, "cutoff": 111,
    "raw_pre_sal": 1841,
    "bars_rows": 2964655,
    "bars_start": "2018-01-01 18:00:00-05:00",
    "bars_end": "2026-06-07 19:59:00-04:00",
    "vxn_file": "vxn_daily_2018_2026.csv",
}
LINE_DAYS, BE_BAR, SL_CAP = 20, 45, 200.0
ENTRY_WINDOW = "touches 19:00-11:00 ET count; 11:00-15:00 skipped"
CAP_FORMULA = "cap = min(1.5 x prev completed 1h range, 200)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--export", action="store_true", help="write canonical ledger CSV")
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)

    raw = C.build_ledger(bars, vxn)
    kept = C.apply_sal(raw).sort_values("touched_at").reset_index(drop=True)
    ex = kept["exit"].value_counts()

    got = {
        "trades": len(kept),
        "net_pts": round(float(kept["pnl"].sum())),
        "PF": round(C.profit_factor(kept["pnl"]), 3),
        "TP": int(ex.get("TP", 0)), "SL": int(ex.get("SL", 0)),
        "BE": int(ex.get("BE", 0)), "cutoff": int(ex.get("cutoff", 0)),
        "raw_pre_sal": len(raw),
        "bars_rows": len(bars),
        "bars_start": str(bars.index[0]),
        "bars_end": str(bars.index[-1]),
        "vxn_file": os.path.basename(args.vxn),
    }

    print("=== DATA PROVENANCE (the thing that drifted) ===")
    print(f"  bars file : {args.bars}")
    print(f"  bars rows : {len(bars):,}")
    print(f"  bars span : {bars.index[0]} -> {bars.index[-1]}")
    print(f"  vxn  file : {args.vxn}   rows={len(vxn)}")
    print(f"  config    : lineDays={LINE_DAYS} BE_bar={BE_BAR} {CAP_FORMULA}")
    print(f"  entry     : {ENTRY_WINDOW}")
    print()

    mism = [k for k, v in FINGERPRINT.items() if v is not None and got.get(k) != v]
    print("=== FINGERPRINT CHECK ===")
    for k, v in FINGERPRINT.items():
        if v is None:
            continue
        flag = "OK" if got.get(k) == v else "*** MISMATCH ***"
        print(f"  {k:>12}: expected {v:>8}  got {got.get(k):>8}   {flag}")

    if mism:
        print("\nBASELINE MISMATCH. TEST INVALID. DO NOT INTERPRET RESULTS.")
        print(f"  differing fields: {mism}")
        sys.exit(1)

    print("\nFINGERPRINT MATCH -- baseline is canonical. Research may proceed.")
    print("All reported deltas must be measured against this exact baseline.")

    if args.export:
        out = kept[["sess_date", "year", "side", "touched_at", "level",
                    "anchor", "cap", "pnl", "exit"]].copy()
        path = "data/canonical/canonical_nq_locked_baseline_1256trades.csv"
        out.to_csv(path, index=False)
        fp = "data/canonical/FINGERPRINT.txt"
        with open(fp, "w") as f:
            f.write("NQ LOCKED BASELINE -- canonical fingerprint\n")
            f.write("config: cond@45, lineDays=20, BE_bar=45, "
                    "cap=min(1.5*prev_1h_range,200), TP=SL=cap, SAL on first real loss\n")
            f.write(f"entry window: {ENTRY_WINDOW}\n\n")
            for k, v in got.items():
                f.write(f"{k} = {v}\n")
            f.write(f"\nbars_file = {os.path.basename(args.bars)}\n")
            f.write(f"bars_rows = {len(bars)}\n")
            f.write(f"bars_span = {bars.index[0]} -> {bars.index[-1]}\n")
            f.write(f"vxn_file  = {os.path.basename(args.vxn)}\n")
        print(f"\nexported: {path}")
        print(f"exported: {fp}")


if __name__ == "__main__":
    main()
