"""Genuine leave-one-build-year-out (LOBYO) validation, all 5 stages
(B/C/D/E/F). Supersedes scripts/og_lobyo.py (a PSEUDO-LOBYO that evaluated
one fixed final config per year rather than re-selecting per fold).

For each stage and each held-out year in {2018, 2020, 2023, partial-2026}:
  1. Exclude that year's outcome data entirely.
  2. Rank/select that stage's candidates using ONLY the remaining 3 build
     years, using that stage's own preregistered objective.
  3. Freeze the fold-specific winner.
  4. Evaluate that fold winner ONLY on the held-out year.
  5. Record which candidate won.

This reuses PER-YEAR breakdowns that were already computed once (per
candidate, across ALL build years) by the stage-complete scripts
(scripts/og_stage_{b,c,e,f}_*.py) and the Stage D full-matrix script
(scripts/og_stage_d_hmm_full.py) / docs/OG_STAGE_D_HMM.md. No candidate here
is a function OF the held-out year -- each candidate's per-year outcome was
computed once, independently, by the original stage engines directly from
trade-level simulation (not fit on aggregated statistics), so slicing that
existing per-year table into "other 3 years" vs "held-out year" for
selection purposes is equivalent to re-running the candidate on the 3-year
subset only: none of these candidates (SAL on/off, BE-bars, blocked-window
start, target_r) are FIT to the data in any way that could leak the held-out
year's information back through the aggregate -- each is a fixed, externally
specified simulation parameter evaluated independently on each trade/year.

Stage D is explicitly handled as an approximation per the task spec: rather
than re-fitting the causal, session-refit HMM 4 times (once per fold), we
use the ALREADY-COMPUTED per-year breakdown for the reduced candidate set
{no_gate (control), hmm3_HIGH_only_p55, hmm3_exclude_MID_p55} to rank/select
per fold and look up the same candidate's held-out-year performance. This is
called out explicitly, both here and in docs/OG_GENUINE_LOBYO.md.

Outputs:
  outputs/og_build_years/genuine_lobyo_results.json
  docs/OG_GENUINE_LOBYO.md (written separately, human-authored summary)
"""
import json
import os

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

FULL_YEARS = [2018, 2020, 2023]
ALL_FOLD_YEARS = [2018, 2020, 2023, 2026]


def pf(pos_sum, neg_sum_abs):
    if neg_sum_abs == 0:
        return float("inf") if pos_sum > 0 else 1.0
    return pos_sum / neg_sum_abs


# ---------------------------------------------------------------------------
# STAGE B: SAL on / off. Per-year net_pts/PF from docs/OG_STAGE_B_SAL.md /
# outputs/og_build_years/stage_b_sal_results.json.
# ---------------------------------------------------------------------------
def load_stage_b():
    with open(os.path.join(OUT, "stage_b_sal_results.json")) as f:
        raw = json.load(f)
    data = {}
    for cand in ("SAL_on", "SAL_off"):
        per_year = raw[cand]["per_year"]
        data[cand] = {int(y): m for y, m in per_year.items()}
    return data


def stage_b_objective(cand_year_metrics, years):
    """Stage B's actual selection standard (docs/OG_STAGE_B_SAL.md): highest
    aggregate net_pts and PF, and flips more years positive. We reduce this
    to a single sortable score = (n_positive_years, aggregate_net_pts) since
    that is what actually discriminated SAL_on vs SAL_off in the original
    decision."""
    pos = sum(1 for y in years if cand_year_metrics.get(y, {}).get("net_pts", 0) > 0)
    net = sum(cand_year_metrics.get(y, {}).get("net_pts", 0) for y in years)
    return (pos, net)


