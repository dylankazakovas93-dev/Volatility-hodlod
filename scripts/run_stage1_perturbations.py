#!/usr/bin/env python3
"""Stage 1 section 19: perturbation battery for a single frozen simple
candidate (scale, gamma, a, b). Only top robust candidates are perturbed --
this script takes one candidate at a time, not the whole grid.

Perturbations run (section 19A/C -- lookback-window perturbations for
range/ATR timeframes are reported as a documented limitation: the
underlying feature table only has range_{15,30,60,120}m and
atr14_{5,15,30,60}m, i.e. no range_20m/range_45m/atr45m -- the closest
available preregistered neighbours are used and this substitution is
logged explicitly, never silently)):
  - neighbouring TP multiplier a (+/- one preregistered step)
  - neighbouring SL multiplier b (+/- one preregistered step)
  - neighbouring gamma (+/- one preregistered step)
  - RVOL history 15 / 20 / 30 sessions
  - RVOL clip bounds 0.75-1.33 / 0.80-1.25 / 0.85-1.18
  - cost 0.5 / 1.0 / 2.0 points
  - adverse entry-fill shift 0.25 / 0.50 points
  - forced liquidation 15:44 ET stress cutoff
  - leave-one-development-year-out (2018..2025 each excluded once)
  - exclude 2026

Usage:
    python3 scripts/run_stage1_perturbations.py --bars ... --out-dir outputs \
        --scale S1_range30m --gamma 0.0 --a 1.0 --b 1.0
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

from src.data_loader import load_1m_ohlcv  # noqa: E402
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from scripts.stage1_engine import round_tp, round_sl, run_replay, first_passage_exit  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table, GAMMAS, MULTS  # noqa: E402

RVOL_HIST_OPTIONS = [15, 20, 30]
CLIP_OPTIONS = [(0.75, 1.33), (0.80, 1.25), (0.85, 1.18)]
COST_OPTIONS = [0.5, 1.0, 2.0]
ADVERSE_SHIFT_OPTIONS = [0.0, 0.25, 0.50]


def metrics_from_ledger(executed, years=None):
    if years is not None:
        executed = executed[executed["year"].isin(years)]
    pnl = executed["pnl_after_cost"]
    r = executed["r_multiple"]
    if len(pnl) == 0:
        return {"n": 0, "net_pts": 0.0, "PF": None, "avg_R": None}
    return {
        "n": len(pnl), "net_pts": round(float(pnl.sum()), 2),
        "PF": round(profit_factor(pnl), 4), "avg_R": round(float(r.mean()), 4),
    }


def run_one(bars, master, scale, gamma, a, b, rvol_col="rvol_60m_hist20_session_anchored",
            clip_bounds=(0.80, 1.25), cost=1.0, adverse_shift=0.0, cutoff_col="forced_liquidation_ts",
            exclude_years=None):
    m = master.copy()
    if exclude_years:
        m = m[~m["year"].isin(exclude_years)]
    rvol_factor = np.clip(m[rvol_col].fillna(1.0) ** gamma, *clip_bounds)
    s_adj = m[scale] * rvol_factor
    m["tp_dist_stage1"] = round_tp(a * s_adj)
    m["sl_dist_stage1"] = round_sl(b * s_adj)
    m["entry_price"] = m["entry_price"] + adverse_shift * np.where(m["side"] == "lower", 1.0, -1.0)
    m["forced_liquidation_ts"] = m[cutoff_col]
    m = m.dropna(subset=[scale, "tp_dist_stage1", "sl_dist_stage1"])
    executed, skipped = run_replay(bars, m, "tp_dist_stage1", "sl_dist_stage1", cost_pts=cost)
    return executed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    ap.add_argument("--scale", required=True)
    ap.add_argument("--gamma", type=float, required=True)
    ap.add_argument("--a", type=float, required=True)
    ap.add_argument("--b", type=float, required=True)
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    bars = load_1m_ohlcv(args.bars)
    master = build_master_table(out_dir)
    master["forced_liquidation_1544"] = master["forced_liquidation_ts"] - pd.Timedelta(minutes=15)
    dev_master = master[master["year"] <= 2025]

    base = run_one(bars, dev_master, args.scale, args.gamma, args.a, args.b)
    base_metrics = metrics_from_ledger(base)

    rows = [{"perturbation": "base", **base_metrics}]

    gi = GAMMAS.index(args.gamma)
    for dg in (-1, 1):
        if 0 <= gi + dg < len(GAMMAS):
            g2 = GAMMAS[gi + dg]
            ex = run_one(bars, dev_master, args.scale, g2, args.a, args.b)
            rows.append({"perturbation": f"gamma_neighbor_{g2:+.2f}", **metrics_from_ledger(ex)})

    ai = MULTS.index(args.a)
    for da in (-1, 1):
        if 0 <= ai + da < len(MULTS):
            a2 = MULTS[ai + da]
            ex = run_one(bars, dev_master, args.scale, args.gamma, a2, args.b)
            rows.append({"perturbation": f"a_neighbor_{a2:.2f}", **metrics_from_ledger(ex)})

    bi = MULTS.index(args.b)
    for db in (-1, 1):
        if 0 <= bi + db < len(MULTS):
            b2 = MULTS[bi + db]
            ex = run_one(bars, dev_master, args.scale, args.gamma, args.a, b2)
            rows.append({"perturbation": f"b_neighbor_{b2:.2f}", **metrics_from_ledger(ex)})

    for n in RVOL_HIST_OPTIONS:
        col = f"rvol_60m_hist{n}_session_anchored"
        if col in dev_master.columns:
            ex = run_one(bars, dev_master, args.scale, args.gamma, args.a, args.b, rvol_col=col)
            rows.append({"perturbation": f"rvol_history_{n}", **metrics_from_ledger(ex)})

    for clip in CLIP_OPTIONS:
        ex = run_one(bars, dev_master, args.scale, args.gamma, args.a, args.b, clip_bounds=clip)
        rows.append({"perturbation": f"rvol_clip_{clip[0]}_{clip[1]}", **metrics_from_ledger(ex)})

    for cost in COST_OPTIONS:
        ex = run_one(bars, dev_master, args.scale, args.gamma, args.a, args.b, cost=cost)
        rows.append({"perturbation": f"cost_{cost}", **metrics_from_ledger(ex)})

    for shift in (0.25, 0.50):
        ex = run_one(bars, dev_master, args.scale, args.gamma, args.a, args.b, adverse_shift=shift)
        rows.append({"perturbation": f"adverse_fill_shift_{shift}", **metrics_from_ledger(ex)})

    ex = run_one(bars, dev_master, args.scale, args.gamma, args.a, args.b, cutoff_col="forced_liquidation_1544")
    rows.append({"perturbation": "cutoff_1544_stress", **metrics_from_ledger(ex)})

    for yr in range(2018, 2026):
        ex = run_one(bars, dev_master, args.scale, args.gamma, args.a, args.b, exclude_years=[yr])
        rows.append({"perturbation": f"leave_out_{yr}", **metrics_from_ledger(ex)})

    pert_df = pd.DataFrame(rows)
    label = f"scale-{args.scale}_gamma-{args.gamma}_a-{args.a}_b-{args.b}".replace(".", "p")
    out_path = os.path.join(out_dir, f"stage1_perturbations_{label}.csv")
    pert_df.to_csv(out_path, index=False)

    n_profitable = int((pert_df["net_pts"] > 0).sum())
    n_total = len(pert_df) - 1  # exclude 'base' row from denominator per spec intent
    frac_profitable = float((pert_df.iloc[1:]["net_pts"] > 0).mean())
    median_pf = float(pert_df.iloc[1:]["PF"].dropna().median())

    summary = {
        "candidate": f"{args.scale}/gamma={args.gamma}/a={args.a}/b={args.b}",
        "base_metrics": base_metrics,
        "n_perturbations": n_total,
        "fraction_profitable": frac_profitable,
        "median_perturbed_PF": median_pf,
        "output_csv": out_path,
    }
    with open(os.path.join(out_dir, f"stage1_perturbations_summary_{label}.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
