"""Phase 1 final comparison: 5 cumulative configurations, build years only.

(a) canonical OG baseline (outputs/baseline_executed.csv, unfiltered engine
    output, filtered here to OG_BUILD_YEARS for reporting)
(b) SAL-off only  (outputs/og_build_years/stage_b_SAL_off_build_years_trades.csv)
(c) SAL-off + BE60  (outputs/og_build_years/stage_c_complete_BE60_build_years_trades.csv)
(d) SAL-off + BE60 + blocked-10:00-15:00
    (outputs/og_build_years/stage_e_complete_blocked_1000_until1500_build_years_trades.csv)
(e) SAL-off + BE60 + blocked-10:00-15:00 + target-1.50R (FINAL)
    (outputs/og_build_years/stage_f_laneB_be60_rr150_build_years_trades.csv)

DATA FIREWALL: build years only {2018, 2020, 2023, 2026-partial}.
"""
import json
import os

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")
BUILD_YEARS = {2018, 2020, 2023, 2026}

CONFIGS = {
    "a_canonical_baseline": os.path.join(REPO_ROOT, "outputs", "baseline_executed.csv"),
    "b_sal_off": os.path.join(OUT, "stage_b_SAL_off_build_years_trades.csv"),
    "c_sal_off_be60": os.path.join(OUT, "stage_c_complete_BE60_build_years_trades.csv"),
    "d_plus_window_10_15": os.path.join(OUT, "stage_e_complete_blocked_1000_until1500_build_years_trades.csv"),
    "e_final_plus_rr150": os.path.join(OUT, "stage_f_laneB_be60_rr150_build_years_trades.csv"),
}


def load(path):
    df = pd.read_csv(path, parse_dates=["entry_time", "exit_time"])
    df = df[df["year"].isin(BUILD_YEARS)].copy()
    df["cap_norm_pnl"] = df["pnl"] / df["cap"]
    return df


def max_dd(series):
    cum = series.cumsum()
    peak = cum.cummax()
    dd = cum - peak
    return float(dd.min()) if len(dd) else 0.0


def pf(series):
    pos = series[series > 0].sum()
    neg = -series[series < 0].sum()
    if neg == 0:
        return float("inf") if pos > 0 else 1.0
    return float(pos / neg)


def metrics_for(df):
    if df is None or len(df) == 0:
        return {"n": 0}
    pnl = df["pnl"]
    capr = df["cap_norm_pnl"]
    return {
        "n": int(len(df)),
        "net_pts": round(float(pnl.sum()), 2),
        "PF_pts": round(pf(pnl), 4),
        "total_cap_norm_R": round(float(capr.sum()), 4),
        "avg_cap_norm_R_per_trade": round(float(capr.mean()), 4) if len(df) else 0.0,
        "max_dd_pts": round(max_dd(pnl), 2),
        "max_dd_R": round(max_dd(capr), 4),
    }


def main():
    results = {}
    for label, path in CONFIGS.items():
        df = load(path)
        row = {"ALL": metrics_for(df)}
        for yr in sorted(BUILD_YEARS):
            row[str(yr)] = metrics_for(df[df["year"] == yr])
        ex2026 = df[df["year"] != 2026]
        row["ALL_ex2026"] = metrics_for(ex2026)
        if len(df):
            yearly_net = df.groupby("year")["pnl"].sum()
            best_year = int(yearly_net.idxmax())
            ex_best = df[df["year"] != best_year]
            row[f"ALL_ex_best_year({best_year})"] = metrics_for(ex_best)
            row["best_year"] = best_year
        results[label] = row

    with open(os.path.join(OUT, "phase1_final_comparison.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    for label, row in results.items():
        print(f"\n=== {label} ===")
        for k, v in row.items():
            print(k, v)


if __name__ == "__main__":
    main()
