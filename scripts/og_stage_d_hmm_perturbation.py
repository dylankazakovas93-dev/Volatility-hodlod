"""Stage D perturbation/seed-stability validation for the most promising
HMM candidate(s) identified by scripts/og_stage_d_hmm_full.py's primary run
(window=120, seed=42). Re-runs regime fitting + gate evaluation at:
  - training windows 80, 100 (in addition to the primary 120)
  - seeds 0, 1, 42, 123, 2024 (at the primary window=120)
for a small set of explicitly named candidates (n_states, state/exclude
target, threshold) passed on the command line via CANDIDATES below.
"""
import csv
import json
import os
import pickle
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import run_variant, filter_build_years, summarize, OG_BUILD_YEARS
from src.og_hmm_gate import build_5m_features, causal_session_regime_probs, make_gate

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

FROZEN = dict(sal_enabled=False, be_bars=60, be_extra_lock=0.0,
              blocked_window=(11 * 60, 15 * 60))

# Each candidate: (name, n_states, kwargs-to-make_gate minus regime_df, threshold)
# Filled in by the orchestrating call based on the primary sweep's best candidate(s).
CANDIDATES = json.loads(os.environ.get("STAGE_D_PERTURB_CANDIDATES", "[]"))

WINDOWS = [80, 100, 120]
SEEDS = [0, 1, 42, 123, 2024]


def run_one(feat, target_sessions, n_states, window, seed, gate_kwargs, threshold):
    regime_df, meta = causal_session_regime_probs(
        feat, target_sessions, n_states=n_states,
        min_sessions=20, max_sessions=window, random_state=seed)
    gate = make_gate(regime_df, threshold=threshold, **gate_kwargs)
    summary, ex_df = run_variant(bars, ranges, events, hmm_gate=gate, **FROZEN)
    by = filter_build_years(ex_df)
    agg = summarize(by)
    per_year = {int(y): summarize(g) for y, g in by.groupby("year")} if len(by) else {}
    return agg, per_year, meta


if __name__ == "__main__":
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]
    touched = [e for e in events if e["touched_at"] is not None]
    target_sessions = sorted({e["session_date"].strftime("%Y-%m-%d") for e in touched
                               if e["session_date"].year in OG_BUILD_YEARS})
    feat = build_5m_features(bars)

    if not CANDIDATES:
        print("No candidates supplied via STAGE_D_PERTURB_CANDIDATES env var. Exiting.")
        sys.exit(0)

    results = []
    for cand in CANDIDATES:
        name = cand["name"]
        n_states = cand["n_states"]
        gate_kwargs = {k: v for k, v in cand.items() if k in ("state_idx", "exclude_idx")}
        threshold = cand["threshold"]

        for w in WINDOWS:
            t0 = time.time()
            agg, per_year, meta = run_one(feat, target_sessions, n_states, w, 42, gate_kwargs, threshold)
            dt = time.time() - t0
            print(f"[window-perturb] {name} window={w} seed=42 -> n={agg.get('n')} PF={agg.get('PF')} ({dt:.1f}s)")
            results.append({"candidate": name, "perturbation": "window", "window": w, "seed": 42,
                             **{k: agg.get(k) for k in ("n", "net_pts", "PF", "win_rate", "avg_trade", "max_drawdown")},
                             "per_year": per_year})

        for s in SEEDS:
            t0 = time.time()
            agg, per_year, meta = run_one(feat, target_sessions, n_states, 120, s, gate_kwargs, threshold)
            dt = time.time() - t0
            print(f"[seed-perturb] {name} window=120 seed={s} -> n={agg.get('n')} PF={agg.get('PF')} ({dt:.1f}s)")
            results.append({"candidate": name, "perturbation": "seed", "window": 120, "seed": s,
                             **{k: agg.get(k) for k in ("n", "net_pts", "PF", "win_rate", "avg_trade", "max_drawdown")},
                             "per_year": per_year})

    with open(os.path.join(OUT, "stage_d_hmm_perturbation.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("Wrote outputs/og_build_years/stage_d_hmm_perturbation.json")
