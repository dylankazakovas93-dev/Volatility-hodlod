#!/usr/bin/env python3
"""Stage 1 section 28: cross-model reproducibility comparison. Diffs this
run's candidate/outer-fold/perturbation tables against another model's
(e.g. Codex's) equivalent outputs, keyed on the deterministic candidate_id.
Reports the first differing signal/feature/candidate rather than
averaging or voting, per the spec.

Usage:
    python3 scripts/compare_stage1_outputs.py \
        --reference-dir outputs --comparison-dir <other_model_outputs_dir>
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

COMPARE_FILES = [
    "stage1_corrected_excursions_summary.json",
    "stage1_session_anchored_rvol_summary.json",
    "stage1_simple_all_candidates.csv",
    "stage1_learned_all_candidates.csv",
    "stage1_outer_test_results.csv",
]


def compare_csv(ref_path, cmp_path, key_col="candidate_id"):
    ref = pd.read_csv(ref_path)
    cmp = pd.read_csv(cmp_path)
    ref_keys = set(ref[key_col]) if key_col in ref.columns else set()
    cmp_keys = set(cmp[key_col]) if key_col in cmp.columns else set()
    only_ref = ref_keys - cmp_keys
    only_cmp = cmp_keys - ref_keys
    both = ref_keys & cmp_keys
    diffs = []
    if key_col in ref.columns:
        ref_idx = ref.set_index(key_col)
        cmp_idx = cmp.set_index(key_col)
        for k in sorted(both):
            r = ref_idx.loc[k]
            c = cmp_idx.loc[k]
            common_cols = [c2 for c2 in ref.columns if c2 in cmp.columns and c2 != key_col]
            for col in common_cols:
                rv, cv = r[col], c[col]
                if pd.isna(rv) and pd.isna(cv):
                    continue
                if rv != cv:
                    diffs.append({"key": k, "column": col, "reference": rv, "comparison": cv})
    return {"only_in_reference": sorted(only_ref)[:20], "only_in_comparison": sorted(only_cmp)[:20],
            "n_only_reference": len(only_ref), "n_only_comparison": len(only_cmp),
            "first_differing_rows": diffs[:20], "n_differing_rows": len(diffs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference-dir", default="outputs")
    ap.add_argument("--comparison-dir", required=True)
    args = ap.parse_args()

    for fname in COMPARE_FILES:
        ref_path = os.path.join(REPO_ROOT, args.reference_dir, fname)
        cmp_path = os.path.join(args.comparison_dir, fname)
        print(f"=== {fname} ===")
        if not os.path.exists(ref_path):
            print("  MISSING in reference dir")
            continue
        if not os.path.exists(cmp_path):
            print("  MISSING in comparison dir -- cannot compare")
            continue
        if fname.endswith(".csv"):
            result = compare_csv(ref_path, cmp_path)
            print(f"  only_in_reference: {result['n_only_reference']}")
            print(f"  only_in_comparison: {result['n_only_comparison']}")
            print(f"  differing_rows: {result['n_differing_rows']}")
            if result["first_differing_rows"]:
                print(f"  FIRST DIFFERENCE: {result['first_differing_rows'][0]}")
        else:
            with open(ref_path) as f:
                ref_txt = f.read()
            with open(cmp_path) as f:
                cmp_txt = f.read()
            print("  IDENTICAL" if ref_txt == cmp_txt else "  DIFFERS (inspect manually)")
        print()


if __name__ == "__main__":
    main()
