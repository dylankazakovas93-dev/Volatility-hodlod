"""Final BE45 bakeoff: exactly 4 candidates (A/B/C/D), all human-overridden
parameters fixed (BE45, PROP_HARD_BLACKOUT always on, original stop/cap and
level-generation logic, one global position, permanent first-touch
consumption, forced liquidation 15:00 ET). The only two axes tested here are
entry-blackout start (10:00 vs 09:30) and target_r (1.00R vs 1.50R).

DATA FIREWALL: {2018 (full), 2020 (full), 2023 (full), 2026 (partial, thru
2026-06-07)} only. No 2019/2021/2022/2024/2025 outcome anywhere. No
OG_PRE_VALIDATION_LOCK. No Monte Carlo / account-sizing simulation.

Outputs:
  outputs/og_build_years/final_buildoff_be45.csv
  outputs/og_build_years/final_buildoff_daily_metrics.csv
  outputs/og_build_years/final_buildoff_paired_trade_analysis.csv
  outputs/og_build_years/final_buildoff_lobyo.json
"""
import json
import os
import pickle

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import filter_build_years, in_prop_hard_blackout
from src.og_management_variants import run_variant_managed
from src.metrics import profit_factor, max_drawdown

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

BE_BARS = 45
CANDIDATES = {
    "A": dict(window=(600, 900), window_name="10:00-15:00", target_r=1.00),
    "B": dict(window=(600, 900), window_name="10:00-15:00", target_r=1.50),
    "C": dict(window=(570, 900), window_name="09:30-15:00", target_r=1.00),
    "D": dict(window=(570, 900), window_name="09:30-15:00", target_r=1.50),
}
BUILD_YEARS_FULL = [2018, 2020, 2023]
ALL_FOLD_YEARS = [2018, 2020, 2023, 2026]


def hold_time_minutes(sub):
    return (pd.to_datetime(sub["exit_time"]) - pd.to_datetime(sub["entry_time"])).dt.total_seconds() / 60.0


def run_candidate(bars, ranges, events, window, target_r):
    summary, ex_df = run_variant_managed(
        bars, ranges, events,
        mgmt_kwargs=dict(mode="barcount", be_bars=BE_BARS, target_r=target_r),
        sal_enabled=False, blocked_window=window, hmm_gate=None)
    by = filter_build_years(ex_df)
    return summary, by


def verify_hard_blackout(label, by):
    if by is None or len(by) == 0:
        return
    bad_entry = by["entry_time"].apply(in_prop_hard_blackout).any()
    bad_exit = by["exit_time"].apply(in_prop_hard_blackout).any()
    if bad_entry or bad_exit:
        raise AssertionError(f"PROP_HARD_BLACKOUT violated for candidate {label}")


def longest_non_winning_run(daily):
    """daily: DataFrame indexed by session_date sorted, with column
    'classification' in {'profitable','losing','breakeven'}. Longest run of
    consecutive session days (present in the daily calendar, i.e. days with
    trades OR explicitly no-trade calendar days are NOT inserted -- we use
    the sequence of ACTUAL TRADING DAYS present, since only days with
    trades have a defined P&L; see doc for explicit definition) that are
    not 'profitable'."""
    best = cur = 0
    for c in daily["classification"]:
        if c != "profitable":
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def longest_non_winning_run_losing_only(daily):
    best = cur = 0
    for c in daily["classification"]:
        if c == "losing":
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def daily_pnl_table(by):
    if by is None or len(by) == 0:
        return pd.DataFrame(columns=["session_date", "net_pnl", "classification", "year"])
    g = by.groupby("session_date").agg(net_pnl=("pnl", "sum"), year=("year", "first")).reset_index()
    g = g.sort_values("session_date").reset_index(drop=True)

    def classify(x):
        if x > 1e-9:
            return "profitable"
        elif x < -1e-9:
            return "losing"
        else:
            return "breakeven"
    g["classification"] = g["net_pnl"].apply(classify)
    return g


def days_to_n_profitable(daily, n=5):
    """Calendar days elapsed (from first trading day) to accumulate n
    profitable trading days, using the actual observed trade/day sequence
    (trading days only, in order)."""
    cnt = 0
    if len(daily) == 0:
        return None
    first_date = pd.to_datetime(daily["session_date"].iloc[0])
    for _, row in daily.iterrows():
        if row["classification"] == "profitable":
            cnt += 1
            if cnt == n:
                elapsed = (pd.to_datetime(row["session_date"]) - first_date).days
                return elapsed
    return None  # never reached n profitable days


def top_decile_threshold(daily):
    prof = daily[daily["classification"] == "profitable"]["net_pnl"]
    if len(prof) == 0:
        return None
    return float(prof.quantile(0.90))


