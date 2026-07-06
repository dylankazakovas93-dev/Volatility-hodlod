"""Stage C STEP 1 confirmation pass: bar-count BE family only, full metric set.

Holds constant: SAL off, no HMM, CANONICAL entry blackout (11:00-15:00),
target fixed at 1.0R, all signal/execution mechanics otherwise unchanged.

Candidates: no-BE, BE30, BE45, BE60, BE75, BE90 (bar-count family), plus
BE45+2pt-lock as a labeled diagnostic-only reference (NOT eligible for
selection).

Outputs:
  outputs/og_build_years/stage_c_management_complete.csv
  docs/OG_STAGE_C_MANAGEMENT_COMPLETE.md (written separately after review)
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
    "noBE":            dict(mode="none"),
    "BE30":            dict(mode="barcount", be_bars=30),
    "BE45":            dict(mode="barcount", be_bars=45),
    "BE60":            dict(mode="barcount", be_bars=60),
    "BE75":            dict(mode="barcount", be_bars=75),
    "BE90":            dict(mode="barcount", be_bars=90),
}

# NOTE: the requested "BE45+2pt-lock" diagnostic candidate (bar-count trigger
# arming a fixed +2pt lock rather than exact breakeven) is NOT representable
# with the existing simulate_managed() primitives without new engine code:
# "profit_lock" mode in src/og_management_variants.py triggers on exact-R
# (r_trigger), not on elapsed bar-count, and there is no bar-count-triggered
# point-lock mode. Per the task's instruction to reuse existing infrastructure
# and not rebuild from scratch, this diagnostic-only reference candidate is
# OMITTED here and flagged explicitly in OG_STAGE_C_MANAGEMENT_COMPLETE.md as
# not run, rather than fabricated or approximated silently.


def cap_norm_R(sub):
    return sub["pnl"] / sub["cap"]


def hold_minutes(sub):
    et = pd.to_datetime(sub["entry_time"])
    xt = pd.to_datetime(sub["exit_time"])
    return (xt - et).dt.total_seconds() / 60.0


def compute_full_metrics(label, by):
    if by is None or len(by) == 0:
        return []
    by = by.copy()
    by["cap_norm_pnl"] = cap_norm_R(by)
    by["hold_min"] = hold_minutes(by)

    rows = []

    def exit_counts(sub):
        vc = sub["exit_reason"].value_counts().to_dict()
        return {f"exit_{k}": int(v) for k, v in vc.items()}

    def m(sub, yr_label):
        n = len(sub)
        pnl = sub["pnl"]
        capR = sub["cap_norm_pnl"]
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        avg_w = float(wins.mean()) if len(wins) else 0.0
        avg_l = float(losses.mean()) if len(losses) else 0.0
        payoff = (avg_w / abs(avg_l)) if avg_l else None
        hm = sub["hold_min"]
        row = {
            "candidate": label, "year": yr_label, "n": n,
            "net_pts": round(float(pnl.sum()), 2),
            "PF_pts": round(profit_factor(pnl), 4),
            "avg_pts_per_trade": round(float(pnl.mean()), 3) if n else 0.0,
            "total_cap_norm_R": round(float(capR.sum()), 4),
            "avg_cap_norm_R": round(float(capR.mean()), 4) if n else 0.0,
            "max_dd_pts": round(max_drawdown(pnl), 2) if n else 0.0,
            "max_dd_R": round(max_drawdown(capR), 4) if n else 0.0,
            "win_rate": round(float((pnl > 0).mean()), 4) if n else 0.0,
            "avg_winner_pts": round(avg_w, 3),
            "avg_loser_pts": round(avg_l, 3),
            "payoff_ratio": round(payoff, 3) if payoff else None,
            "hold_min_median": round(float(hm.median()), 1) if n else None,
            "hold_min_mean": round(float(hm.mean()), 1) if n else None,
            "hold_min_p25": round(float(hm.quantile(0.25)), 1) if n else None,
            "hold_min_p75": round(float(hm.quantile(0.75)), 1) if n else None,
        }
        row.update(exit_counts(sub))
        return row

    for yr in sorted(by["year"].unique()):
        rows.append(m(by[by["year"] == yr], int(yr)))
    rows.append(m(by, "ALL"))
    ex2026 = by[by["year"] != 2026]
    if len(ex2026):
        rows.append(m(ex2026, "ALL_ex2026"))
    # exclude single best build year (by net pts, completed years only)
    completed = by[by["year"] != 2026]
    if len(completed) and completed["year"].nunique() > 1:
        by_year_pts = completed.groupby("year")["pnl"].sum()
        best_year = by_year_pts.idxmax()
        ex_best = by[by["year"] != best_year]
        r = m(ex_best, f"ALL_ex_best_year({int(best_year)})")
        rows.append(r)
    n_years = by["year"].nunique()
    span_years = max(1, len({2018, 2020, 2023} & set(by["year"].unique())) +
                      (1 if 2026 in set(by["year"].unique()) else 0))
    trades_per_year = round(len(by) / span_years, 2)
    for r in rows:
        r["trades_per_year_overall"] = trades_per_year
    return rows


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    import inspect
    sig = inspect.signature(run_variant_managed)
    print("run_variant_managed signature:", sig)

    all_rows = []
    for label, mgmt_kwargs in CANDIDATES.items():
        try:
            summary, ex_df = run_variant_managed(
                bars, ranges, events, mgmt_kwargs=mgmt_kwargs,
                sal_enabled=False, blocked_window=CANONICAL_WINDOW, hmm_gate=None)
        except TypeError as e:
            print(f"SKIP {label}: mgmt_kwargs not supported by run_variant_managed: {e}")
            continue
        by = filter_build_years(ex_df)
        rows = compute_full_metrics(label, by)
        all_rows.extend(rows)
        print(f"{label}: n={len(by) if by is not None else 0} "
              f"net_pts={float(by['pnl'].sum()) if by is not None and len(by) else 0:.2f}")

    df = pd.DataFrame(all_rows)
    out_path = os.path.join(OUT, "stage_c_management_complete.csv")
    df.to_csv(out_path, index=False)
    print("Wrote", out_path)
    print("Build years used:", sorted(OG_BUILD_YEARS))


if __name__ == "__main__":
    main()
