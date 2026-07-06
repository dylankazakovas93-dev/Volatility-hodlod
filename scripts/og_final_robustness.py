"""Final combined frozen configuration: robustness reporting + LOBYO,
build years only. Frozen params: sal_enabled=False, be_bars=60,
be_extra_lock=0.0, blocked_window=(10:00,16:00) ET, hmm_gate=None.
"""
import json
import os
import pickle
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import run_variant, filter_build_years, summarize, OG_BUILD_YEARS
from src.metrics import profit_factor, max_drawdown

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

FINAL = dict(sal_enabled=False, be_bars=60, be_extra_lock=0.0,
             blocked_window=(10 * 60, 16 * 60), hmm_gate=None)


def agg(ex_df, years):
    sub = ex_df[ex_df["year"].isin(years)]
    return summarize(sub)


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    summary, ex_full = run_variant(bars, ranges, events, **FINAL)
    build = filter_build_years(ex_full)
    build.to_csv(os.path.join(OUT, "final_frozen_build_years_trades.csv"), index=False)

    report = {"frozen_params": {**FINAL, "blocked_window_et": "10:00-16:00"}}

    # each build year separately
    report["per_year"] = {int(y): summarize(g) for y, g in build.groupby("year")}

    # aggregate excluding partial 2026
    report["excl_2026_partial"] = agg(build, {2018, 2020, 2023})

    # aggregate excluding single best build year (by net_pts)
    best_year = max(report["per_year"], key=lambda y: report["per_year"][y]["net_pts"])
    report["excl_best_year"] = {
        "excluded_year": best_year,
        "metrics": agg(build, OG_BUILD_YEARS - {best_year}),
    }

    # full-year results 2018/2020/2023 only (same as excl_2026_partial, kept explicit)
    report["full_years_2018_2020_2023"] = agg(build, {2018, 2020, 2023})

    # partial 2026 shown separately
    report["partial_2026"] = {"is_partial": True, "through": "2026-06-07",
                               "metrics": agg(build, {2026})}

    # positive build years count
    report["n_positive_build_years"] = sum(1 for y in report["per_year"]
                                            if report["per_year"][y]["net_pts"] > 0)
    report["n_build_years"] = len(report["per_year"])
    report["r_multiple_note"] = ("Engine has no R-multiple concept (no stop-risk-normalized "
                                  "field in the ledger); R sub-metrics are skipped per instructions.")

    # overall aggregate (all 4 build years)
    report["aggregate_all_build_years"] = agg(build, OG_BUILD_YEARS)

    # parameter-neighborhood stability: perturb each frozen param by one step
    neighborhood = {}
    perturbations = {
        "be_bars_45": {**FINAL, "be_bars": 45},
        "be_bars_75": {**FINAL, "be_bars": 75},
        "window_9_17": {**FINAL, "blocked_window": (9 * 60, 17 * 60)},
        "window_10.5_15.5": {**FINAL, "blocked_window": (10 * 60 + 30, 15 * 60 + 30)},
        "sal_on": {**FINAL, "sal_enabled": True},
    }
    for label, params in perturbations.items():
        s, ex = run_variant(bars, ranges, events, **params)
        by = filter_build_years(ex)
        neighborhood[label] = agg(by, OG_BUILD_YEARS)
    report["parameter_neighborhood"] = neighborhood

    with open(os.path.join(OUT, "final_robustness_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