def run_stage_b_lobyo():
    data = load_stage_b()
    folds = {}
    for held_out in ALL_FOLD_YEARS:
        other_years = [y for y in ALL_FOLD_YEARS if y != held_out]
        scores = {c: stage_b_objective(data[c], other_years) for c in data}
        winner = max(scores, key=lambda c: scores[c])
        held_out_metrics = data[winner].get(held_out, {"n": 0})
        folds[str(held_out)] = {
            "selected_on_other_years": other_years,
            "candidate_scores_on_other_years": {c: list(s) for c, s in scores.items()},
            "fold_winner": winner,
            "held_out_year_metrics_for_winner": held_out_metrics,
        }
    all_years_winner = max(data, key=lambda c: stage_b_objective(data[c], ALL_FOLD_YEARS))
    return {
        "stage": "B",
        "objective": "(n_positive_build_years, aggregate_net_pts) over the non-held-out years, per docs/OG_STAGE_B_SAL.md",
        "candidate_pool": list(data.keys()),
        "folds": folds,
        "all_years_frozen_winner": "SAL_off",
        "all_years_recomputed_winner": all_years_winner,
    }


# ---------------------------------------------------------------------------
# STAGE C: BE family (noBE, BE30, BE45, BE60, BE75, BE90). Objective per
# docs/OG_STAGE_C_MANAGEMENT_COMPLETE.md: bar-count-neighborhood-with-no-
# cliff-edge + ex-2026 PF (highest) + all/most years positive. We reduce
# this to: (n_positive_years_among_others, PF_pts_ex_held_out_within_others)
# -- i.e. rank first by how many of the OTHER years are individually
# positive, tie-break by aggregate PF over those other years (using only
# full years for PF where possible, matching the doc's "ex-2026 PF" framing
# when 2026 is not the held-out year).
# ---------------------------------------------------------------------------
def load_stage_c():
    df = pd.read_csv(os.path.join(OUT, "stage_c_management_complete.csv"))
    df = df[df["candidate"] != "BE45_lock2pt_DIAGNOSTIC_ONLY"]
    data = {}
    for cand, g in df.groupby("candidate"):
        yearmap = {}
        for _, row in g.iterrows():
            yl = row["year"]
            if yl in ("2018", "2020", "2023", "2026"):
                yearmap[int(yl)] = {"net_pts": row["net_pts"], "PF_pts": row["PF_pts"],
                                     "n_trades": row["n_trades"]}
        data[cand] = yearmap
    return data


def year_pool_pf(data_cand, years):
    """Aggregate PF_pts over a set of years using the per-year net win/loss
    sums is not directly recoverable from PF_pts alone (PF is not additive
    across years); we approximate the "ex-held-out-year aggregate PF" by the
    (n_trades-weighted) mean of the per-year PF_pts values actually computed
    by the stage script, which is the same quantity referenced qualitatively
    ("ex-2026 PF") in the original stage docs when full per-pooled-trade PF
    is unavailable at this granularity."""
    vals, weights = [], []
    for y in years:
        m = data_cand.get(y)
        if m is None:
            continue
        vals.append(m["PF_pts"])
        weights.append(max(m["n_trades"], 1))
    if not vals:
        return 0.0
    return sum(v * w for v, w in zip(vals, weights)) / sum(weights)


def stage_c_objective(data_cand, years):
    pos = sum(1 for y in years if data_cand.get(y, {}).get("net_pts", 0) > 0)
    pf_agg = year_pool_pf(data_cand, years)
    return (pos, pf_agg)


def run_stage_c_lobyo():
    data = load_stage_c()
    folds = {}
    for held_out in ALL_FOLD_YEARS:
        other_years = [y for y in ALL_FOLD_YEARS if y != held_out]
        scores = {c: stage_c_objective(data[c], other_years) for c in data}
        winner = max(scores, key=lambda c: scores[c])
        held_out_metrics = data[winner].get(held_out, {"n_trades": 0})
        folds[str(held_out)] = {
            "selected_on_other_years": other_years,
            "candidate_scores_on_other_years": {c: list(s) for c, s in scores.items()},
            "fold_winner": winner,
            "held_out_year_metrics_for_winner": held_out_metrics,
        }
    all_years_winner = max(data, key=lambda c: stage_c_objective(data[c], ALL_FOLD_YEARS))
    return {
        "stage": "C",
        "objective": "(n_positive_years, trade-count-weighted mean PF_pts) over the non-held-out years, approximating docs/OG_STAGE_C_MANAGEMENT_COMPLETE.md's 'ex-2026 PF + all/most-years-positive + no-cliff-edge' standard",
        "candidate_pool": list(data.keys()),
        "folds": folds,
        "all_years_frozen_winner": "BE60",
        "all_years_recomputed_winner": all_years_winner,
    }


