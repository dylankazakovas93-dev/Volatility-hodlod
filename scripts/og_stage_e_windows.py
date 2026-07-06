"""Stage E: entry-window/cutoff variants, build years only. Carries forward
Stage B (sal_enabled=False), Stage C (be_bars=60), Stage D (no HMM gate).
Canonical blocked window is 11:00-15:00 ET (entry_allowed blocks that span).
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

FROZEN = dict(sal_enabled=False, be_bars=60, be_extra_lock=0.0, hmm_gate=None)

CANDIDATES = {
    "canonical_11_15":  (11 * 60, 15 * 60),   # canonical: blocked 11:00-15:00 ET
    "RESEARCH_ENTRY_BLACKOUT_10_16": (10 * 60, 16 * 60),  # research-selected blocked ENTRY interval: entries blocked from 10:00 ET (not a "10:00-16:00 trading window")
    "narrower_12_14":   (12 * 60, 14 * 60),   # narrower blocked window (more permissive entry)
    "shifted_11_16":    (11 * 60, 16 * 60),   # shifted/extended block into the close
}


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    results = {}
    for label, window in CANDIDATES.items():
        summary, ex_df = run_variant(bars, ranges, events, blocked_window=window, **FROZEN)
        by = filter_build_years(ex_df)
        by.to_csv(os.path.join(OUT, f"stage_e_{label}_build_years_trades.csv"), index=False)
        results[label] = {
            "blocked_window": window,
            "build_years_summary": summarize(by),
            "per_year": {int(y): summarize(g) for y, g in by.groupby("year")},
        }

    with open(os.path.join(OUT, "stage_e_windows_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps({k: v["build_years_summary"] for k, v in results.items()}, indent=2))
    print("\nBuild years used:", sorted(OG_BUILD_YEARS))


if __name__ == "__main__":
    main()
