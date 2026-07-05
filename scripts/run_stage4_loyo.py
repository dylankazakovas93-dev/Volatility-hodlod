#!/usr/bin/env python3
"""Stage 4: leave-one-development-year-out internal robustness check.

For each development year Y, "select" the best regime rule (by the same
Part C criteria) using only the other three development years' data, then
report that rule's performance on Y. This is internal development
robustness only -- not a final out-of-sample test (2019/2021/2022/2024/
2025 remain untouched throughout).

Usage:
    python3 scripts/run_stage4_loyo.py --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

DEV_YEARS = [2018, 2020, 2023, 2026]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    cand_df = pd.read_csv(os.path.join(out_dir, "stage4_candidate_summary.csv"))
    control = cand_df[cand_df["candidate"] == "no_filter"].iloc[0]
    control_yearly = json.loads(control["yearly_json"])

    MIN_TRAIN_TRADES_PER_YEAR = 15  # relaxed vs. the full-population 20, since
    # this is a 3-of-4-year training subset, not the full development population

    rows = []
    for held_out in DEV_YEARS:
        train_years = [y for y in DEV_YEARS if y != held_out]
        best_name, best_pf = None, -1
        for _, r in cand_df.iterrows():
            if r["candidate"] == "no_filter":
                continue
            yearly = json.loads(r["yearly_json"])
            train_rows = [yearly[str(y)] for y in train_years if str(y) in yearly]
            if len(train_rows) < len(train_years):
                continue
            # avoid tiny-sample flukes: require a minimum trade count in
            # every training year, not just "highest training PF"
            if any(x.get("n", 0) < MIN_TRAIN_TRADES_PER_YEAR for x in train_rows):
                continue
            gains = sum(x["net_pts"] for x in train_rows if x["net_pts"] > 0)
            losses = sum(-x["net_pts"] for x in train_rows if x["net_pts"] < 0)
            train_pf = gains / losses if losses > 0 else (float("inf") if gains > 0 else 0)
            all_train_profitable = all(x["net_pts"] > 0 for x in train_rows)
            if all_train_profitable and train_pf > best_pf:
                best_pf, best_name = train_pf, r["candidate"]

        if best_name is None:
            rows.append({"held_out_year": held_out, "selected_rule": None,
                         "held_out_net": control_yearly.get(str(held_out), {}).get("net_pts"),
                         "held_out_PF": control_yearly.get(str(held_out), {}).get("PF"),
                         "note": "no candidate all-profitable on the other 3 years -- fell back to no_filter"})
            continue

        sel = cand_df[cand_df["candidate"] == best_name].iloc[0]
        sel_yearly = json.loads(sel["yearly_json"])
        held = sel_yearly.get(str(held_out), {"net_pts": None, "PF": None, "n": 0})
        rows.append({"held_out_year": held_out, "selected_rule": best_name,
                     "train_pf": round(best_pf, 4),
                     "held_out_net": held["net_pts"], "held_out_PF": held.get("PF"), "held_out_n": held.get("n")})

    result = pd.DataFrame(rows)
    result.to_csv(os.path.join(out_dir, "stage4_loyo.csv"), index=False)
    print(result.to_string())

    stable = result["selected_rule"].nunique() <= 2 if result["selected_rule"].notna().any() else False
    print(f"\ndistinct rules selected across 4 held-out folds: {result['selected_rule'].nunique()}")
    print(f"stability verdict: {'stable' if stable else 'unstable'} (same/similar rule chosen across folds: {stable})")


if __name__ == "__main__":
    main()