# ---------------------------------------------------------------------------
# STAGE D: reduced candidate set {no_gate, hmm3_HIGH_only_p55,
# hmm3_exclude_MID_p55}, using ALREADY-COMPUTED per-year breakdowns from the
# full-matrix results (docs/OG_STAGE_D_HMM.md) -- explicit approximation,
# avoiding 4x re-fits of the expensive session-refit causal HMM.
# no_gate's per-year values equal Stage C's BE60 (canonical 11:00-15:00
# window, no gate) -- same underlying trade population.
# ---------------------------------------------------------------------------
def load_stage_d():
    data = {
        "no_gate": {
            2018: {"net_pts": 103.61, "PF": 1.0709},
            2020: {"net_pts": 1301.84, "PF": 1.3819},
            2023: {"net_pts": 99.04, "PF": 1.0321},
            2026: {"net_pts": 2867.86, "PF": 2.7313},
        },
        "hmm3_HIGH_only_p55": {
            2018: {"net_pts": 112.23, "PF": 1.1047},
            2020: {"net_pts": 1525.63, "PF": 1.7652},
            2023: {"net_pts": -237.66, "PF": 0.8905},
            2026: {"net_pts": 2033.48, "PF": 3.0838},
        },
        "hmm3_exclude_MID_p55": {
            2018: {"net_pts": 315.48, "PF": 1.2702},
            2020: {"net_pts": 1436.02, "PF": 1.5275},
            2023: {"net_pts": 199.50, "PF": 1.0782},
            2026: {"net_pts": 2479.61, "PF": 3.0857},
        },
    }
    return data


def stage_d_objective(data_cand, years):
    pos = sum(1 for y in years if data_cand.get(y, {}).get("net_pts", 0) > 0)
    net = sum(data_cand.get(y, {}).get("net_pts", 0) for y in years)
    return (pos, net)


def run_stage_d_lobyo():
    data = load_stage_d()
    folds = {}
    for held_out in ALL_FOLD_YEARS:
        other_years = [y for y in ALL_FOLD_YEARS if y != held_out]
        scores = {c: stage_d_objective(data[c], other_years) for c in data}
        winner = max(scores, key=lambda c: scores[c])
        held_out_metrics = data[winner].get(held_out, {})
        folds[str(held_out)] = {
            "selected_on_other_years": other_years,
            "candidate_scores_on_other_years": {c: list(s) for c, s in scores.items()},
            "fold_winner": winner,
            "held_out_year_metrics_for_winner": held_out_metrics,
        }
    all_years_winner = max(data, key=lambda c: stage_d_objective(data[c], ALL_FOLD_YEARS))
    return {
        "stage": "D",
        "objective": "(n_positive_years, aggregate_net_pts) over the non-held-out years; APPROXIMATION using already-computed per-year breakdowns from the full HMM matrix (docs/OG_STAGE_D_HMM.md), reduced candidate set {no_gate, hmm3_HIGH_only_p55, hmm3_exclude_MID_p55} -- no per-fold HMM re-fitting was performed (would require 4x expensive causal session-refits); this is explicitly disclosed as an approximation.",
        "candidate_pool": list(data.keys()),
        "folds": folds,
        "all_years_frozen_winner": "no_gate (no-HMM)",
        "all_years_recomputed_winner": all_years_winner,
        "note": "no_gate's per-year values are identical to Stage C's BE60 canonical-window numbers (same underlying trade population with no gate applied).",
    }


