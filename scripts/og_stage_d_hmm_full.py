"""Stage D full causal HMM regime-gate matrix (build years only).

Holds constant: SAL off (Stage B), be_bars=60 (Stage C provisional pick),
CANONICAL 11:00-15:00 entry restriction (isolates the HMM-gate variable,
not Stage E's RESEARCH_ENTRY_BLACKOUT_10_16), PROP_HARD_BLACKOUT (automatic,
unconditional in og_build_variant_engine.run_variant).

Runs the 2-state and 3-state candidate matrix at the PRIMARY config
(training window = 120 sessions, seed = 42), both confidence thresholds
(0.55, 0.65) for every real gate candidate, plus the no-gate controls.
Perturbation (window 80/100, seeds 0/1/123/2024) is run separately in
scripts/og_stage_d_hmm_perturbation.py for the candidate(s) selected here as
"not obviously dead".
"""
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

STATE_LABELS = {2: {0: "LOW", 1: "HIGH"}, 3: {0: "LOW", 1: "MID", 2: "HIGH"}}
THRESHOLDS = [0.55, 0.65]


def candidates_for(n_states, regime_df):
    labels = STATE_LABELS[n_states]
    cands = {}
    for idx, name in labels.items():
        for thr in THRESHOLDS:
            cands[f"hmm{n_states}_{name}_only_p{int(thr*100)}"] = make_gate(
                regime_df, state_idx=idx, threshold=thr)
        if n_states == 3:
            for thr in THRESHOLDS:
                cands[f"hmm{n_states}_exclude_{name}_p{int(thr*100)}"] = make_gate(
                    regime_df, exclude_idx=idx, threshold=thr)
    cands[f"hmm{n_states}_no_gate"] = None
    return cands


def state_occupancy_by_year(regime_df, n_states):
    df = regime_df.copy()
    df["year"] = [s.year for s in df["session"]]
    argmax_col = df[[f"state_prob_{j}" for j in range(n_states)]].values.argmax(axis=1)
    df["argmax"] = argmax_col
    labels = STATE_LABELS[n_states]
    out = {}
    for y, g in df.groupby("year"):
        n = len(g)
        out[int(y)] = {labels[j]: round(float((g["argmax"] == j).mean()), 4) for j in range(n_states)}
    return out


def transition_frequency(regime_df, n_states):
    df = regime_df.sort_index()
    argmax_col = df[[f"state_prob_{j}" for j in range(n_states)]].values.argmax(axis=1)
    # only count transitions within the same session (bar-to-bar, causal)
    sessions = df["session"].values
    trans = {}
    for i in range(1, len(argmax_col)):
        if sessions[i] != sessions[i - 1]:
            continue
        key = f"{argmax_col[i-1]}->{argmax_col[i]}"
        trans[key] = trans.get(key, 0) + 1
    total = sum(trans.values())
    return {k: round(v / total, 5) for k, v in trans.items()} if total else {}


def main(n_states_list=(2, 3), window=120, seed=42, min_sessions=20, tag="primary"):
    t_all = time.time()
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    touched = [e for e in events if e["touched_at"] is not None]
    target_sessions = sorted({e["session_date"] for e in touched
                               if e["session_date"].year in OG_BUILD_YEARS})
    print(f"[{tag}] target sessions (build years, touch-bearing): {len(target_sessions)}")

    print(f"[{tag}] building 5-min causal features...")
    feat = build_5m_features(bars)

    all_rows = []
    full_results = {}
    for n_states in n_states_list:
        t0 = time.time()
        print(f"[{tag}] fitting session-refit HMM, n_states={n_states}, window={window}, seed={seed} ...")
        regime_df, meta = causal_session_regime_probs(
            feat, target_sessions, n_states=n_states,
            min_sessions=min_sessions, max_sessions=window, random_state=seed)
        print(f"[{tag}] n_states={n_states} fit done in {time.time()-t0:.1f}s; meta={meta}")

        occ = state_occupancy_by_year(regime_df, n_states)
        trans = transition_frequency(regime_df, n_states)

        cands = candidates_for(n_states, regime_df)
        for label, gate in cands.items():
            summary, ex_df = run_variant(bars, ranges, events, hmm_gate=gate, **FROZEN)
            by = filter_build_years(ex_df)
            by.to_csv(os.path.join(OUT, f"stage_d_{tag}_{label}_build_years_trades.csv"), index=False)
            agg = summarize(by)
            per_year = {int(y): summarize(g) for y, g in by.groupby("year")}
            ex_2026 = filter_build_years(ex_df, years={2018, 2020, 2023})
            agg_ex2026 = summarize(ex_2026)

            raw_touches_in_gate_scope = summary["total_physical_touches"]
            allowed_pct_by_year = {}
            if len(by):
                for y in sorted(OG_BUILD_YEARS):
                    ytouch = [e for e in touched if e["session_date"].year == y]
                    allowed_pct_by_year[y] = round(len(by[by["year"] == y]) / max(1, len(ytouch)), 4)

            full_results[label] = {
                "n_states": n_states, "window": window, "seed": seed,
                "build_years_summary": agg,
                "ex_2026_summary": agg_ex2026,
                "per_year": per_year,
                "skipped_hmm_gate": summary.get("skipped_hmm_gate", 0),
                "state_occupancy_by_year": occ,
                "transition_frequency": trans,
                "hmm_meta": meta,
                "allowed_pct_by_year": allowed_pct_by_year,
            }
            row = {"candidate": label, "n_states": n_states, "window": window, "seed": seed,
                   "n": agg.get("n", 0), "net_pts": agg.get("net_pts"), "PF": agg.get("PF"),
                   "win_rate": agg.get("win_rate"), "avg_trade": agg.get("avg_trade"),
                   "max_drawdown": agg.get("max_drawdown"),
                   "PF_ex2026": agg_ex2026.get("PF"), "net_pts_ex2026": agg_ex2026.get("net_pts"),
                   "n_ex2026": agg_ex2026.get("n", 0)}
            all_rows.append(row)
            print(f"  {label}: n={row['n']} net_pts={row['net_pts']} PF={row['PF']}")

    import csv
    csv_path = os.path.join(OUT, f"stage_d_hmm_candidates_{tag}.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)

    with open(os.path.join(OUT, f"stage_d_hmm_full_results_{tag}.json"), "w") as f:
        json.dump(full_results, f, indent=2, default=str)

    print(f"[{tag}] TOTAL TIME {time.time()-t_all:.1f}s")
    print(f"[{tag}] wrote {csv_path}")


if __name__ == "__main__":
    main()
