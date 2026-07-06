"""Stage B: SAL on vs off, build years only (2018/2020/2023/2026)."""
import json
import os
import pickle
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import run_variant, filter_build_years, summarize, OG_BUILD_YEARS

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    results = {}
    for label, sal in (("SAL_on", True), ("SAL_off", False)):
        summary, ex_df = run_variant(bars, ranges, events, sal_enabled=sal)
        by = filter_build_years(ex_df)
        by.to_csv(os.path.join(OUT, f"stage_b_{label}_build_years_trades.csv"), index=False)
        results[label] = {
            "build_years_summary": summarize(by),
            "per_year": {int(y): summarize(g) for y, g in by.groupby("year")},
        }

    with open(os.path.join(OUT, "stage_b_sal_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))
    print("\nBuild years used:", sorted(OG_BUILD_YEARS))


if __name__ == "__main__":
    main()