# ---------------------------------------------------------------------------
# STAGE E: 7 blocked-until-15:00 starts (09:00...12:00). Objective per
# docs/OG_STAGE_E_WINDOWS_COMPLETE.md: highest ex-2026 PF among the 7,
# all-4-years positive preferred, not an isolated cliff-edge. Reduced to:
# (n_positive_years_among_others, trade-count-weighted mean PF_pts over
# others).
# ---------------------------------------------------------------------------
def load_stage_e():
    df = pd.read_csv(os.path.join(OUT, "stage_e_window_complete.csv"))
    df = df[df["candidate"].str.contains("until1500")]
    data = {}
    for cand, g in df.groupby("candidate"):
        yearmap = {}
        for _, row in g.iterrows():
            yl = row["year"]
            if yl in ("2018", "2020", "2023", "2026"):
                yearmap[int(yl)] = {"net_pts": row["net_pts"], "PF_pts": row["PF_pts"],
                                     "n_trades": row["n_trades"]}
        data[cand] = yearmap
    return data


def stage_e_objective(data_cand, years):
    pos = sum(1 for y in years if data_cand.get(y, {}).get("net_pts", 0) > 0)
    pf_agg = year_pool_pf(data_cand, years)
    return (pos, pf_agg)


def run_stage_e_lobyo():
    data = load_stage_e()
    folds = {}
    for held_out in ALL_FOLD_YEARS:
        other_years = [y for y in ALL_FOLD_YEARS if y != held_out]
        scores = {c: stage_e_objective(data[c], other_years) for c in data}
        winner = max(scores, key=lambda c: scores[c])
        held_out_metrics = data[winner].get(held_out, {"n_trades": 0})
        folds[str(held_out)] = {
            "selected_on_other_years": other_years,
            "candidate_scores_on_other_years": {c: list(s) for c, s in scores.items()},
            "fold_winner": winner,
            "held_out_year_metrics_for_winner": held_out_metrics,
        }
    all_years_winner = max(data, key=lambda c: stage_e_objective(data[c], ALL_FOLD_YEARS))
    return {
        "stage": "E",
        "objective": "(n_positive_years, trade-count-weighted mean PF_pts) over the non-held-out years, approximating docs/OG_STAGE_E_WINDOWS_COMPLETE.md's 'ex-2026 PF + all/most-years-positive + no-cliff-edge' standard",
        "candidate_pool": list(data.keys()),
        "folds": folds,
        "all_years_frozen_winner": "blocked_1000_until1500",
        "all_years_recomputed_winner": all_years_winner,
    }


# ---------------------------------------------------------------------------
# STAGE F: Lane A/B x 5 RRs; task pool: {0.75R,1.00R,1.25R,1.50R,2.00R, Lane B
# only (BE60)}, i.e. Lane B candidates only (the eligible-for-selection lane).
# Objective per docs/OG_STAGE_F_RR.md: PF_R / avg-R-per-trade monotonicity +
# no isolated max. Reduced to (n_positive_years_among_others, trade-count-
# weighted mean PF_R over others).
# ---------------------------------------------------------------------------
def load_stage_f():
    df = pd.read_csv(os.path.join(OUT, "stage_f_rr_complete.csv"))
    df = df[df["candidate"].str.startswith("laneB_")]
    data = {}
    for cand, g in df.groupby("candidate"):
        yearmap = {}
        for _, row in g.iterrows():
            yl = row["year"]
            if yl in ("2018", "2020", "2023", "2026"):
                yearmap[int(yl)] = {"net_pts": row["net_pts"], "PF_R": row["PF_R"],
                                     "cap_norm_R_avg": row["cap_norm_R_avg"],
                                     "n_trades": row["n_trades"]}
        data[cand] = yearmap
    return data


def year_pool_pfr(data_cand, years):
    vals, weights = [], []
    for y in years:
        m = data_cand.get(y)
        if m is None:
            continue
        vals.append(m["PF_R"])
        weights.append(max(m["n_trades"], 1))
    if not vals:
        return 0.0
    return sum(v * w for v, w in zip(vals, weights)) / sum(weights)


def stage_f_objective(data_cand, years):
    pos = sum(1 for y in years if data_cand.get(y, {}).get("net_pts", 0) > 0)
    pfr_agg = year_pool_pfr(data_cand, years)
    return (pos, pfr_agg)


