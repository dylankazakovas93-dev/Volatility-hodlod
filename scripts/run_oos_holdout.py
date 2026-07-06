#!/usr/bin/env python3
"""LOCKED_NONCONSECUTIVE_HOLDOUT: the final, one-shot locked out-of-sample
test of the frozen strategy (F2 TP/SL + profit_lock_0.75R + entry window
05:00-11:00 ET + 15:59 ET cutoff + hmm3_exclude_LOW_VOL) on the five
reserved years: 2019, 2021, 2022, 2024, 2025.

This is NOT a walk-forward test -- the strategy was developed using later,
non-consecutive years (2018, 2020, 2023, partial 2026), so these reserved
years are a locked, nonconsecutive holdout, not a historical forward test.

Nothing here may be changed after viewing reserved-year performance. See
docs/OOS_PRE_LOCK.md for the exact frozen configuration and pass/fail
criteria, committed BEFORE this script is ever run against reserved-year
data (the PRE_OOS_LOCK commit).

Usage:
    python3 scripts/run_oos_holdout.py --bars ... --out-dir outputs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table  # noqa: E402
from scripts.stage2_engine import fit_frozen_formula, apply_frozen_formula, DEV_YEARS, RESERVED_YEARS  # noqa: E402
from scripts.oos_engine import (  # noqa: E402
    run_oos_replay, state_before_rich, state_before_pine,
)

PINE_YEARS = [2024, 2025]


def df_hash(df):
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()


def longest_loss_streak(pnl_series):
    streak = best = 0
    for p in pnl_series:
        if p < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def year_metrics(ledger, year):
    d = ledger[(ledger["year"] == year) & (ledger["skip_reason"].isna())]
    out = {"n_trades": len(d)}
    if len(d) == 0:
        return out
    pnl, r = d["pnl_pts"], d["r_multiple"]
    out.update({
        "net_pts": round(float(pnl.sum()), 2), "total_R": round(float(r.sum()), 4),
        "avg_R": round(float(r.mean()), 4),
        "PF_pts": round(profit_factor(pnl), 4),
        "PF_R": round(profit_factor(r), 4),
        "max_dd_pts": round(max_drawdown(pnl), 2), "max_dd_R": round(max_drawdown(r), 4),
        "longest_loss_streak": longest_loss_streak(pnl.to_numpy()),
        "avg_tp": round(float(d["tp_dist"].mean()), 3), "avg_sl": round(float(d["sl_dist"].mean()), 3),
        "avg_structural_rr": round(float((d["tp_dist"] / d["sl_dist"]).mean()), 4),
        "true_tp_win_rate": round(float((d["exit_reason"] == "TP").mean()), 4),
        "TP_exits": int((d["exit_reason"] == "TP").sum()),
        "SL_exits": int((d["exit_reason"] == "SL").sum()),
        "LOCK_exits": int((d["exit_reason"] == "LOCK").sum()),
        "cutoff_exits": int((d["exit_reason"] == "cutoff").sum()),
        "long_n": int((d["side"] == "lower").sum()), "short_n": int((d["side"] == "upper").sum()),
        "long_net_pts": round(float(d.loc[d["side"] == "lower", "pnl_pts"].sum()), 2),
        "short_net_pts": round(float(d.loc[d["side"] == "upper", "pnl_pts"].sum()), 2),
        "avg_hold_minutes": round(float(((d["exit_time"] - d["entry_time"]) / pd.Timedelta(minutes=1)).mean()), 2),
        "median_hold_minutes": round(float(((d["exit_time"] - d["entry_time"]) / pd.Timedelta(minutes=1)).median()), 2),
    })
    return out


def pooled_metrics(ledger, years):
    d = ledger[ledger["year"].isin(years) & ledger["skip_reason"].isna()]
    n = len(d)
    if n == 0:
        return {"n_trades": 0}
    pnl, r = d["pnl_pts"], d["r_multiple"]
    result = {
        "n_trades": n, "net_pts": round(float(pnl.sum()), 2), "total_R": round(float(r.sum()), 4),
        "avg_R": round(float(r.mean()), 4),
        "PF_pts": round(profit_factor(pnl), 4), "PF_R": round(profit_factor(r), 4),
        "max_dd_pts": round(max_drawdown(pnl), 2), "max_dd_R": round(max_drawdown(r), 4),
        "longest_loss_streak": longest_loss_streak(pnl.to_numpy()),
        "avg_tp": round(float(d["tp_dist"].mean()), 3), "avg_sl": round(float(d["sl_dist"].mean()), 3),
        "avg_structural_rr": round(float((d["tp_dist"] / d["sl_dist"]).mean()), 4),
        "true_tp_win_rate": round(float((d["exit_reason"] == "TP").mean()), 4),
        "TP_exits": int((d["exit_reason"] == "TP").sum()),
        "SL_exits": int((d["exit_reason"] == "SL").sum()),
        "LOCK_exits": int((d["exit_reason"] == "LOCK").sum()),
        "cutoff_exits": int((d["exit_reason"] == "cutoff").sum()),
        "long_n": int((d["side"] == "lower").sum()), "short_n": int((d["side"] == "upper").sum()),
        "long_net_pts": round(float(d.loc[d["side"] == "lower", "pnl_pts"].sum()), 2),
        "short_net_pts": round(float(d.loc[d["side"] == "upper", "pnl_pts"].sum()), 2),
        "avg_hold_minutes": round(float(((d["exit_time"] - d["entry_time"]) / pd.Timedelta(minutes=1)).mean()), 2),
        "median_hold_minutes": round(float(((d["exit_time"] - d["entry_time"]) / pd.Timedelta(minutes=1)).median()), 2),
        "monthly_distribution": {
            str(k): {"n": int(v["level_id"].count()), "net_pts": round(float(v["pnl_pts"].sum()), 2)}
            for k, v in d.assign(month=d["entry_time"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m")).groupby("month")
        },
    }
    return result


def annual_equity_path(ledger, years):
    d = ledger[ledger["year"].isin(years) & ledger["skip_reason"].isna()].sort_values("entry_time")
    d = d.assign(cum_pts=d["pnl_pts"].cumsum(), cum_R=d["r_multiple"].cumsum())
    return d[["entry_time", "year", "pnl_pts", "r_multiple", "cum_pts", "cum_R"]]


def apply_verdict(pooled, per_year, years):
    n = pooled.get("n_trades", 0)
    pf = pooled.get("PF_pts", 0.0)
    total_r = pooled.get("total_R", 0.0)
    years_pos_r = sum(1 for y in years if per_year[y].get("total_R", -1) > 0)
    years_pf_105 = sum(1 for y in years if per_year[y].get("PF_pts", 0) > 1.05)

    strong = (pf >= 1.20 and total_r > 0 and years_pos_r >= 3 and years_pf_105 >= 3 and n >= 200)
    marginal = (pf > 1.05 and total_r > 0 and years_pos_r >= 2 and n >= 150)

    if strong:
        return "OOS_STRONG_PASS", years_pos_r, years_pf_105
    if marginal:
        return "OOS_MARGINAL_PASS", years_pos_r, years_pf_105
    return "OOS_FAIL", years_pos_r, years_pf_105


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    bars = load_1m_ohlcv(args.bars)
    master = build_master_table(out_dir)
    master["conventional_mfe_pts"] = master["mfe"].clip(lower=0)
    master["conventional_mae_pts"] = (-master["mae"]).clip(lower=0)
    frozen = fit_frozen_formula(master, 0.50, 0.50, DEV_YEARS)
    full_df = apply_frozen_formula(master, frozen)
    full_df["touched_at"] = pd.to_datetime(full_df["touched_at"], utc=True)
    full_df["forced_liquidation_ts"] = pd.to_datetime(full_df["forced_liquidation_ts"], utc=True)

    with open(os.path.join(out_dir, "oos_hmm3_rolling_cache.pkl"), "rb") as f:
        rolling_cache = pickle.load(f)
    with open(os.path.join(out_dir, "oos_pine_cache.pkl"), "rb") as f:
        pine_cache_data = pickle.load(f)

    cache_probs, cache_meta = rolling_cache["cache_probs"], rolling_cache["cache_meta"]
    pine_cache = pine_cache_data["cache"]

    # -------------------- ROLLING_PYTHON_HMM: all 5 reserved years --------------------
    def rolling_lookup(session, ts):
        return state_before_rich(cache_probs, cache_meta, session, ts)

    ledger_rolling, skip_counts_rolling = run_oos_replay(bars, full_df, rolling_lookup, RESERVED_YEARS)
    ledger_rolling.to_csv(os.path.join(out_dir, "oos_ledger_rolling_python_hmm.csv"), index=False)

    pooled_rolling = pooled_metrics(ledger_rolling, RESERVED_YEARS)
    per_year_rolling = {y: year_metrics(ledger_rolling, y) for y in RESERVED_YEARS}

    best_year = max(RESERVED_YEARS, key=lambda y: per_year_rolling[y].get("net_pts", -1e18))
    ex_best = pooled_metrics(ledger_rolling, [y for y in RESERVED_YEARS if y != best_year])
    worst_year = min(RESERVED_YEARS, key=lambda y: per_year_rolling[y].get("net_pts", 1e18))
    ex_worst = pooled_metrics(ledger_rolling, [y for y in RESERVED_YEARS if y != worst_year])

    total_net = pooled_rolling.get("net_pts", 0.0)
    best_year_pct_of_profit = (
        round(100.0 * per_year_rolling[best_year].get("net_pts", 0.0) / total_net, 2)
        if total_net not in (0, None) else None
    )

    verdict, years_pos_r, years_pf_105 = apply_verdict(pooled_rolling, per_year_rolling, RESERVED_YEARS)

    equity_path = annual_equity_path(ledger_rolling, RESERVED_YEARS)
    equity_path.to_csv(os.path.join(out_dir, "oos_annual_equity_path.csv"), index=False)

    # -------------------- FROZEN_PINE_HMM: 2024/2025 ONLY, separate replay --------------------
    def pine_lookup(session, ts):
        label, prob = state_before_pine(pine_cache, session, ts)
        return {"hmm_state": label, "hmm_prob": prob}

    ledger_pine, skip_counts_pine = run_oos_replay(bars, full_df, pine_lookup, PINE_YEARS)
    ledger_pine.to_csv(os.path.join(out_dir, "oos_ledger_frozen_pine_hmm.csv"), index=False)
    pooled_pine = pooled_metrics(ledger_pine, PINE_YEARS)
    per_year_pine = {y: year_metrics(ledger_pine, y) for y in PINE_YEARS}

    # trade-by-trade agreement between the two systems, restricted to the
    # 2024/2025 touches both systems evaluate (never pooled)
    rolling_2425 = ledger_rolling[ledger_rolling["year"].isin(PINE_YEARS)][["level_id", "skip_reason", "hmm_state", "exit_reason"]]
    pine_2425 = ledger_pine[ledger_pine["year"].isin(PINE_YEARS)][["level_id", "skip_reason", "hmm_state", "exit_reason"]]
    merged = rolling_2425.merge(pine_2425, on="level_id", suffixes=("_roll", "_pine"))
    state_agree = float((merged["hmm_state_roll"] == merged["hmm_state_pine"]).mean()) if len(merged) else None
    allow_agree = float(
        ((merged["skip_reason_roll"].isna()) == (merged["skip_reason_pine"].isna())).mean()
    ) if len(merged) else None
    both_entered = merged[merged["skip_reason_roll"].isna() & merged["skip_reason_pine"].isna()]
    exit_agree = float((both_entered["exit_reason_roll"] == both_entered["exit_reason_pine"]).mean()) if len(both_entered) else None

    # -------------------- skip-reason reconciliation --------------------
    reserved_all = full_df[full_df["year"].isin(RESERVED_YEARS)]
    skip_recon = {
        "total_reserved_year_touches_in_master": int(len(reserved_all)),
        "total_rows_in_rolling_ledger": int(len(ledger_rolling[ledger_rolling["year"].isin(RESERVED_YEARS)])),
        "skip_counts": skip_counts_rolling,
        "executed": int(pooled_rolling.get("n_trades", 0)),
    }

    # -------------------- hashes --------------------
    hashes = {
        "bars_file_sha256": hashlib.sha256(open(args.bars, "rb").read()).hexdigest(),
        "ledger_rolling_hash": df_hash(ledger_rolling),
        "ledger_pine_hash": df_hash(ledger_pine),
        "config_hashes": {
            f: hashlib.sha256(open(os.path.join(REPO_ROOT, f), "rb").read()).hexdigest()
            for f in [
                "scripts/oos_engine.py", "scripts/run_oos_holdout.py",
                "scripts/stage2_engine.py", "scripts/stage3_engine.py",
                "scripts/stage4_hmm.py", "scripts/stage4_regime_data.py",
                "scripts/stage5_engine.py",
            ]
        },
    }

    report = {
        "status": verdict,
        "years_with_positive_total_R": years_pos_r,
        "years_with_PF_pts_gt_1.05": years_pf_105,
        "rolling_python_hmm": {
            "pooled": pooled_rolling,
            "per_year": per_year_rolling,
            "best_year": best_year, "best_year_pct_of_pooled_profit": best_year_pct_of_profit,
            "excluding_best_year": ex_best,
            "worst_year": worst_year, "excluding_worst_year": ex_worst,
        },
        "frozen_pine_hmm_2024_2025": {
            "pooled": pooled_pine, "per_year": per_year_pine,
            "state_agreement_pct": round(state_agree * 100, 2) if state_agree is not None else None,
            "allow_block_agreement_pct": round(allow_agree * 100, 2) if allow_agree is not None else None,
            "exit_reason_agreement_pct_given_both_entered": round(exit_agree * 100, 2) if exit_agree is not None else None,
            "n_touches_compared": int(len(merged)),
        },
        "skip_reason_reconciliation": skip_recon,
        "hashes": hashes,
    }
    with open(os.path.join(out_dir, "oos_final_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(json.dumps({"status": verdict, "pooled_rolling": pooled_rolling}, indent=2, default=str))


if __name__ == "__main__":
    main()
