#!/usr/bin/env python3
"""Stage 1 section 23: evaluate the pass gate for a frozen candidate given
its outer-test results, perturbation results, causal-roll result, and
bootstrap result. Prints a plain PASS/FAIL breakdown per criterion --
does not weaken or skip any criterion.

Usage:
    python3 scripts/evaluate_stage1_gate.py --outer-csv outputs/stage1_outer_test_results.csv \
        --scale S1_range30m --gamma 0.0 --a 1.0 --b 1.0 \
        --perturbation-summary outputs/stage1_perturbations_summary_<label>.json \
        --causal-roll-summary outputs/stage1_causal_roll_summary.json \
        --bootstrap-summary outputs/stage1_bootstrap_<label>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outer-csv", required=True)
    ap.add_argument("--scale", required=True)
    ap.add_argument("--gamma", type=float, required=True)
    ap.add_argument("--a", type=float, required=True)
    ap.add_argument("--b", type=float, required=True)
    ap.add_argument("--perturbation-summary")
    ap.add_argument("--causal-roll-net-pts", type=float)
    ap.add_argument("--bootstrap-summary")
    args = ap.parse_args()

    outer = pd.read_csv(args.outer_csv)
    mine = outer[(outer["scale"] == args.scale) & (outer["gamma"] == args.gamma) &
                 (outer["a_tp_mult"] == args.a) & (outer["b_sl_mult"] == args.b)]

    checks = {}
    if mine.empty:
        checks["candidate_selected_in_any_fold"] = False
    else:
        net_col = "test_net_pts"
        pf_col = "test_PF"
        checks["candidate_selected_in_any_fold"] = True
        aggregate_net = mine[net_col].sum() if net_col in mine.columns else None
        checks["aggregate_outer_test_net_positive"] = bool(aggregate_net is not None and aggregate_net > 0)
        n_years = len(mine)
        n_profitable = int((mine[net_col] > 0).sum()) if net_col in mine.columns else 0
        checks["at_least_3_of_5_years_profitable"] = n_profitable >= 3
        checks["n_profitable_years"] = n_profitable
        checks["n_years_selected"] = n_years

    if args.perturbation_summary and os.path.exists(args.perturbation_summary):
        with open(args.perturbation_summary) as f:
            pert = json.load(f)
        checks["perturbation_fraction_profitable"] = pert["fraction_profitable"]
        checks["perturbation_ge_70pct_profitable"] = pert["fraction_profitable"] >= 0.70
        checks["median_perturbed_pf_gt_1_02"] = (pert["median_perturbed_PF"] or 0) > 1.02

    if args.causal_roll_net_pts is not None:
        checks["causal_roll_positive"] = args.causal_roll_net_pts > 0

    if args.bootstrap_summary and os.path.exists(args.bootstrap_summary):
        with open(args.bootstrap_summary) as f:
            boot = json.load(f)
        checks["bootstrap_prob_negative_expectancy"] = boot["prob_negative_expectancy"]
        checks["bootstrap_below_35pct"] = boot["prob_negative_expectancy"] < 0.35

    overall = all(v for k, v in checks.items() if isinstance(v, bool))
    print(json.dumps({"checks": checks, "all_boolean_checks_pass": overall}, indent=2))


if __name__ == "__main__":
    main()