def run_stage_f_lobyo():
    data = load_stage_f()
    folds = {}
    for held_out in ALL_FOLD_YEARS:
        other_years = [y for y in ALL_FOLD_YEARS if y != held_out]
        scores = {c: stage_f_objective(data[c], other_years) for c in data}
        winner = max(scores, key=lambda c: scores[c])
        held_out_metrics = data[winner].get(held_out, {"n_trades": 0})
        folds[str(held_out)] = {
            "selected_on_other_years": other_years,
            "candidate_scores_on_other_years": {c: list(s) for c, s in scores.items()},
            "fold_winner": winner,
            "held_out_year_metrics_for_winner": held_out_metrics,
        }
    all_years_winner = max(data, key=lambda c: stage_f_objective(data[c], ALL_FOLD_YEARS))
    return {
        "stage": "F",
        "objective": "(n_positive_years, trade-count-weighted mean PF_R) over the non-held-out years, approximating docs/OG_STAGE_F_RR.md's 'PF_R/avg-R-per-trade monotonicity + no isolated max' standard, Lane B (BE60) candidates only",
        "candidate_pool": list(data.keys()),
        "folds": folds,
        "all_years_frozen_winner": "laneB_be60_rr150",
        "all_years_recomputed_winner": all_years_winner,
    }


def selection_frequency(stage_result):
    freq = {}
    for f in stage_result["folds"].values():
        w = f["fold_winner"]
        freq[w] = freq.get(w, 0) + 1
    return freq


def main():
    results = {
        "B": run_stage_b_lobyo(),
        "C": run_stage_c_lobyo(),
        "D": run_stage_d_lobyo(),
        "E": run_stage_e_lobyo(),
        "F": run_stage_f_lobyo(),
    }
    for stage_key, res in results.items():
        res["selection_frequency_across_4_folds"] = selection_frequency(res)
        # 2026-specific check: does removing 2026 specifically as the held-out
        # fold change the winner relative to the 3 full-year folds?
        full_year_winners = [res["folds"][str(y)]["fold_winner"] for y in FULL_YEARS]
        fold_2026_winner = res["folds"]["2026"]["fold_winner"]
        res["stability_verdict"] = {
            "full_year_fold_winners": {str(y): w for y, w in zip(FULL_YEARS, full_year_winners)},
            "fold_2026_winner": fold_2026_winner,
            "unanimous_across_all_4_folds": len(set(full_year_winners + [fold_2026_winner])) == 1,
            "unanimous_across_3_full_year_folds": len(set(full_year_winners)) == 1,
            "2026_fold_winner_differs_from_full_year_consensus": (
                len(set(full_year_winners)) == 1 and fold_2026_winner != full_year_winners[0]
            ),
        }
        n_pos_full = sum(
            1 for y in FULL_YEARS
            if res["folds"][str(y)]["held_out_year_metrics_for_winner"].get("net_pts", -1) > 0
        )
        res["n_positive_held_out_folds_of_3_full_years"] = n_pos_full
        n_pos_all = n_pos_full + (
            1 if res["folds"]["2026"]["held_out_year_metrics_for_winner"].get("net_pts", -1) > 0 else 0
        )
        res["n_positive_held_out_folds_of_4"] = n_pos_all

    with open(os.path.join(OUT, "genuine_lobyo_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    for stage_key, res in results.items():
        print(f"\n=== Stage {stage_key} ===")
        print("Selection frequency:", res["selection_frequency_across_4_folds"])
        print("All-years frozen winner:", res["all_years_frozen_winner"])
        print("All-years recomputed winner:", res["all_years_recomputed_winner"])
        print("Stability:", res["stability_verdict"])
        print("Positive held-out folds (of 3 full years):", res["n_positive_held_out_folds_of_3_full_years"])
        print("Positive held-out folds (of 4):", res["n_positive_held_out_folds_of_4"])

    print("\nWrote outputs/og_build_years/genuine_lobyo_results.json")


if __name__ == "__main__":
    main()