def compute_year_row(label, sub, yr_label, n_years=1.0):
    n = len(sub)
    pnl = sub["pnl"]
    capr = sub["pnl"] / sub["cap"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    avg_w = float(wins.mean()) if len(wins) else 0.0
    avg_l = float(losses.mean()) if len(losses) else 0.0
    payoff = (avg_w / abs(avg_l)) if avg_l != 0 else None
    exit_counts = sub["exit_reason"].value_counts().to_dict()
    hm = hold_time_minutes(sub)
    daily = daily_pnl_table(sub)
    prof_days = int((daily["classification"] == "profitable").sum())
    lose_days = int((daily["classification"] == "losing").sum())
    be_days = int((daily["classification"] == "breakeven").sum())
    longest_nonwin = longest_non_winning_run(daily) if len(daily) else 0
    return {
        "candidate": label, "year": yr_label, "n_trades": n,
        "net_pts": round(float(pnl.sum()), 2),
        "PF_pts": round(profit_factor(pnl), 4),
        "PF_R": round(profit_factor(capr), 4),
        "cap_norm_R_total": round(float(capr.sum()), 4),
        "avg_R_per_trade": round(float(capr.mean()), 4) if n else 0.0,
        "win_rate": round(float((pnl > 0).mean()), 4) if n else 0.0,
        "avg_winner_pts": round(avg_w, 3),
        "avg_loser_pts": round(avg_l, 3),
        "payoff_ratio": round(payoff, 3) if payoff is not None else None,
        "max_dd_pts": round(max_drawdown(pnl), 2) if n else 0.0,
        "max_dd_R": round(max_drawdown(capr), 4) if n else 0.0,
        "n_TP": int(exit_counts.get("TP", 0)),
        "n_SL": int(exit_counts.get("SL", 0)),
        "n_BE": int(exit_counts.get("BE", 0) + exit_counts.get("LOCK", 0) + exit_counts.get("SCRATCH", 0)),
        "n_cutoff": int(exit_counts.get("cutoff", 0)),
        "hold_mean_min": round(float(hm.mean()), 1) if n else None,
        "hold_median_min": round(float(hm.median()), 1) if n else None,
        "trades_per_year": round(n / n_years, 2) if n_years else None,
        "profitable_days": prof_days,
        "losing_days": lose_days,
        "breakeven_days": be_days,
        "avg_daily_pnl": round(float(daily["net_pnl"].mean()), 3) if len(daily) else None,
        "median_daily_pnl": round(float(daily["net_pnl"].median()), 3) if len(daily) else None,
        "longest_run_no_profitable_day": longest_nonwin,
    }


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    trades = {}
    all_rows = []
    daily_rows = []

    for label, cfg in CANDIDATES.items():
        summary, by = run_candidate(bars, ranges, events, cfg["window"], cfg["target_r"])
        verify_hard_blackout(label, by)
        trades[label] = by
        by.to_csv(os.path.join(OUT, f"final_buildoff_{label}_build_years_trades.csv"), index=False)
        print(label, "n=", len(by), "net=", round(float(by["pnl"].sum()), 2) if len(by) else 0)

        for yr in sorted(by["year"].unique()):
            sub = by[by["year"] == yr]
            all_rows.append(compute_year_row(label, sub, int(yr), n_years=1))
            daily = daily_pnl_table(sub)
            for _, r in daily.iterrows():
                daily_rows.append({"candidate": label, "session_date": r["session_date"],
                                    "year": int(r["year"]), "net_pnl": r["net_pnl"],
                                    "classification": r["classification"]})

        full = by[by["year"].isin(BUILD_YEARS_FULL)]
        all_rows.append(compute_year_row(label, full, "completed_2018_2020_2023", n_years=3))
        all_rows.append(compute_year_row(label, by, "ALL_build_years_incl_2026", n_years=3.5))

    df = pd.DataFrame(all_rows)
    df.to_csv(os.path.join(OUT, "final_buildoff_be45.csv"), index=False)

    daily_df = pd.DataFrame(daily_rows)
    daily_df.to_csv(os.path.join(OUT, "final_buildoff_daily_metrics.csv"), index=False)

    # --- Prop-relevant descriptive diagnostics per candidate + pooled 1.00R
    # vs 1.50R groups ---------------------------------------------------
    prop_rows = []
    for label in CANDIDATES:
        by = trades[label]
        full = by[by["year"].isin(BUILD_YEARS_FULL)]
        daily_full = daily_pnl_table(full)
        pct_pos_trades = float((full["pnl"] > 0).mean()) if len(full) else None
        pct_pos_days = float((daily_full["classification"] == "profitable").mean()) if len(daily_full) else None
        avg_win_day = float(daily_full.loc[daily_full["classification"] == "profitable", "net_pnl"].mean()) if (daily_full["classification"] == "profitable").any() else None
        avg_loss_day = float(daily_full.loc[daily_full["classification"] == "losing", "net_pnl"].mean()) if (daily_full["classification"] == "losing").any() else None
        days_to_5 = days_to_n_profitable(daily_full, 5)
        thresh = top_decile_threshold(daily_full)
        n_large_days = int((daily_full["net_pnl"] >= thresh).sum()) if thresh is not None else 0
        max_consec_losing = longest_non_winning_run_losing_only(daily_full)
        max_consec_nonwin = longest_non_winning_run(daily_full)
        net_sorted = full.groupby("session_date")["pnl"].sum().sort_values(ascending=False)
        total_net = float(full["pnl"].sum())
        best5 = float(net_sorted.head(5).sum())
        best10 = float(net_sorted.head(10).sum())
        prop_rows.append({
            "candidate": label, "window": CANDIDATES[label]["window_name"],
            "target_r": CANDIDATES[label]["target_r"],
            "scope": "completed_years_2018_2020_2023",
            "pct_trades_positive": round(pct_pos_trades, 4) if pct_pos_trades is not None else None,
            "pct_days_positive": round(pct_pos_days, 4) if pct_pos_days is not None else None,
            "avg_profit_per_winning_day": round(avg_win_day, 3) if avg_win_day is not None else None,
            "avg_loss_per_losing_day": round(avg_loss_day, 3) if avg_loss_day is not None else None,
            "days_elapsed_to_5_profitable_days": days_to_5,
            "large_day_threshold_p90": round(thresh, 3) if thresh is not None else None,
            "n_large_winning_days": n_large_days,
            "max_consecutive_losing_days": max_consec_losing,
            "max_consecutive_nonwinning_days": max_consec_nonwin,
            "pct_net_from_best5_days": round(100.0 * best5 / total_net, 2) if total_net else None,
            "pct_net_from_best10_days": round(100.0 * best10 / total_net, 2) if total_net else None,
        })
    prop_df = pd.DataFrame(prop_rows)
    prop_df.to_csv(os.path.join(OUT, "final_buildoff_prop_diagnostics.csv"), index=False)

    # --- Paired trade analysis: A vs B (10:00-15:00), C vs D (09:30-15:00)
    pair_rows = []
    for pair_name, (lo_label, hi_label) in [("A_vs_B_10_15", ("A", "B")), ("C_vs_D_0930_15", ("C", "D"))]:
        lo = trades[lo_label].set_index("level_id")
        hi = trades[hi_label].set_index("level_id")
        common = lo.index.intersection(hi.index)
        cats = {
            "hit_1R_profitable_lo_but_scratched_lost_hi": 0,
            "hit_both_1R_and_1p5R_excursion": 0,
            "hit_1R_never_reached_1p5R_excursion": 0,
            "be45_prevented_eventual_1p5R_target": 0,
            "be45_avoided_eventual_full_stop": 0,
            "cutoff_caused_by_larger_target": 0,
        }
        net_r_effect = {k: 0.0 for k in cats}
        n_common = len(common)
        n_lo_only = len(lo.index.difference(hi.index))
        n_hi_only = len(hi.index.difference(lo.index))
        for lvl in common:
            lo_row = lo.loc[lvl]
            hi_row = hi.loc[lvl]
            if isinstance(lo_row, pd.DataFrame):
                lo_row = lo_row.iloc[0]
            if isinstance(hi_row, pd.DataFrame):
                hi_row = hi_row.iloc[0]
            lo_r = lo_row["pnl"] / lo_row["cap"]
            hi_r = hi_row["pnl"] / hi_row["cap"]
            diff = hi_r - lo_r
            # (1) hit 1.00R (TP under lo) but scratched/lost under hi
            if lo_row["exit_reason"] == "TP" and hi_row["exit_reason"] in ("BE", "LOCK", "SCRATCH", "SL"):
                cats["hit_1R_profitable_lo_but_scratched_lost_hi"] += 1
                net_r_effect["hit_1R_profitable_lo_but_scratched_lost_hi"] += diff
            # (2) hit both 1.00R and 1.50R excursion => hi also TP'd
            if lo_row["exit_reason"] == "TP" and hi_row["exit_reason"] == "TP":
                cats["hit_both_1R_and_1p5R_excursion"] += 1
                net_r_effect["hit_both_1R_and_1p5R_excursion"] += diff
            # (3) hit 1.00R but never reached 1.5R excursion (TP under lo,
            # non-TP under hi that is NOT a BE/lock exit caused by mgmt --
            # approximate via hi exit_reason != TP)
            if lo_row["exit_reason"] == "TP" and hi_row["exit_reason"] != "TP":
                cats["hit_1R_never_reached_1p5R_excursion"] += 1
                net_r_effect["hit_1R_never_reached_1p5R_excursion"] += diff
            # (4) BE45 in the 1.5R variant exited (BE/LOCK/SCRATCH) while lo
            # (1.0R) trade reached its own TP -- proxy for "BE prevented a
            # later, larger target from being reached"
            if hi_row["exit_reason"] in ("BE", "LOCK", "SCRATCH") and lo_row["exit_reason"] == "TP":
                cats["be45_prevented_eventual_1p5R_target"] += 1
                net_r_effect["be45_prevented_eventual_1p5R_target"] += diff
            # (5) BE45 avoided an eventual full stop-loss: hi exit BE/LOCK/
            # SCRATCH while lo (same entry, tighter target) ended SL
            if hi_row["exit_reason"] in ("BE", "LOCK", "SCRATCH") and lo_row["exit_reason"] == "SL":
                cats["be45_avoided_eventual_full_stop"] += 1
                net_r_effect["be45_avoided_eventual_full_stop"] += diff
            # (6) cutoff caused specifically by the larger target: lo==TP,
            # hi==cutoff
            if lo_row["exit_reason"] == "TP" and hi_row["exit_reason"] == "cutoff":
                cats["cutoff_caused_by_larger_target"] += 1
                net_r_effect["cutoff_caused_by_larger_target"] += diff
        for k in cats:
            pair_rows.append({
                "pair": pair_name, "category": k, "count": cats[k],
                "net_R_effect_hi_minus_lo": round(net_r_effect[k], 4),
            })
        pair_rows.append({"pair": pair_name, "category": "n_common_level_ids", "count": n_common, "net_R_effect_hi_minus_lo": None})
        pair_rows.append({"pair": pair_name, "category": f"n_only_in_{lo_label}", "count": n_lo_only, "net_R_effect_hi_minus_lo": None})
        pair_rows.append({"pair": pair_name, "category": f"n_only_in_{hi_label}", "count": n_hi_only, "net_R_effect_hi_minus_lo": None})
    pair_df = pd.DataFrame(pair_rows)
    pair_df.to_csv(os.path.join(OUT, "final_buildoff_paired_trade_analysis.csv"), index=False)

    # --- Genuine LOBYO (4-candidate fold selection, completed years only for
    # selection; 2026 fold uses all 3 completed years) --------------------
    def avg_r_for_years(label, years):
        by = trades[label]
        sub = by[by["year"].isin(years)]
        if len(sub) == 0:
            return None, None, 0
        capr = sub["pnl"] / sub["cap"]
        return float(capr.mean()), float(profit_factor(capr)), len(sub)

    folds = {}
    for held_out in ALL_FOLD_YEARS:
        train_years = [y for y in BUILD_YEARS_FULL if y != held_out]
        if held_out == 2026:
            train_years = BUILD_YEARS_FULL  # 2026 held out; train on all 3 completed years
        scores = {}
        for label in CANDIDATES:
            avg_r, pf_r, n = avg_r_for_years(label, train_years)
            scores[label] = {"avg_R_per_trade": avg_r, "PF_R": pf_r, "n_trades": n}
        winner = max(scores, key=lambda l: (scores[l]["avg_R_per_trade"] if scores[l]["avg_R_per_trade"] is not None else -999))
        by_w = trades[winner]
        held_sub = by_w[by_w["year"] == held_out]
        held_metrics = compute_year_row(winner, held_sub, held_out) if len(held_sub) else {"n_trades": 0}
        folds[str(held_out)] = {
            "train_years": train_years,
            "candidate_scores_on_train_years": scores,
            "fold_winner": winner,
            "held_out_year": held_out,
            "held_out_year_metrics_for_winner": held_metrics,
        }
    all_scores = {label: dict(zip(("avg_R_per_trade", "PF_R", "n_trades"), avg_r_for_years(label, BUILD_YEARS_FULL))) for label in CANDIDATES}
    overall_winner = max(all_scores, key=lambda l: (all_scores[l]["avg_R_per_trade"] if all_scores[l]["avg_R_per_trade"] is not None else -999))
    lobyo_out = {
        "objective": "avg_R_per_trade over completed build years available in the fold's training set (selection restricted to the 4 candidates A/B/C/D, no new parameter search)",
        "folds": folds,
        "all_completed_years_scores": all_scores,
        "all_completed_years_winner": overall_winner,
    }
    with open(os.path.join(OUT, "final_buildoff_lobyo.json"), "w") as f:
        json.dump(lobyo_out, f, indent=2, default=str)

    print("\nCompleted-years (2018+2020+2023) summary:")
    print(df[df["year"] == "completed_2018_2020_2023"][["candidate", "n_trades", "net_pts", "PF_R", "avg_R_per_trade", "max_dd_R", "profitable_days", "losing_days"]].to_string(index=False))
    print("\nLOBYO winner overall (completed years):", overall_winner)
    print("Fold winners:", {k: v["fold_winner"] for k, v in folds.items()})


if __name__ == "__main__":
    main()
