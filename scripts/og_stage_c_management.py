"""Stage C: management (BE/exit-management) candidates, build years only.
Carries forward the Stage B freeze: sal_enabled=False.
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

CANDIDATES = {
    "BE45_lock0":  dict(be_bars=45, be_extra_lock=0.0),   # canonical BE-45, baseline candidate
    "BE30_lock0":  dict(be_bars=30, be_extra_lock=0.0),   # earlier BE trigger
    "BE60_lock0":  dict(be_bars=60, be_extra_lock=0.0),   # later BE trigger
    "BE45_lock2":  dict(be_bars=45, be_extra_lock=2.0),   # BE-45 + 2pt profit lock beyond entry
}


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    results = {}
    for label, params in CANDIDATES.items():
        summary, ex_df = run_variant(bars, ranges, events, sal_enabled=False, **params)
        by = filter_build_years(ex_df)
        by.to_csv(os.path.join(OUT, f"stage_c_{label}_build_years_trades.csv"), index=False)
        results[label] = {
            "params": params,
            "build_years_summary": summarize(by),
            "per_year": {int(y): summarize(g) for y, g in by.groupby("year")},
        }

    with open(os.path.join(OUT, "stage_c_management_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps({k: v["build_years_summary"] for k, v in results.items()}, indent=2))
    print("\nBuild years used:", sorted(OG_BUILD_YEARS))


if __name__ == "__main__":
    main()
