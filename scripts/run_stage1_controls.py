#!/usr/bin/env python3
"""Stage 1 section 25: required controls, run once each over the full
2018-2025 development population (2026 reported separately, never used to
pick a control).

1. Cutoff-only Stage 0 control -- already computed
   (outputs/stage0_control_summary.json); reported here for convenience.
2. Simple 1x-scale controls: TP=SL=1.0 x {range_30m, atr14_60m,
   prev_session_range, sqrt(range_30m*atr14_60m)}.
3. No-volume controls: gamma=0 rows already exist inside
   stage1_simple_all_candidates.csv for every scale/a/b; extracted here.

Usage:
    python3 scripts/run_stage1_controls.py --bars ... --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from scripts.stage1_engine import round_tp, round_sl, run_replay  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table, SCALES  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    ap.add_argument("--cost", type=float, default=1.0)
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    bars = load_1m_ohlcv(args.bars)
    master = build_master_table(out_dir)

    rows = []
    for scale in SCALES:
        touches = master.dropna(subset=[scale]).copy()
        touches["tp_dist_stage1"] = round_tp(1.0 * touches[scale])
        touches["sl_dist_stage1"] = round_sl(1.0 * touches[scale])
        executed, skipped = run_replay(bars, touches, "tp_dist_stage1", "sl_dist_stage1", cost_pts=args.cost)
        dev = executed[executed["year"] <= 2025]
        pnl = dev["pnl_after_cost"]
        r = dev["r_multiple"]
        rows.append({
            "control": f"1.0x_{scale}", "executed_2018_2025": len(dev),
            "net_pts": round(float(pnl.sum()), 2) if len(pnl) else 0.0,
            "PF": round(profit_factor(pnl), 4) if len(pnl) else None,
            "avg_R": round(float(r.mean()), 4) if len(r) else None,
            "max_dd_R": round(max_drawdown(r), 4) if len(r) else None,
        })

    control_df = pd.DataFrame(rows)
    control_df.to_csv(os.path.join(out_dir, "stage1_simple_controls.csv"), index=False)

    with open(os.path.join(out_dir, "stage0_control_summary.json")) as f:
        cutoff_control = json.load(f)

    print(json.dumps({"cutoff_only_control": {
        "executed": cutoff_control["executed"], "net_pts": cutoff_control["net_pts"],
        "PF": cutoff_control["PF"]},
    }, indent=2))
    print(control_df.to_string())


if __name__ == "__main__":
    main()
