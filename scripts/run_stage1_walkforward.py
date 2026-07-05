#!/usr/bin/env python3
"""Stage 1 sections 15-16: expanding-window outer walk-forward selection
for the 980 preregistered simple candidates.

Because every simple candidate is a FIXED (scale, gamma, a, b) rule (no
fitting), its full 2018-2025 chronological replay does not change across
outer folds -- only which years count as "training" (for candidate
selection) vs. "test" (frozen, evaluate-once) changes. So candidate
selection uses each fold's training-year subset of the SAME per-year
metrics already computed by run_stage1_simple_surface.py, and "freezing"
a formula simply means reading off its already-computed test-year row --
no re-simulation is needed or performed per fold.

Outer folds (year to test): 2021, 2022, 2023, 2024, 2025. 2026 is never
used for selection (diagnostic only, handled separately).

Robust-neighborhood selection (section 16): for each fold and each base
scale, build a graph over the preregistered (gamma, a, b) grid restricted
to candidates that are profitable (training-period net_pts > 0) in that
fold's training years; two candidates are neighbours if they differ by
exactly one adjacent preregistered step in exactly one of {gamma, a, b}
while sharing the same scale. Connected components are "neighbourhoods".
Rank neighbourhoods by (median training PF, then size), pick the top one,
then choose its medoid (candidate minimizing total normalized grid
distance to the rest of the neighbourhood).

Usage:
    python3 scripts/run_stage1_walkforward.py --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

GAMMAS = [-0.30, -0.15, 0.00, 0.15, 0.30]
MULTS = [0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00]
SCALES = ["S1_range30m", "S2_atr60m", "S3_prevsessrange", "S4_geomean"]
FOLDS = [
    (list(range(2018, 2021)), 2021),
    (list(range(2018, 2022)), 2022),
    (list(range(2018, 2023)), 2023),
    (list(range(2018, 2024)), 2024),
    (list(range(2018, 2025)), 2025),
]


def yearly_agg(yearly_json, years):
    ys = json.loads(yearly_json)
    sub = [y for y in ys if y["year"] in years]
    if not sub:
        return None
    net = sum(y["net_pts"] for y in sub)
    n = sum(y["n"] for y in sub)
    avg_r = np.average([y["avg_R"] for y in sub], weights=[y["n"] for y in sub]) if n else None
    gains = sum(y["net_pts"] for y in sub if y["net_pts"] > 0)
    losses = sum(-y["net_pts"] for y in sub if y["net_pts"] < 0)
    pf = gains / losses if losses > 0 else (float("inf") if gains > 0 else None)
    return {"net_pts": net, "n": n, "avg_R": avg_r, "PF": pf,
            "n_profitable_years": sum(1 for y in sub if y["net_pts"] > 0),
            "n_years": len(sub),
            "min_year_net": min(y["net_pts"] for y in sub)}


def neighbor_key(gamma, a, b):
    return (GAMMAS.index(gamma), MULTS.index(a), MULTS.index(b))


def find_neighborhoods(candidate_keys):
    """candidate_keys: set of (gi, ai, bi) index tuples. Returns list of
    connected components (each a list of index tuples), connecting keys
    that differ by 1 in exactly one coordinate."""
    keys = set(candidate_keys)
    visited = set()
    components = []
    for start in keys:
        if start in visited:
            continue
        stack = [start]
        comp = []
        visited.add(start)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            gi, ai, bi = cur
            neighbors = [
                (gi + 1, ai, bi), (gi - 1, ai, bi),
                (gi, ai + 1, bi), (gi, ai - 1, bi),
                (gi, ai, bi + 1), (gi, ai, bi - 1),
            ]
            for nb in neighbors:
                if nb in keys and nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        components.append(comp)
    return components


def medoid(comp):
    arr = np.array(comp, dtype=float)
    dists = np.zeros(len(comp))
    for i in range(len(comp)):
        dists[i] = np.linalg.norm(arr - arr[i], axis=1).sum()
    return comp[int(np.argmin(dists))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    cand = pd.read_csv(os.path.join(out_dir, "stage1_simple_all_candidates.csv"))

    neighborhood_rows = []
    outer_test_rows = []

    for scale in SCALES:
        scale_cand = cand[cand["scale"] == scale].copy()
        for train_years, test_year in FOLDS:
            train_metrics = scale_cand["yearly_json"].apply(lambda j: yearly_agg(j, train_years))
            scale_cand["_train"] = train_metrics
            profitable = scale_cand[scale_cand["_train"].apply(lambda m: m is not None and m["net_pts"] > 0)]
            if profitable.empty:
                continue
            key_to_row = {}
            keys = []
            for _, row in profitable.iterrows():
                k = neighbor_key(row["gamma"], row["a_tp_mult"], row["b_sl_mult"])
                key_to_row[k] = row
                keys.append(k)
            components = find_neighborhoods(keys)

            comp_stats = []
            for comp in components:
                rows_c = [key_to_row[k] for k in comp]
                pfs = [r["_train"]["PF"] for r in rows_c if r["_train"]["PF"] not in (None, float("inf"))]
                avg_rs = [r["_train"]["avg_R"] for r in rows_c]
                worst_years = [r["_train"]["min_year_net"] for r in rows_c]
                comp_stats.append({
                    "scale": scale, "test_year": test_year, "n_candidates": len(comp),
                    "median_pf": float(np.median(pfs)) if pfs else None,
                    "min_pf": float(np.min(pfs)) if pfs else None,
                    "median_avg_r": float(np.median(avg_rs)),
                    "worst_year_net": float(np.min(worst_years)),
                    "pct_profitable": 100.0,
                    "_comp": comp,
                })

            comp_stats.sort(key=lambda c: (-(c["median_pf"] or 0), -c["n_candidates"]))
            best = comp_stats[0]
            neighborhood_rows.append({k: v for k, v in best.items() if k != "_comp"})

            med_key = medoid(best["_comp"])
            gi, ai, bi = med_key
            chosen = key_to_row[med_key]
            outer_test_rows.append({
                "scale": scale, "test_year": test_year,
                "candidate_id": chosen["candidate_id"],
                "gamma": GAMMAS[gi], "a_tp_mult": MULTS[ai], "b_sl_mult": MULTS[bi],
                "train_years": str(train_years),
                "train_PF": best["median_pf"],
                **{f"test_{k}": v for k, v in (yearly_agg(chosen["yearly_json"], [test_year]) or {}).items()},
            })

    pd.DataFrame(neighborhood_rows).to_csv(os.path.join(out_dir, "stage1_neighbourhoods.csv"), index=False)
    outer_df = pd.DataFrame(outer_test_rows)
    outer_df.to_csv(os.path.join(out_dir, "stage1_outer_test_results.csv"), index=False)

    print(outer_df.to_string())


if __name__ == "__main__":
    main()
