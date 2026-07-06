"""Stage F: target / RR (reward:risk) study.

Holds constant: SAL off (Stage B freeze), BE60 management (Stage C final --
mode="barcount", be_bars=60, via src.og_management_variants.run_variant_managed)
for Lane B only, no HMM gate (Stage D freeze), Stage E's selected blocked
entry interval RESEARCH_ENTRY_BLACKOUT_10_15 (blocked_window=(600, 900), i.e.
10:00-15:00 ET blocked), original stop distance/cap logic unchanged
(cap = min(1.5*anchor, SL_CAP)), forced liquidation 15:00 ET (session_cutoff(),
unchanged), PROP_HARD_BLACKOUT (16:00-19:00 ET) always on and unconditional.

The variable under test is `target_r`: the TP target distance as a multiple
of the per-trade stop distance `cap` (1R), added as a new optional parameter
to src.og_management_variants.simulate_managed (default 1.0, which exactly
reproduces every prior stage's numbers -- verified below). Only the target
moves; the stop distance/cap is never touched.

Two lanes per RR:
  Lane A -- no management at all: mode="none" (raw TP/SL only, no BE/lock/
            scratch mechanism whatsoever), new target only.
  Lane B -- BE60: mode="barcount", be_bars=60 (Stage C mechanism, unchanged),
            new target only.

RRs tested: 0.75, 1.00, 1.25, 1.50, 2.00.

DATA FIREWALL: build years only {2018 (full), 2020 (full), 2023 (full),
2026 (partial)}. No 2019/2021/2022/2024/2025 trade outcomes anywhere below.
No OG_PRE_VALIDATION_LOCK. No Monte Carlo, no prop-account simulation.

Outputs:
  outputs/og_build_years/stage_f_rr_complete.csv          (10-candidate table)
  outputs/og_build_years/stage_f_rr_complete_raw.json      (raw summaries)
  outputs/og_build_years/stage_f_excursion_diagnostic.csv  (excursion diag)
  outputs/og_build_years/stage_f_mgmt_interaction.csv      (Lane B mgmt diag)
  per-candidate build-year trade ledgers
    outputs/og_build_years/stage_f_<candidate>_build_years_trades.csv
"""
import json
import os
import pickle
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import filter_build_years, in_prop_hard_blackout
from src.og_management_variants import run_variant_managed, simulate_managed, _fav_adv
from src.strict_engine import session_cutoff
from src.metrics import profit_factor, max_drawdown

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")

BLOCKED_WINDOW = (10 * 60, 15 * 60)  # Stage E final: RESEARCH_ENTRY_BLACKOUT_10_15
RRS = [0.75, 1.00, 1.25, 1.50, 2.00]
THRESHOLDS = [0.50, 0.75, 1.00, 1.25, 1.50, 2.00]


def hold_time_minutes(sub):
    dt = (pd.to_datetime(sub["exit_time"]) - pd.to_datetime(sub["entry_time"])).dt.total_seconds() / 60.0
    return dt


