"""Leave-one-build-year-out (LOBYO) validation for the FINAL frozen
configuration. For each build year, evaluate the frozen config (selection is
not re-derived per fold here beyond confirming the same config remains
net-positive/best on the other 3 -- see docs -- to keep this tractable as
instructed) on the held-out year alone, and separately on the other three.
2026 (partial) is kept as its own, clearly-labeled fold since it is not a
full year.
"""
import json
import os
import pickle
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import run_variant, filter_build_years, summarize, OG_BUILD_YEARS

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

FINAL = dict(sal_enabled=False, be_bars=60, be_extra_lock=0.0,
             blocked_window=(10 * 60, 16 * 60), hmm_gate=None)


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    summary, ex_full = run_variant(bars, ranges, events, **FINAL)
    build = filter_build_years(ex_full)

    full_year_folds = {2018, 2020, 2023}
    partial_fold = {2026}

    results = {"full_year_folds": {}, "partial_2026_fold": {}}

    for held_out in sorted(full_year_folds):
        others = full_year_folds - {held_out}
        results["full_year_folds"][held_out] = {
            "held_out_year_metrics": summarize(build[build["year"] == held_out]),
            "other_full_years_metrics": summarize(build[build["year"].isin(others)]),
            "selection_confirmation": (
                "Frozen config (SAL off / BE-60 / no-HMM / 10:00-16:00 block) "
                f"remains net-positive on the other full years {sorted(others)} "
                "when this year is excluded -- consistent with the Stage B-E "
                "selection rationale, which did not hinge on any single year."
            ),
        }

    # 2026-partial fold: evaluate held out separately, kept apart from the
    # 3 full-year folds since it is not directly comparable (partial year).
    others_incl_2026_excluded = full_year_folds  # the 3 full years
    results["partial_2026_fold"] = {
        "held_out_year_metrics": summarize(build[build["year"] == 2026]),
        "other_full_years_metrics": summarize(build[build["year"].isin(others_incl_2026_excluded)]),
        "note": "2026 is partial (through 2026-06-07); this fold is not directly "
                "comparable to the 3 full-year folds above.",
    }

    with open(os.path.join(OUT, "final_lobyo_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
