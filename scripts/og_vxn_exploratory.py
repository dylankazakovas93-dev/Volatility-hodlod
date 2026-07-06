"""OG VXN exploratory filter matrix runner (POST_VALIDATION_EXPLORATORY_REDEVELOPMENT).

Runs the locked 7-filter x 2-base (14-candidate) matrix defined in
docs/OG_VXN_EXPLORATORY_PROTOCOL.md against the FULL redevelopment sample
(2018 through partial-2026, i.e. every year the frozen build+validation
cache already covers). Does not touch 2013-2015. Does not modify any
locked validation artifact.

Usage:
    python3 scripts/og_vxn_exploratory.py --out-dir outputs/og_vxn/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_vxn_filter import (
    FILTER_DEFS, build_session_date_to_vxn_close, load_vxn_normalized,
    run_variant_managed_vxn, sha256_file,
)
from src.metrics import profit_factor, max_drawdown

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
VXN_NORM_PATH = os.path.join(REPO_ROOT, "data", "vxn_daily_2018_2026_normalized.csv")

BASES = {
    "OG_PRIMARY_150R": dict(be_bars=45, target_r=1.50, blocked_window=(600, 900)),
    "OG_OPERATIONAL_100R": dict(be_bars=45, target_r=1.00, blocked_window=(600, 900)),
}

FULL_YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
ORIGINAL_BUILD_YEARS = {2018, 2020, 2023, 2026}
FORMER_VALIDATION_YEARS = {2019, 2021, 2022, 2024, 2025}
BANNED_YEARS = {2013, 2014, 2015}


def compute_row(pnl, cap):
    n = len(pnl)
    if n == 0:
        return dict(n_trades=0, net_pts=0.0, PF_pts=None, total_R=0.0, PF_R=None,
                    avg_R_per_trade=0.0, win_rate=0.0, avg_winner=None, avg_loser=None,
                    payoff_ratio=None, max_dd_pts=0.0, max_dd_R=0.0)
    capr = pnl / cap
    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]
    avg_w = float(winners.mean()) if len(winners) else 0.0
    avg_l = float(losers.mean()) if len(losers) else 0.0
    payoff = (avg_w / abs(avg_l)) if avg_l != 0 else None
    return dict(
        n_trades=n,
        net_pts=round(float(pnl.sum()), 2),
        PF_pts=round(profit_factor(pnl), 4),
        total_R=round(float(capr.sum()), 4),
        PF_R=round(profit_factor(capr), 4),
        avg_R_per_trade=round(float(capr.mean()), 4),
        win_rate=round(float((pnl > 0).mean()), 4),
        avg_winner=round(avg_w, 2),
        avg_loser=round(avg_l, 2),
        payoff_ratio=round(payoff, 4) if payoff is not None else None,
        max_dd_pts=round(max_drawdown(pnl), 2),
        max_dd_R=round(max_drawdown(capr), 4),
    )


def daily_stats(df):
    """profitable/losing/breakeven trading days + longest non-winning-day run."""
    if len(df) == 0:
        return dict(profitable_days=0, losing_days=0, breakeven_days=0, longest_non_winning_run=0)
    daily = df.groupby("session_date")["pnl"].sum()
    prof = int((daily > 0.01).sum())
    lose = int((daily < -0.01).sum())
    be = int(len(daily) - prof - lose)
    longest = cur = 0
    for v in daily.sort_index().values:
        if v > 0.01:
            cur = 0
        else:
            cur += 1
            longest = max(longest, cur)
    return dict(profitable_days=prof, losing_days=lose, breakeven_days=be,
                longest_non_winning_run=longest)


def exit_counts(df):
    if len(df) == 0:
        return dict(TP=0, SL=0, BE=0, cutoff=0)
    vc = df["exit_reason"].value_counts()
    return dict(TP=int(vc.get("TP", 0)), SL=int(vc.get("SL", 0)),
                BE=int(vc.get("BE", 0)), cutoff=int(vc.get("cutoff", 0)))


def year_of(df, yr):
    return df[df["year"] == yr] if len(df) else df


def run_matrix(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    vxn_df = load_vxn_normalized(VXN_NORM_PATH)
    session_dates = sorted({e_sess for e_sess in
                             (pd.Timestamp(bars.index[0]).strftime("%Y-%m-%d"),)})
    # Build vxn_map keyed on ALL session dates actually touched (derived after run,
    # but we need it up front for the filter check) -- compute over the full bars span.
    from src.strict_engine import session_date as _session_date
    all_sessions = sorted({_session_date(ts) for ts in bars.index})
    vxn_map = build_session_date_to_vxn_close(vxn_df, all_sessions)

    candidate_rows = []
    per_year_rows = []
    all_ledgers = {}

    for base_id, base_params in BASES.items():
        mgmt_kwargs = dict(mode="barcount", be_bars=base_params["be_bars"], target_r=base_params["target_r"])
        base_executed_count = None
        for filter_name in FILTER_DEFS:
            summary, ex_df = run_variant_managed_vxn(
                bars, ranges, events, vxn_map, filter_name,
                mgmt_kwargs=mgmt_kwargs, blocked_window=base_params["blocked_window"])

            leaked_banned = set(ex_df["year"].unique()) & BANNED_YEARS if len(ex_df) else set()
            if leaked_banned:
                raise RuntimeError(f"banned years leaked: {leaked_banned}")

            candidate_id = f"{base_id}__{filter_name}"
            ledger_path = os.path.join(out_dir, f"{candidate_id}_trades.csv")
            ex_df.to_csv(ledger_path, index=False)
            all_ledgers[candidate_id] = ledger_path

            if filter_name == "NO_VXN_FILTER":
                base_executed_count = len(ex_df)
            retained_pct = round(100.0 * len(ex_df) / base_executed_count, 2) if base_executed_count else None

            full = ex_df
            orig_build = ex_df[ex_df["year"].isin(ORIGINAL_BUILD_YEARS)] if len(ex_df) else ex_df
            former_val = ex_df[ex_df["year"].isin(FORMER_VALIDATION_YEARS)] if len(ex_df) else ex_df

            row = dict(base=base_id, filter=filter_name, candidate=candidate_id,
                       retained_pct_of_no_filter=retained_pct)
            row.update({f"combined_{k}": v for k, v in compute_row(full["pnl"] if len(full) else pd.Series(dtype=float),
                                                                     full["cap"] if len(full) else pd.Series(dtype=float)).items()})
            row.update({f"origbuild_{k}": v for k, v in compute_row(orig_build["pnl"] if len(orig_build) else pd.Series(dtype=float),
                                                                      orig_build["cap"] if len(orig_build) else pd.Series(dtype=float)).items()})
            row.update({f"formerval_{k}": v for k, v in compute_row(former_val["pnl"] if len(former_val) else pd.Series(dtype=float),
                                                                      former_val["cap"] if len(former_val) else pd.Series(dtype=float)).items()})
            row.update({f"combined_{k}": v for k, v in daily_stats(full).items()})
            row.update({f"combined_{k}": v for k, v in exit_counts(full).items()})

            # best-year-exclusion + best-year-share, computed on combined sample
            year_nets = {yr: float(year_of(full, yr)["pnl"].sum()) for yr in FULL_YEARS}
            if any(v != 0 for v in year_nets.values()):
                best_yr = max(year_nets, key=lambda yr: year_nets[yr])
                net_excl_best = row["combined_net_pts"] - year_nets[best_yr]
                pos_total = sum(v for v in year_nets.values() if v > 0)
                best_share = (year_nets[best_yr] / pos_total) if pos_total > 0 else None
            else:
                best_yr, net_excl_best, best_share = None, row["combined_net_pts"], None
            row["combined_best_year"] = best_yr
            row["combined_net_pts_excl_best_year"] = round(net_excl_best, 2)
            row["combined_best_year_pct_of_positive_net"] = round(best_share * 100, 2) if best_share is not None else None

            candidate_rows.append(row)

            for yr in FULL_YEARS:
                sub = year_of(full, yr)
                yrow = dict(base=base_id, filter=filter_name, candidate=candidate_id, year=yr)
                yrow.update(compute_row(sub["pnl"] if len(sub) else pd.Series(dtype=float),
                                         sub["cap"] if len(sub) else pd.Series(dtype=float)))
                per_year_rows.append(yrow)

    cand_df = pd.DataFrame(candidate_rows)
    peryr_df = pd.DataFrame(per_year_rows)
    cand_df.to_csv(os.path.join(out_dir, "vxn_candidate_summary.csv"), index=False)
    peryr_df.to_csv(os.path.join(out_dir, "vxn_per_year.csv"), index=False)

    # mechanism diagnostic (bucket by vxn_prev_close, pooled across both bases and per-base)
    bucket_rows = []
    for base_id in list(BASES.keys()) + ["ALL_BASES"]:
        ledger_path = os.path.join(out_dir, f"{base_id}__NO_VXN_FILTER_trades.csv") if base_id != "ALL_BASES" else None
        if base_id == "ALL_BASES":
            dfs = [pd.read_csv(os.path.join(out_dir, f"{b}__NO_VXN_FILTER_trades.csv")) for b in BASES]
            df = pd.concat(dfs, ignore_index=True)
        else:
            df = pd.read_csv(ledger_path)
        if len(df) == 0:
            continue
        def bucket(v):
            if pd.isna(v):
                return "NO_VXN_AVAILABLE"
            if v < 20:
                return "<20"
            if v < 25:
                return "20-25"
            if v < 30:
                return "25-30"
            return ">=30"
        df["bucket"] = df["vxn_prev_close"].apply(bucket)
        for b, sub in df.groupby("bucket"):
            capr = sub["pnl"] / sub["cap"]
            bucket_rows.append(dict(
                base=base_id, bucket=b, n_trades=len(sub),
                avg_stop_cap=round(float(sub["cap"].mean()), 3),
                median_stop_cap=round(float(sub["cap"].median()), 3),
                net_pts=round(float(sub["pnl"].sum()), 2),
                total_R=round(float(capr.sum()), 4),
                avg_R_per_trade=round(float(capr.mean()), 4),
                PF_pts=round(profit_factor(sub["pnl"]), 4),
                PF_R=round(profit_factor(capr), 4),
            ))
    bucket_df = pd.DataFrame(bucket_rows)
    bucket_df.to_csv(os.path.join(out_dir, "vxn_mechanism_buckets.csv"), index=False)

    # hashes of ledgers for determinism check
    hashes = {cid: sha256_file(p) for cid, p in all_ledgers.items()}
    with open(os.path.join(out_dir, "ledger_hashes.json"), "w") as f:
        json.dump(hashes, f, indent=2)

    return cand_df, peryr_df, bucket_df, hashes


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    cand_df, peryr_df, bucket_df, hashes = run_matrix(args.out_dir)
    print(f"candidates: {len(cand_df)} rows written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
