"""Stage C full preregistered management-family sweep, build years only.

Holds constant: sal_enabled=False (Stage B freeze), CANONICAL 11:00-15:00
blocked entry window (NOT the Stage E RESEARCH_ENTRY_BLACKOUT_10_16 -- Stage
C isolates the management variable in isolation), no HMM gate,
PROP_HARD_BLACKOUT always on (unconditional in the shared engine path).

20 candidates: 2 controls + 5 bar-count BE + 4 exact-R BE + 3 profit-lock +
4 time-based conditional BE + 2 scratch-on-recovery.

Outputs:
  outputs/og_build_years/stage_c_full_sweep_results.csv   (one row per
    candidate x year, plus an "ALL" aggregate row and "ALL_ex2026" row)
  outputs/og_build_years/stage_c_full_sweep_summary.json  (raw per-candidate
    executed trades summary + per-year breakdown, nested)
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import filter_build_years, OG_BUILD_YEARS
from src.og_management_variants import run_variant_managed
from src.metrics import profit_factor, max_drawdown

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

CANONICAL_WINDOW = (11 * 60, 15 * 60)

CANDIDATES = {
    # --- controls
    "ctrl_BE45":        dict(mode="barcount", be_bars=45),
    "ctrl_noBE":        dict(mode="none"),
    # --- bar-count BE
    "bc_BE30":          dict(mode="barcount", be_bars=30),
    "bc_BE45":          dict(mode="barcount", be_bars=45),
    "bc_BE60":          dict(mode="barcount", be_bars=60),
    "bc_BE75":          dict(mode="barcount", be_bars=75),
    "bc_BE90":          dict(mode="barcount", be_bars=90),
    # --- exact-R BE
    "exr_050":          dict(mode="exact_r", r_trigger=0.50),
    "exr_075":          dict(mode="exact_r", r_trigger=0.75),
    "exr_100":          dict(mode="exact_r", r_trigger=1.00),
    "exr_125":          dict(mode="exact_r", r_trigger=1.25),
    # --- profit lock
    "lock_075_010":     dict(mode="profit_lock", r_trigger=0.75, lock_r=0.10),
    "lock_100_010":     dict(mode="profit_lock", r_trigger=1.00, lock_r=0.10),
    "lock_125_010":     dict(mode="profit_lock", r_trigger=1.25, lock_r=0.10),
    # --- time-based conditional BE
    "time_30":          dict(mode="time_be", minutes_elapsed=30, mfe_r=0.25),
    "time_45":          dict(mode="time_be", minutes_elapsed=45, mfe_r=0.25),
    "time_60":          dict(mode="time_be", minutes_elapsed=60, mfe_r=0.25),
    "time_75":          dict(mode="time_be", minutes_elapsed=75, mfe_r=0.25),
    # --- scratch on recovery
    "scratch_050":      dict(mode="scratch", adverse_r=0.50),
    "scratch_075":      dict(mode="scratch", adverse_r=0.75),
}


def compute_full_metrics(label, ex_df_all_years):
    """ex_df_all_years: executed trades filtered to OG_BUILD_YEARS already."""
    by = ex_df_all_years
    if by is None or len(by) == 0:
        return None

    by = by.copy()
    by["cap_norm_pnl"] = by["pnl"] / by["cap"]

    rows = []

    def yr_metrics(sub, yr_label):
        n = len(sub)
        pnl = sub["pnl"]
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        avg_w = float(wins.mean()) if len(wins) else 0.0
        avg_l = float(losses.mean()) if len(losses) else 0.0
        payoff = (avg_w / abs(avg_l)) if avg_l != 0 else float("inf")
        return {
            "candidate": label, "year": yr_label, "n": n,
            "net_pts": round(float(pnl.sum()), 2),
            "PF": round(profit_factor(pnl), 4),
            "avg_pts_per_trade": round(float(pnl.mean()), 3) if n else 0.0,
            "median_pts_per_trade": round(float(pnl.median()), 3) if n else 0.0,
            "avg_winner_pts": round(avg_w, 3),
            "avg_loser_pts": round(avg_l, 3),
            "payoff_ratio": round(payoff, 3) if payoff != float("inf") else None,
            "max_drawdown": round(max_drawdown(pnl), 2) if n else 0.0,
            "avg_cap_norm_pnl": round(float(sub["cap_norm_pnl"].mean()), 4) if n else 0.0,
            "pct_of_pooled_net_pts": None,  # filled in below for per-year rows
        }

    total_net = float(by["pnl"].sum())
    for yr in sorted(by["year"].unique()):
        sub = by[by["year"] == yr]
        m = yr_metrics(sub, int(yr))
        m["pct_of_pooled_net_pts"] = round(100.0 * float(sub["pnl"].sum()) / total_net, 2) if total_net != 0 else None
        rows.append(m)

    rows.append(yr_metrics(by, "ALL"))

    ex2026 = by[by["year"] != 2026]
    if len(ex2026):
        rows.append(yr_metrics(ex2026, "ALL_ex2026"))

    return rows


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    all_rows = []
    raw_summaries = {}

    for label, mgmt_kwargs in CANDIDATES.items():
        summary, ex_df = run_variant_managed(
            bars, ranges, events, mgmt_kwargs=mgmt_kwargs,
            sal_enabled=False, blocked_window=CANONICAL_WINDOW, hmm_gate=None)
        by = filter_build_years(ex_df)
        by.to_csv(os.path.join(OUT, f"stage_c_{label}_build_years_trades.csv"), index=False)

        rows = compute_full_metrics(label, by)
        if rows:
            all_rows.extend(rows)
        raw_summaries[label] = {
            "mgmt_kwargs": mgmt_kwargs,
            "n_all_touches_summary": summary,
            "build_year_n": int(len(by)) if by is not None else 0,
        }
        print(f"{label}: n={len(by) if by is not None else 0} "
              f"net_pts={float(by['pnl'].sum()) if by is not None and len(by) else 0:.2f}")

    df = pd.DataFrame(all_rows)
    df.to_csv(os.path.join(OUT, "stage_c_full_sweep_results.csv"), index=False)

    with open(os.path.join(OUT, "stage_c_full_sweep_raw_summary.json"), "w") as f:
        json.dump(raw_summaries, f, indent=2, default=str)

    print("\nWrote:", os.path.join(OUT, "stage_c_full_sweep_results.csv"))
    print("Build years used:", sorted(OG_BUILD_YEARS))


if __name__ == "__main__":
    main()
