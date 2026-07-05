#!/usr/bin/env python3
"""Stage 3: breakeven / scratch-management candidates on top of the frozen
Stage 2 configuration (E-F entry window 08:00-11:00 ET, frozen F2 TP/SL,
SAL off, gross P&L, development years 2018/2020/2023/partial-2026 only).

Usage:
    python3 scripts/run_stage3_be_scratch.py --bars ... --out-dir outputs
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
    DEV_YEARS, fit_frozen_formula, apply_frozen_formula,
    minutes_since_session_start, window_allows,
)
import scripts.stage3_engine as s3  # noqa: E402

WINDOW_BLOCKS = set("EF")  # 08:00-11:00 ET


def run_replay(bars, master_with_dist, simulate_fn, sim_kwargs):
    df = master_with_dist.dropna(subset=["tp_dist_stage2", "sl_dist_stage2"]).sort_values("touched_at")

    executed = []
    skip_counts = {"blocked_reserved_year": 0, "blocked_window": 0, "position_open": 0, "same_bar_reentry": 0}
    position_open_until = None

    for row in df.itertuples(index=False):
        ts = getattr(row, "touched_at")
        sess = getattr(row, "session_date")
        year = getattr(row, "year")

        if year not in DEV_YEARS:
            skip_counts["blocked_reserved_year"] += 1
            continue

        minutes_elapsed = minutes_since_session_start(ts, sess)
        if not window_allows(WINDOW_BLOCKS, minutes_elapsed):
            skip_counts["blocked_window"] += 1
            continue

        if position_open_until is not None and ts < position_open_until:
            skip_counts["position_open"] += 1
            continue
        if position_open_until is not None and ts == position_open_until:
            skip_counts["same_bar_reentry"] += 1
            continue

        side = getattr(row, "side")
        sign = 1.0 if side == "lower" else -1.0
        entry_price = getattr(row, "entry_price")
        cutoff_ts = getattr(row, "forced_liquidation_ts")
        tp_dist = getattr(row, "tp_dist_stage2")
        sl_dist = getattr(row, "sl_dist_stage2")

        pnl, reason, exit_ts, audit = simulate_fn(
            bars, ts, cutoff_ts, entry_price, sign, tp_dist, sl_dist, **sim_kwargs)

        hold_minutes = int((exit_ts - ts) / pd.Timedelta(minutes=1))
        executed.append({
            "level_id": getattr(row, "level_id"), "session_date": sess, "year": year,
            "side": side, "entry_time": ts, "exit_time": exit_ts,
            "entry_price": entry_price, "tp_dist": tp_dist, "sl_dist": sl_dist,
            "pnl_pts": pnl, "r_multiple": pnl / sl_dist, "exit_reason": reason,
            "hold_minutes": hold_minutes,
        })
        position_open_until = exit_ts

    return pd.DataFrame(executed), skip_counts


def summarize(executed, dev_years=DEV_YEARS):
    dev = executed[executed["year"].isin(dev_years)]
    out = {"n_trades": len(dev)}
    if len(dev) == 0:
        return out
    pnl, r = dev["pnl_pts"], dev["r_multiple"]
    out.update({
        "net_pts": round(float(pnl.sum()), 2),
        "PF": round(profit_factor(pnl), 4),
        "avg_R": round(float(r.mean()), 4),
        "max_dd_pts": round(max_drawdown(pnl), 2),
        "max_dd_R": round(max_drawdown(r), 4),
        "avg_hold_minutes": round(float(dev["hold_minutes"].mean()), 1),
    })
    counts = dev["exit_reason"].value_counts().to_dict()
    for k in ("TP", "SL", "BE", "LOCK", "SCRATCH", "cutoff"):
        out[f"n_{k}"] = int(counts.get(k, 0))
    for side, s in dev.groupby("side"):
        out[f"{side}_n"] = len(s)
        out[f"{side}_net_pts"] = round(float(s["pnl_pts"].sum()), 2)
        out[f"{side}_avg_R"] = round(float(s["r_multiple"].mean()), 4)
    yearly = {}
    for yr, s in dev.groupby("year"):
        yearly[int(yr)] = {
            "n": len(s), "net_pts": round(float(s["pnl_pts"].sum()), 2),
            "PF": round(profit_factor(s["pnl_pts"]), 4), "avg_R": round(float(s["r_multiple"].mean()), 4),
        }
    out["yearly"] = yearly
    ex2026 = dev[dev["year"] != 2026]
    if len(ex2026):
        out["ex_2026_net_pts"] = round(float(ex2026["pnl_pts"].sum()), 2)
        out["ex_2026_PF"] = round(profit_factor(ex2026["pnl_pts"]), 4)
    return out


CANDIDATES = []
CANDIDATES.append(("no_be_control", s3.simulate_no_management, {}))
CANDIDATES.append(("historical_BE45", s3.simulate_be45, {}))
for r in (0.25, 0.50, 0.75, 1.00):
    CANDIDATES.append((f"exact_r_be_{r:.2f}R", s3.simulate_exact_r_be, {"trigger_r": r}))
for frac in (0.25, 0.50, 0.75):
    CANDIDATES.append((f"tp_progress_be_{int(frac*100)}pct", s3.simulate_tp_progress_be, {"trigger_frac": frac}))
for r in (0.50, 0.75, 1.00):
    CANDIDATES.append((f"profit_lock_{r:.2f}R", s3.simulate_exact_r_be, {"trigger_r": r, "lock_r": 0.10}))
for m in (15, 30, 45, 60):
    CANDIDATES.append((f"time_delayed_be_{m}min", s3.simulate_time_delayed_be, {"minutes": m}))
for r in (0.25, 0.50, 0.75):
    CANDIDATES.append((f"scratch_recovery_{r:.2f}R", s3.simulate_scratch_on_recovery, {"adverse_r": r}))
for be_r, sc_r in [(0.50, 0.50), (0.50, 0.75), (0.75, 0.50), (0.75, 0.75)]:
    CANDIDATES.append((f"combined_be{be_r:.2f}R_scratch{sc_r:.2f}R", s3.simulate_combined_be_scratch,
                        {"be_r": be_r, "scratch_r": sc_r}))


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
    frozen = fit_frozen_formula(master, 0.50, 0.50, DEV_YEARS)
    full_df = apply_frozen_formula(master, frozen)

    rows = []
    for name, fn, kwargs in CANDIDATES:
        executed, skip = run_replay(bars, full_df, fn, kwargs)
        executed.to_csv(os.path.join(out_dir, f"stage3_ledger_{name}.csv"), index=False)
        summ = summarize(executed)
        row = {"candidate": name, "skip_counts": json.dumps(skip)}
        row.update({k: v for k, v in summ.items() if k != "yearly"})
        row["yearly_json"] = json.dumps(summ.get("yearly", {}))
        rows.append(row)
        print(f"{name}: n={summ.get('n_trades')} net={summ.get('net_pts')} PF={summ.get('PF')}", file=sys.stderr)

    cand_df = pd.DataFrame(rows)
    out_path = os.path.join(out_dir, "stage3_candidate_summary.csv")
    cand_df.to_csv(out_path, index=False)

    def git_sha():
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
        except Exception:
            return None

    def sha256_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    meta = {
        "research_commit": git_sha(), "n_candidates": len(CANDIDATES),
        "output_sha256": sha256_file(out_path),
        "reproduction_command": f"python3 scripts/run_stage3_be_scratch.py --bars {args.bars} --out-dir {args.out_dir}",
    }
    with open(os.path.join(out_dir, "stage3_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))
    print(cand_df[["candidate", "n_trades", "net_pts", "PF", "avg_R", "max_dd_pts"]].to_string())


if __name__ == "__main__":
    main()