def compute_full_metrics(label, by):
    if by is None or len(by) == 0:
        return []
    by = by.copy()
    by["cap_norm_pnl"] = by["pnl"] / by["cap"]
    by["hold_min"] = hold_time_minutes(by)

    def yr_row(sub, yr_label, n_years=1):
        n = len(sub)
        pnl = sub["pnl"]
        capr = sub["cap_norm_pnl"]
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        avg_w = float(wins.mean()) if len(wins) else 0.0
        avg_l = float(losses.mean()) if len(losses) else 0.0
        payoff = (avg_w / abs(avg_l)) if avg_l not in (0, None) and avg_l != 0 else None
        exit_counts = sub["exit_reason"].value_counts().to_dict()
        hm = sub["hold_min"]
        return {
            "candidate": label, "year": yr_label, "n_trades": n,
            "net_pts": round(float(pnl.sum()), 2),
            "PF_pts": round(profit_factor(pnl), 4),
            "PF_R": round(profit_factor(capr), 4),
            "avg_pts_per_trade": round(float(pnl.mean()), 3) if n else 0.0,
            "cap_norm_R_total": round(float(capr.sum()), 4),
            "cap_norm_R_avg": round(float(capr.mean()), 4) if n else 0.0,
            "max_dd_pts": round(max_drawdown(pnl), 2) if n else 0.0,
            "max_dd_R": round(max_drawdown(capr), 4) if n else 0.0,
            "win_rate": round(float((pnl > 0).mean()), 4) if n else 0.0,
            "avg_winner_pts": round(avg_w, 3),
            "avg_loser_pts": round(avg_l, 3),
            "payoff_ratio": round(payoff, 3) if payoff is not None else None,
            "n_TP": int(exit_counts.get("TP", 0)),
            "n_SL": int(exit_counts.get("SL", 0)),
            "n_BE": int(exit_counts.get("BE", 0) + exit_counts.get("LOCK", 0) + exit_counts.get("SCRATCH", 0)),
            "n_cutoff": int(exit_counts.get("cutoff", 0)),
            "trades_per_year": round(n / n_years, 2),
            "hold_median_min": round(float(hm.median()), 1) if n else None,
            "hold_mean_min": round(float(hm.mean()), 1) if n else None,
            "hold_p25_min": round(float(hm.quantile(.25)), 1) if n else None,
            "hold_p75_min": round(float(hm.quantile(.75)), 1) if n else None,
        }

    rows = []
    for yr in sorted(by["year"].unique()):
        sub = by[by["year"] == yr]
        rows.append(yr_row(sub, int(yr)))
    rows.append(yr_row(by, "ALL", n_years=4))
    ex2026 = by[by["year"] != 2026]
    if len(ex2026):
        rows.append(yr_row(ex2026, "ALL_ex2026", n_years=3))
    yearly_net = by.groupby("year")["pnl"].sum()
    if len(yearly_net) > 1:
        best_year = yearly_net.idxmax()
        ex_best = by[by["year"] != best_year]
        rows.append(yr_row(ex_best, f"ALL_ex_best_year({int(best_year)})", n_years=len(yearly_net) - 1))
    # % pooled profit by year (share of total positive-sum-of-net-pts, using
    # net pnl per year -- reported for the ALL scope only).
    total_net = float(pnl_sum_pos_denominator(yearly_net))
    for yr, net in yearly_net.items():
        rows.append({
            "candidate": label, "year": f"pct_pooled_profit_{int(yr)}", "n_trades": None,
            "net_pts": round(float(net), 2),
            "PF_pts": None, "PF_R": None, "avg_pts_per_trade": None,
            "cap_norm_R_total": None, "cap_norm_R_avg": None, "max_dd_pts": None,
            "max_dd_R": None, "win_rate": None, "avg_winner_pts": None,
            "avg_loser_pts": None, "payoff_ratio": None, "n_TP": None, "n_SL": None,
            "n_BE": None, "n_cutoff": None, "trades_per_year": None,
            "hold_median_min": None, "hold_mean_min": None, "hold_p25_min": None,
            "hold_p75_min": None,
            "pct_pooled_profit": round(100.0 * float(net) / total_net, 2) if total_net else None,
        })
    return rows


def pnl_sum_pos_denominator(yearly_net):
    # Denominator for "% pooled profit by year": sum of net pnl across all
    # build years (can be negative-containing; this is a share-of-total-net
    # measure, not a share-of-gross-profit measure).
    return float(yearly_net.sum())


def run_candidate(bars, ranges, events, mgmt_kwargs):
    summary, ex_df = run_variant_managed(
        bars, ranges, events, mgmt_kwargs=mgmt_kwargs, sal_enabled=False,
        blocked_window=BLOCKED_WINDOW, hmm_gate=None)
    by = filter_build_years(ex_df)
    return summary, by


def verify_hard_blackout(label, by):
    if by is None or len(by) == 0:
        return True
    bad_entry = by["entry_time"].apply(in_prop_hard_blackout).any()
    bad_exit = by["exit_time"].apply(in_prop_hard_blackout).any()
    if bad_entry or bad_exit:
        raise AssertionError(f"PROP_HARD_BLACKOUT violated for candidate {label}")
    return True


