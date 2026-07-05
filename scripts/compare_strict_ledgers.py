#!/usr/bin/env python3
"""Row-by-row comparison of two strict-engine NQ ledgers.

Row identity: (level_id, physical first-touch timestamp, side, origin session).
See docs/CROSS_MODEL_RECONCILIATION_PROTOCOL.md for the full protocol this
script implements.

Usage:
    python3 scripts/compare_strict_ledgers.py \
        --reference outputs/nq_strict_executed.csv \
        --comparison path/to/other_ledger.csv

    # if the comparison ledger uses different column names:
    python3 scripts/compare_strict_ledgers.py \
        --reference outputs/nq_strict_executed.csv \
        --comparison path/to/other_ledger.csv \
        --comparison-columns level_id=id,entry_time=touch_ts,side=side,\
session_date=sess,exit_reason=exit,pnl=points
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

REQUIRED_COLS = ["level_id", "entry_time", "side", "session_date", "exit_reason", "pnl"]


def load_ledger(path, colmap=None):
    df = pd.read_csv(path)
    if colmap:
        df = df.rename(columns={v: k for k, v in colmap.items()})
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing required columns {missing} (got {list(df.columns)})")
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True, errors="coerce")
    if "exit_time" in df.columns:
        df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True, errors="coerce")
    df["_key"] = (
        df["level_id"].astype(str) + "|" +
        df["entry_time"].astype(str) + "|" +
        df["side"].astype(str) + "|" +
        df["session_date"].astype(str)
    )
    return df


def parse_colmap(s):
    if not s:
        return None
    out = {}
    for pair in s.split(","):
        k, v = pair.split("=")
        out[k.strip()] = v.strip()
    return out


def classify_difference(ref_row, cmp_row):
    """Best-effort classification. Returns one of the categories in the
    protocol doc, defaulting to unexplained. This is a heuristic starting
    point -- reviewers should still eyeball rows classified unexplained."""
    if ref_row is None:
        return "first_touch_mismatch_or_eligibility_gate_mismatch"
    if cmp_row is None:
        return "first_touch_mismatch_or_eligibility_gate_mismatch"

    if ref_row["exit_reason"] != cmp_row["exit_reason"]:
        if "exit_time" in ref_row and "exit_time" in cmp_row:
            if pd.notna(ref_row.get("exit_time")) and pd.notna(cmp_row.get("exit_time")):
                if ref_row["exit_reason"] == "BE" or cmp_row["exit_reason"] == "BE":
                    return "be_timing_mismatch"
        return "position_state_mismatch_or_sal_state_mismatch"

    pnl_diff = abs(float(ref_row["pnl"]) - float(cmp_row["pnl"]))
    if pnl_diff < 0.01:
        return "matched"
    if pnl_diff < 1.0:
        return "numerical_precision_only"
    return "fill_policy_mismatch_or_same_bar_policy_mismatch"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--comparison", required=True)
    ap.add_argument("--comparison-columns", default=None,
                     help="comma-separated canonical=other mappings, e.g. "
                          "level_id=id,entry_time=touch_ts")
    ap.add_argument("--max-detail", type=int, default=100)
    args = ap.parse_args()

    ref = load_ledger(args.reference)
    cmp_colmap = parse_colmap(args.comparison_columns)
    cmp = load_ledger(args.comparison, cmp_colmap)

    ref_idx = ref.set_index("_key")
    cmp_idx = cmp.set_index("_key")

    ref_keys = set(ref_idx.index)
    cmp_keys = set(cmp_idx.index)

    only_ref = sorted(ref_keys - cmp_keys)
    only_cmp = sorted(cmp_keys - ref_keys)
    both = sorted(ref_keys & cmp_keys)

    matched = []
    diff_exit = []
    diff_pnl = []
    detail_rows = []
    category_pnl_effect = {}

    for k in both:
        r = ref_idx.loc[k]
        c = cmp_idx.loc[k]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        if isinstance(c, pd.DataFrame):
            c = c.iloc[0]

        same_exit = r["exit_reason"] == c["exit_reason"]
        pnl_diff = abs(float(r["pnl"]) - float(c["pnl"]))

        if same_exit and pnl_diff < 0.01:
            matched.append(k)
            continue

        cat = classify_difference(r, c)
        category_pnl_effect.setdefault(cat, 0.0)
        category_pnl_effect[cat] += (float(c["pnl"]) - float(r["pnl"]))

        if not same_exit:
            diff_exit.append(k)
        else:
            diff_pnl.append(k)

        if len(detail_rows) < args.max_detail:
            detail_rows.append({
                "key": k,
                "ref_exit": r["exit_reason"], "cmp_exit": c["exit_reason"],
                "ref_pnl": float(r["pnl"]), "cmp_pnl": float(c["pnl"]),
                "pnl_diff": float(c["pnl"]) - float(r["pnl"]),
                "category": cat,
            })

    for k in only_ref:
        category_pnl_effect.setdefault("only_in_reference", 0.0)
        category_pnl_effect["only_in_reference"] -= float(ref_idx.loc[k, "pnl"])
        if len(detail_rows) < args.max_detail:
            detail_rows.append({"key": k, "category": "only_in_reference",
                                 "ref_pnl": float(ref_idx.loc[k, "pnl"]), "cmp_pnl": None})

    for k in only_cmp:
        category_pnl_effect.setdefault("only_in_comparison", 0.0)
        category_pnl_effect["only_in_comparison"] += float(cmp_idx.loc[k, "pnl"])
        if len(detail_rows) < args.max_detail:
            detail_rows.append({"key": k, "category": "only_in_comparison",
                                 "ref_pnl": None, "cmp_pnl": float(cmp_idx.loc[k, "pnl"])})

    print("=== ROW-BY-ROW LEDGER COMPARISON ===")
    print(f"  reference rows       : {len(ref)}")
    print(f"  comparison rows      : {len(cmp)}")
    print(f"  matched               : {len(matched)}")
    print(f"  only in reference     : {len(only_ref)}")
    print(f"  only in comparison    : {len(only_cmp)}")
    print(f"  same entry, diff exit : {len(diff_exit)}")
    print(f"  same entry/exit, diff pnl : {len(diff_pnl)}")
    print()
    print("=== AGGREGATE P&L EFFECT BY CATEGORY (comparison - reference) ===")
    for cat, effect in sorted(category_pnl_effect.items(), key=lambda kv: -abs(kv[1])):
        print(f"  {cat:55s} {effect:+10.2f} pts")
    print()
    print(f"=== FIRST {min(args.max_detail, len(detail_rows))} DETAILED DIFFERENCES ===")
    for row in detail_rows[:args.max_detail]:
        print(row)

    reproduced = (len(only_ref) == 0 and len(only_cmp) == 0
                  and len(diff_exit) == 0 and len(diff_pnl) == 0)
    print()
    print(f"FULLY REPRODUCED: {reproduced}")
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
