#!/usr/bin/env python3
"""Stage 5 Parts 1-4: cutoff sweep, contiguous windows, broken-session
windows, and the limited window/cutoff interaction. All on top of the
frozen F2 TP/SL + profit_lock_0.75R + hmm3_exclude_LOW_VOL regime gate.

Usage:
    python3 scripts/run_stage5_windows.py --bars ... --out-dir outputs --part {1,2,3,4}
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
from scripts.run_stage1_simple_surface import build_master_table  # noqa: E402
from scripts.stage2_engine import fit_frozen_formula, apply_frozen_formula, DEV_YEARS  # noqa: E402
from scripts.stage5_engine import (  # noqa: E402
    BLOCKS, BLOCK_ORDER, ASIA, LONDON, NEW_YORK, CUTOFF_MINUTES,
    in_allowed_blocks, in_minute_range, contiguous_windows, run_replay,
)


def build_master_with_hmm3(out_dir):
    master = build_master_table(out_dir)
    master["conventional_mfe_pts"] = master["mfe"].clip(lower=0)
    master["conventional_mae_pts"] = (-master["mae"]).clip(lower=0)
    frozen = fit_frozen_formula(master, 0.50, 0.50, DEV_YEARS)
    full_df = apply_frozen_formula(master, frozen)
    hmm3 = pd.read_csv(os.path.join(REPO_ROOT, out_dir, "stage5_hmm3_features.csv"))
    full_df = full_df.merge(hmm3, on="level_id", how="left")
    full_df["touched_at"] = pd.to_datetime(full_df["touched_at"], utc=True)
    full_df["forced_liquidation_ts"] = pd.to_datetime(full_df["forced_liquidation_ts"], utc=True)
    return full_df


def summarize(executed, dev_years=DEV_YEARS):
    dev = executed[executed["year"].isin(dev_years)]
    out = {"n_trades": len(dev)}
    if len(dev) == 0:
        return out
    pnl, r = dev["pnl_pts"], dev["r_multiple"]
    out.update({
        "net_pts": round(float(pnl.sum()), 2), "total_R": round(float(r.sum()), 4),
        "PF": round(profit_factor(pnl), 4), "avg_R": round(float(r.mean()), 4),
        "max_dd_pts": round(max_drawdown(pnl), 2), "max_dd_R": round(max_drawdown(r), 4),
    })
    tp_only = dev[dev["exit_reason"] == "TP"]
    out["true_tp_win_rate"] = round(len(tp_only) / len(dev), 4)
    for side, s in dev.groupby("side"):
        out[f"{side}_n"] = len(s)
        out[f"{side}_net_pts"] = round(float(s["pnl_pts"].sum()), 2)
    yearly = {}
    for yr, s in dev.groupby("year"):
        yearly[int(yr)] = {"n": len(s), "net_pts": round(float(s["pnl_pts"].sum()), 2),
                            "PF": round(profit_factor(s["pnl_pts"]), 4),
                            "avg_R": round(float(s["r_multiple"].mean()), 4),
                            "total_R": round(float(s["r_multiple"].sum()), 4)}
    out["yearly"] = yearly
    ex2026 = dev[dev["year"] != 2026]
    if len(ex2026):
        out["ex_2026_net_pts"] = round(float(ex2026["pnl_pts"].sum()), 2)
        out["ex_2026_PF"] = round(profit_factor(ex2026["pnl_pts"]), 4)
        out["ex_2026_total_R"] = round(float(ex2026["r_multiple"].sum()), 4)
    return out


def run_one(bars, full_df, name, allow_fn, cutoff_minutes, out_dir):
    executed, skip = run_replay(bars, full_df, allow_fn, cutoff_minutes=cutoff_minutes)
    executed.to_csv(os.path.join(REPO_ROOT, out_dir, f"stage5_ledger_{name}.csv"), index=False)
    summ = summarize(executed)
    row = {"candidate": name, "cutoff_minutes": cutoff_minutes, "skip_counts": json.dumps(skip)}
    row.update({k: v for k, v in summ.items() if k != "yearly"})
    row["yearly_json"] = json.dumps(summ.get("yearly", {}))
    print(f"{name}: n={summ.get('n_trades')} net={summ.get('net_pts')} PF={summ.get('PF')} totalR={summ.get('total_R')}",
          file=sys.stderr)
    return row


def part1(bars, full_df, out_dir):
    allow_fn = lambda m: in_minute_range(m, BLOCKS["G"][0], BLOCKS["I"][1])  # 08:00-11:00
    rows = []
    for label, mins in CUTOFF_MINUTES.items():
        rows.append(run_one(bars, full_df, f"cutoff_{label.replace(':', '')}", allow_fn, mins, out_dir))
    pd.DataFrame(rows).to_csv(os.path.join(REPO_ROOT, out_dir, "stage5_part1_cutoff_sweep.csv"), index=False)


def part2(bars, full_df, out_dir, cutoff_minutes):
    rows = []
    for blocks in contiguous_windows():
        name = "contig_" + "".join(blocks)
        allow_fn = (lambda m, bl=set(blocks): in_allowed_blocks(m, bl))
        rows.append(run_one(bars, full_df, name, allow_fn, cutoff_minutes, out_dir))
    pd.DataFrame(rows).to_csv(os.path.join(REPO_ROOT, out_dir, "stage5_part2_contiguous.csv"), index=False)


def part3(bars, full_df, out_dir, cutoff_minutes):
    combos = {
        "asia_only": ASIA, "london_only": LONDON, "newyork_only": NEW_YORK,
        "asia_or_london": ASIA | LONDON, "asia_or_newyork": ASIA | NEW_YORK,
        "london_or_newyork": LONDON | NEW_YORK, "asia_or_london_or_newyork": ASIA | LONDON | NEW_YORK,
    }
    rows = []
    for name, blocks in combos.items():
        allow_fn = (lambda m, bl=blocks: in_allowed_blocks(m, bl))
        rows.append(run_one(bars, full_df, name, allow_fn, cutoff_minutes, out_dir))
    # required explicit broken-window example: 02:00-06:00 OR 09:00-11:00 (C+D+E OR H+I == london_or_newyork)
    pd.DataFrame(rows).to_csv(os.path.join(REPO_ROOT, out_dir, "stage5_part3_broken_sessions.csv"), index=False)


def part4(bars, full_df, out_dir, selected_cutoff, top5):
    """top5: dict name -> allow_fn"""
    rows = []
    ci = list(CUTOFF_MINUTES.values()).index(selected_cutoff)
    neighbor_mins = list(CUTOFF_MINUTES.values())
    neighbors = [neighbor_mins[i] for i in (ci - 1, ci, ci + 1) if 0 <= i < len(neighbor_mins)]
    for name, allow_fn in top5.items():
        for cm in neighbors:
            rows.append(run_one(bars, full_df, f"{name}_cutoff{cm}", allow_fn, cm, out_dir))
    pd.DataFrame(rows).to_csv(os.path.join(REPO_ROOT, out_dir, "stage5_part4_interaction.csv"), index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    ap.add_argument("--part", required=True, choices=["1", "2", "3", "4"])
    ap.add_argument("--cutoff-minutes", type=int, default=1319)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    full_df = build_master_with_hmm3(args.out_dir)

    if args.part == "1":
        part1(bars, full_df, args.out_dir)
    elif args.part == "2":
        part2(bars, full_df, args.out_dir, args.cutoff_minutes)
    elif args.part == "3":
        part3(bars, full_df, args.out_dir, args.cutoff_minutes)
    elif args.part == "4":
        old_1911 = lambda m: in_minute_range(m, 60, 1020)
        control_0811 = lambda m: in_minute_range(m, BLOCKS["G"][0], BLOCKS["I"][1])
        # placeholders for best contiguous / best broken -- filled in by the caller
        # after inspecting parts 2/3 results; here we always include the two fixed ones
        top5 = {"old_19_11": old_1911, "control_08_11": control_0811}
        part4(bars, full_df, args.out_dir, args.cutoff_minutes, top5)


if __name__ == "__main__":
    main()
