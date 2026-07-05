#!/usr/bin/env python3
"""Stage 1 section 22: volume-increment test. For every (scale, a, b)
combination, compares each nonzero-gamma variant against its gamma=0
control using the FULL 2018-2025 development-period ledger (same
candidates already computed by run_stage1_simple_surface.py -- no new
replay needed).

Usage:
    python3 scripts/run_stage1_volume_increment.py --out-dir outputs
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
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    cand = pd.read_csv(os.path.join(out_dir, "stage1_simple_all_candidates.csv"))
    rows = []
    for (scale, a, b), grp in cand.groupby(["scale", "a_tp_mult", "b_sl_mult"]):
        control = grp[grp["gamma"] == 0.0]
        if control.empty:
            continue
        control_row = control.iloc[0]
        for _, row in grp[grp["gamma"] != 0.0].iterrows():
            rows.append({
                "scale": scale, "a": a, "b": b, "gamma": row["gamma"],
                "gamma_PF": row["PF_R"], "control_PF": control_row["PF_R"],
                "delta_PF": (row["PF_R"] or 0) - (control_row["PF_R"] or 0),
                "gamma_avg_R": row["avg_R"], "control_avg_R": control_row["avg_R"],
                "delta_avg_R": (row["avg_R"] or 0) - (control_row["avg_R"] or 0),
                "gamma_max_dd_R": row["max_dd_R"], "control_max_dd_R": control_row["max_dd_R"],
                "gamma_net_pts": row["net_pts"], "control_net_pts": control_row["net_pts"],
            })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, "stage1_volume_increment.csv"), index=False)

    summary = {
        "n_comparisons": len(df),
        "frac_gamma_beats_control_on_avg_R": float((df["delta_avg_R"] > 0).mean()) if len(df) else None,
        "frac_gamma_beats_control_on_PF": float((df["delta_PF"] > 0).mean()) if len(df) else None,
        "median_delta_avg_R": float(df["delta_avg_R"].median()) if len(df) else None,
        "median_delta_PF": float(df["delta_PF"].median()) if len(df) else None,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