# ---------------------------------------------------------------------------
# Excursion diagnostic (once, reusable across all 10 candidates): for the
# canonical BE60 target=1.0R (Stage E frozen) trade population, walk the raw
# per-trade OHLC path from the bar after the touch bar to the ORIGINAL stop
# (cap distance) or session cutoff -- ignoring target/management entirely --
# and record the max favorable excursion (in R = fav_pts / cap) reached
# before that raw stop/cutoff exit. This is a property of trade *paths*
# (entries + raw stop distance), not of which RR/lane is later selected.
def excursion_diagnostic(bars, trades_df, thresholds=THRESHOLDS):
    counts = {t: 0 for t in thresholds}
    n = 0
    mfe_r_values = []
    for _, row in trades_df.iterrows():
        touched_at = row["entry_time"]
        sign = -1.0 if row["side"] == "upper" else 1.0
        cap = float(row["cap"])
        entry_fill = float(row["entry_price"])
        cutoff = session_cutoff(touched_at)
        if cutoff is None or touched_at not in bars.index:
            continue
        n += 1
        touch_row = bars.loc[touched_at]
        orig_stop = entry_fill - sign * cap
        h0, l0 = float(touch_row["high"]), float(touch_row["low"])
        hit_stop = (l0 <= orig_stop) if sign > 0 else (h0 >= orig_stop)
        if hit_stop:
            mfe_r_values.append(0.0)
            continue
        rest = bars.loc[touched_at:cutoff].iloc[1:]
        if rest.empty:
            mfe_r_values.append(0.0)
            continue
        mfe = 0.0
        for h, l in zip(rest["high"].values, rest["low"].values):
            h, l = float(h), float(l)
            stop_hit = (l <= orig_stop) if sign > 0 else (h >= orig_stop)
            if stop_hit:
                break
            fav, _ = _fav_adv(sign, h, l, entry_fill)
            mfe = max(mfe, fav)
        r = mfe / cap if cap else 0.0
        mfe_r_values.append(r)
        for t in thresholds:
            if r >= t:
                counts[t] += 1
    return n, counts, mfe_r_values


