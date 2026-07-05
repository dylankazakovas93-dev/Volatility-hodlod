#!/usr/bin/env python3
"""Stage 1 section 21: month-block bootstrap for a surviving candidate's
executed-trade ledger. Resamples complete calendar-month trade blocks
(preserving trade order within each sampled month), not individual trades.

Usage:
    python3 scripts/run_stage1_bootstrap.py --ledger <executed_trades.csv> \
        --out-dir outputs --label <candidate_id> --n-sims 5000
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.metrics import profit_factor, max_drawdown  # noqa: E402

SEED = 42


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out-dir", default="outputs")
    ap.add_argument("--label", default="candidate")
    ap.add_argument("--n-sims", type=int, default=5000)
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    df = pd.read_csv(args.ledger)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["month"] = df["entry_time"].dt.to_period("M")
    months = sorted(df["month"].unique())
    by_month = {m: df[df["month"] == m] for m in months}
    n_months = len(months)

    rng = np.random.default_rng(SEED)
    avg_r_dist, pf_dist, dd_dist = [], [], []

    for _ in range(args.n_sims):
        sampled_months = rng.choice(months, size=n_months, replace=True)
        blocks = [by_month[m] for m in sampled_months]
        sim = pd.concat(blocks, ignore_index=True) if blocks else pd.DataFrame()
        if sim.empty:
            continue
        r = sim["r_multiple"]
        pnl = sim["pnl_after_cost"]
        avg_r_dist.append(float(r.mean()))
        pf_dist.append(profit_factor(pnl))
        dd_dist.append(max_drawdown(r))

    avg_r_dist = np.array(avg_r_dist)
    pf_dist = np.array([x for x in pf_dist if np.isfinite(x)])
    dd_dist = np.array(dd_dist)

    summary = {
        "label": args.label, "n_sims": args.n_sims, "n_months": n_months, "seed": SEED,
        "avg_R": {"p5": float(np.percentile(avg_r_dist, 5)), "p50": float(np.percentile(avg_r_dist, 50)),
                  "p95": float(np.percentile(avg_r_dist, 95))},
        "PF": {"p5": float(np.percentile(pf_dist, 5)) if len(pf_dist) else None,
               "p50": float(np.percentile(pf_dist, 50)) if len(pf_dist) else None,
               "p95": float(np.percentile(pf_dist, 95)) if len(pf_dist) else None},
        "max_dd_R": {"p5": float(np.percentile(dd_dist, 5)), "p50": float(np.percentile(dd_dist, 50)),
                     "p95": float(np.percentile(dd_dist, 95))},
        "prob_negative_expectancy": float((avg_r_dist < 0).mean()),
        "prob_pf_below_1": float((pf_dist < 1.0).mean()) if len(pf_dist) else None,
    }
    out_path = os.path.join(out_dir, f"stage1_bootstrap_{args.label.replace('|', '_').replace('=', '-')}.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
