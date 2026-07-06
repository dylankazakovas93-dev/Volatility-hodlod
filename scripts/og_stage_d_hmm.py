"""Stage D: HMM regime-gate candidates, build years only. Carries forward
Stage B (sal_enabled=False) and Stage C (be_bars=60) freezes.
"""
import json
import os
import pickle
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import run_variant, filter_build_years, summarize, OG_BUILD_YEARS
from src.og_hmm_gate import build_causal_regime_series, make_hmm_gate

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

FROZEN = dict(sal_enabled=False, be_bars=60, be_extra_lock=0.0)


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    print("Fitting causal walk-forward 2-state HMM regime series (input feature only)...")
    regime = build_causal_regime_series(bars)
    regime.to_csv(os.path.join(OUT, "stage_d_regime_series.csv"))

    candidates = {
        "no_hmm": None,
        "hmm_state0": make_hmm_gate(regime, target_state=0),
        "hmm_state1": make_hmm_gate(regime, target_state=1),
    }

    results = {}
    for label, gate in candidates.items():
        summary, ex_df = run_variant(bars, ranges, events, hmm_gate=gate, **FROZEN)
        by = filter_build_years(ex_df)
        by.to_csv(os.path.join(OUT, f"stage_d_{label}_build_years_trades.csv"), index=False)
        results[label] = {
            "build_years_summary": summarize(by),
            "per_year": {int(y): summarize(g) for y, g in by.groupby("year")},
        }

    with open(os.path.join(OUT, "stage_d_hmm_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps({k: v["build_years_summary"] for k, v in results.items()}, indent=2))
    print("\nBuild years used:", sorted(OG_BUILD_YEARS))


if __name__ == "__main__":
    main()