# ---------------------------------------------------------------------------
# Management-interaction diagnostics (Lane B only, read-only, does not alter
# any reported P&L). For each RR, compare the actual Lane-B (BE60, target_r
# = RR) trade to two counterfactuals computed on the SAME entry (touched_at,
# fill, sign, cap): (a) mode="none" with the SAME target_r (what would have
# happened with no management at all, same target) -- isolates what BE
# management changed vs a full stop / full target outcome; (b) the Lane-B
# RR=1.00 baseline trade on the same entry (what actually happened under the
# canonical BE60 1.0R candidate) -- isolates what the LARGER target changed
# vs the frozen baseline.
def mgmt_interaction_diagnostics(bars, ranges, events, rr, lane_b_trades, baseline_1r_trades):
    none_summary, none_by = run_candidate(bars, ranges, events, dict(mode="none", target_r=rr))
    none_by = none_by.set_index("entry_time") if len(none_by) else none_by
    lane_b_idx = lane_b_trades.set_index("entry_time")
    baseline_idx = baseline_1r_trades.set_index("entry_time")

    avoided_full_stop = 0
    sacrificed_full_target = 0
    reached_this_rr_target = 0
    converted_tp_to_cutoff = 0
    converted_tp_to_mgmt = 0

    for ts, row in lane_b_idx.iterrows():
        if row["exit_reason"] not in ("BE", "LOCK", "SCRATCH"):
            continue
        if ts in none_by.index:
            cf = none_by.loc[ts]
            if isinstance(cf, pd.DataFrame):
                cf = cf.iloc[0]
            if cf["exit_reason"] == "SL":
                avoided_full_stop += 1
            if cf["exit_reason"] == "TP":
                sacrificed_full_target += 1
                reached_this_rr_target += 1

    for ts, row in baseline_idx.iterrows():
        if row["exit_reason"] != "TP":
            continue
        if ts in lane_b_idx.index:
            cur = lane_b_idx.loc[ts]
            if isinstance(cur, pd.DataFrame):
                cur = cur.iloc[0]
            if cur["exit_reason"] == "cutoff":
                converted_tp_to_cutoff += 1
            if cur["exit_reason"] in ("BE", "LOCK", "SCRATCH"):
                converted_tp_to_mgmt += 1

    return {
        "rr": rr,
        "n_mgmt_exits": int((lane_b_idx["exit_reason"].isin(["BE", "LOCK", "SCRATCH"])).sum()),
        "avoided_full_stop": avoided_full_stop,
        "sacrificed_full_target": sacrificed_full_target,
        "reached_this_rr_target_after_mgmt_exit": reached_this_rr_target,
        "baseline_1R_TP_converted_to_cutoff": converted_tp_to_cutoff,
        "baseline_1R_TP_converted_to_mgmt_exit": converted_tp_to_mgmt,
    }


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    all_rows = []
    raw = {}
    trades_by_label = {}

    # --- Sanity check: target_r=1.0 for both lanes must reproduce the
    # existing Stage E BE60 numbers (Lane B) exactly, confirming the new
    # parameter is a true no-op at its default. --------------------------
    _, sanity_by = run_candidate(bars, ranges, events, dict(mode="barcount", be_bars=60, target_r=1.0))
    sanity_net = round(float(sanity_by["pnl"].sum()), 2) if len(sanity_by) else 0.0
    print(f"Sanity check: Lane B target_r=1.0 net_pts(ALL) = {sanity_net} "
          f"(expect 5011.09 per Stage E's 10:00-15:00 candidate)")

    for rr in RRS:
        rr_name = f"{rr:.2f}".replace(".", "")
        # Lane A: no management.
        label_a = f"laneA_none_rr{rr_name}"
        summary_a, by_a = run_candidate(bars, ranges, events, dict(mode="none", target_r=rr))
        verify_hard_blackout(label_a, by_a)
        trades_by_label[label_a] = by_a
        by_a.to_csv(os.path.join(OUT, f"stage_f_{label_a}_build_years_trades.csv"), index=False)
        rows_a = compute_full_metrics(label_a, by_a)
        all_rows.extend(rows_a)
        raw[label_a] = {"lane": "A_no_mgmt", "rr": rr, "summary": summary_a, "n": int(len(by_a))}
        print(label_a, "n=", len(by_a), "net=", round(float(by_a["pnl"].sum()), 2) if len(by_a) else 0)

        # Lane B: BE60.
        label_b = f"laneB_be60_rr{rr_name}"
        summary_b, by_b = run_candidate(bars, ranges, events, dict(mode="barcount", be_bars=60, target_r=rr))
        verify_hard_blackout(label_b, by_b)
        trades_by_label[label_b] = by_b
        by_b.to_csv(os.path.join(OUT, f"stage_f_{label_b}_build_years_trades.csv"), index=False)
        rows_b = compute_full_metrics(label_b, by_b)
        all_rows.extend(rows_b)
        raw[label_b] = {"lane": "B_BE60", "rr": rr, "summary": summary_b, "n": int(len(by_b))}
        print(label_b, "n=", len(by_b), "net=", round(float(by_b["pnl"].sum()), 2) if len(by_b) else 0)

    df = pd.DataFrame(all_rows)
    df.to_csv(os.path.join(OUT, "stage_f_rr_complete.csv"), index=False)
    with open(os.path.join(OUT, "stage_f_rr_complete_raw.json"), "w") as f:
        json.dump(raw, f, indent=2, default=str)
    print("\nWrote outputs/og_build_years/stage_f_rr_complete.csv")

    # --- Excursion diagnostic (once, using the Lane B RR=1.00 canonical
    # (Stage E frozen) trade population as the reference entry set / raw
    # stop-distance path). -------------------------------------------------
    ref_trades = trades_by_label["laneB_be60_rr100"]
    n_exc, counts, mfe_vals = excursion_diagnostic(bars, ref_trades)
    exc_rows = [{"threshold_R": t, "n_reached": counts[t], "n_total": n_exc,
                 "pct_reached": round(100.0 * counts[t] / n_exc, 2) if n_exc else None}
                for t in THRESHOLDS]
    exc_df = pd.DataFrame(exc_rows)
    exc_df.to_csv(os.path.join(OUT, "stage_f_excursion_diagnostic.csv"), index=False)
    print("\nExcursion diagnostic (reference: Lane B BE60 RR=1.00 trade population):")
    print(exc_df.to_string(index=False))

    # --- Management-interaction diagnostics (Lane B only). ----------------
    baseline_1r = trades_by_label["laneB_be60_rr100"]
    mgmt_rows = []
    for rr in RRS:
        rr_name = f"{rr:.2f}".replace(".", "")
        lane_b_trades = trades_by_label[f"laneB_be60_rr{rr_name}"]
        diag = mgmt_interaction_diagnostics(bars, ranges, events, rr, lane_b_trades, baseline_1r)
        mgmt_rows.append(diag)
    mgmt_df = pd.DataFrame(mgmt_rows)
    mgmt_df.to_csv(os.path.join(OUT, "stage_f_mgmt_interaction.csv"), index=False)
    print("\nManagement-interaction diagnostics (Lane B):")
    print(mgmt_df.to_string(index=False))


if __name__ == "__main__":
    main()
