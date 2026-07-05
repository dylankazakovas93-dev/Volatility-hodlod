#!/usr/bin/env python3
"""Stage 2: frozen F2 TP/SL formula (refit on development years only) +
time-window and SAL testing.

Development years: 2018, 2020, 2023, partial 2026. Reserved years
(2019, 2021, 2022, 2024, 2025) are never inspected or reported here --
historical bars from any year may still be used to compute causal lagged
features for a development-year trade (the feature table already only
ever looks backward from touch time, so this happens automatically and
requires no special-casing).

Usage:
    python3 scripts/run_stage2_timewindow_sal.py --bars ... --out-dir outputs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table  # noqa: E402
from scripts.stage2_engine import (  # noqa: E402
    DEV_YEARS, RESERVED_YEARS, fit_frozen_formula, apply_frozen_formula,
    run_stage2_replay, all_test_windows, window_label, BLOCK_ORDER,
)


def dev_metrics(executed):
    dev = executed[executed["year"].isin(DEV_YEARS)]
    out = {"n_trades": len(dev)}
    if len(dev) == 0:
        return out
    pnl = dev["pnl_pts"]
    r = dev["r_multiple"]
    out.update({
        "net_pts": round(float(pnl.sum()), 2),
        "PF": round(profit_factor(pnl), 4),
        "avg_R": round(float(r.mean()), 4),
        "max_dd_R": round(max_drawdown(r), 4),
    })
    yearly = {}
    for yr, s in dev.groupby("year"):
        yearly[int(yr)] = {
            "n": len(s), "net_pts": round(float(s["pnl_pts"].sum()), 2),
            "PF": round(profit_factor(s["pnl_pts"]), 4),
            "avg_R": round(float(s["r_multiple"].mean()), 4),
        }
    out["yearly"] = yearly
    for side, s in dev.groupby("side"):
        out[f"{side}_n"] = len(s)
        out[f"{side}_net_pts"] = round(float(s["pnl_pts"].sum()), 2)
        out[f"{side}_avg_R"] = round(float(s["r_multiple"].mean()), 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    bars = load_1m_ohlcv(args.bars)
    master = build_master_table(out_dir)
    master["conventional_mfe_pts"] = master["mfe"].clip(lower=0)
    master["conventional_mae_pts"] = (-master["mae"]).clip(lower=0)

    # --- 1. fit frozen formula on dev years only ---
    frozen = fit_frozen_formula(master, mfe_q=0.50, mae_q=0.50, dev_years=DEV_YEARS)
    full_df = apply_frozen_formula(master, frozen)

    coef_summary = {
        "n_train_signals": frozen["n_train"],
        "tp_intercept": frozen["tp_intercept"], "tp_coefs": frozen["tp_coefs"],
        "sl_intercept": frozen["sl_intercept"], "sl_coefs": frozen["sl_coefs"],
        "mfe_clip_bounds": list(frozen["mfe_clip"]), "mae_clip_bounds": list(frozen["mae_clip"]),
    }
    with open(os.path.join(out_dir, "stage2_frozen_formula.json"), "w") as f:
        json.dump(coef_summary, f, indent=2, default=str)
    print("=== FROZEN FORMULA (fit on 2018/2020/2023/2026 only) ===")
    print(json.dumps(coef_summary, indent=2, default=str))

    # --- 2. all-hours baseline, SAL off / on ---
    exec_base_off, skip_base_off, _ = run_stage2_replay(bars, full_df, allowed_blocks=None, sal_enabled=False)
    exec_base_on, skip_base_on, sal_audit_base = run_stage2_replay(bars, full_df, allowed_blocks=None, sal_enabled=True)

    baseline = {
        "sal_off": {**dev_metrics(exec_base_off), "skip_counts": skip_base_off},
        "sal_on": {**dev_metrics(exec_base_on), "skip_counts": skip_base_on,
                   "n_sal_activations_dev_years": int(
                       (sal_audit_base["event"] == "SAL_activated").sum()
                       if len(sal_audit_base) and "session_date" in sal_audit_base.columns
                       else 0)},
    }
    exec_base_off.to_csv(os.path.join(out_dir, "stage2_baseline_sal_off_executed.csv"), index=False)
    exec_base_on.to_csv(os.path.join(out_dir, "stage2_baseline_sal_on_executed.csv"), index=False)
    sal_audit_base.to_csv(os.path.join(out_dir, "stage2_sal_audit_baseline.csv"), index=False)
    with open(os.path.join(out_dir, "stage2_baseline_summary.json"), "w") as f:
        json.dump(baseline, f, indent=2, default=str)
    print("\n=== ALL-HOURS BASELINE ===")
    print(json.dumps(baseline, indent=2, default=str))

    # --- 3. all windows, SAL off ---
    windows = all_test_windows()
    print(f"\n=== RUNNING {len(windows)} TIME WINDOWS (SAL off) ===", file=sys.stderr)
    window_rows = []
    for kind, blocks in windows:
        label = window_label(kind, blocks)
        ex, skip, _ = run_stage2_replay(bars, full_df, allowed_blocks=set(blocks), sal_enabled=False)
        m = dev_metrics(ex)
        row = {"window": label, "kind": kind, "blocks": "".join(blocks), "n_blocks": len(blocks)}
        row.update({k: v for k, v in m.items() if k != "yearly"})
        if "yearly" in m:
            for yr in DEV_YEARS:
                yd = m["yearly"].get(yr, {"n": 0, "net_pts": 0.0, "PF": None})
                row[f"y{yr}_n"] = yd["n"]
                row[f"y{yr}_net"] = yd["net_pts"]
                row[f"y{yr}_PF"] = yd["PF"]
        window_rows.append(row)

    windows_df = pd.DataFrame(window_rows).sort_values("window").reset_index(drop=True)
    windows_df.to_csv(os.path.join(out_dir, "stage2_windows_sal_off.csv"), index=False)
    print("done all windows", file=sys.stderr)

    def sha256_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def git_sha():
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
        except Exception:
            return None

    meta = {
        "research_commit": git_sha(), "dev_years": DEV_YEARS, "reserved_years": RESERVED_YEARS,
        "n_windows_tested": len(windows_df),
        "windows_sal_off_sha256": sha256_file(os.path.join(out_dir, "stage2_windows_sal_off.csv")),
        "reproduction_command": f"python3 scripts/run_stage2_timewindow_sal.py --bars {args.bars} --out-dir {args.out_dir}",
    }
    with open(os.path.join(out_dir, "stage2_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
