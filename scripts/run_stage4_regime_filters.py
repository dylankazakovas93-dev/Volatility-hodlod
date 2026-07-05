#!/usr/bin/env python3
"""Stage 4 Part C: regime-gated replay using the frozen Stage 3 primary
management rule (profit_lock_0.75R: BE-style stop move to +0.10R after
+0.75R favourable, next-bar activation), E-F entry window, frozen F2
TP/SL, SAL off, gross P&L, development years only.

Usage:
    python3 scripts/run_stage4_regime_filters.py --bars ... --out-dir outputs
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

from src.data_loader import load_1m_ohlcv  # noqa: E402
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table  # noqa: E402
from scripts.stage2_engine import (  # noqa: E402
    fit_frozen_formula, apply_frozen_formula, DEV_YEARS,
    minutes_since_session_start, window_allows,
)
import scripts.stage3_engine as s3  # noqa: E402

WINDOW_BLOCKS = set("EF")
MGMT_KWARGS = {"trigger_r": 0.75, "lock_r": 0.10}


def run_gated_replay(bars, master_with_dist, regime_allow_fn):
    df = master_with_dist.dropna(subset=["tp_dist_stage2", "sl_dist_stage2"]).sort_values("touched_at")

    executed = []
    skip_counts = {"blocked_reserved_year": 0, "blocked_window": 0, "blocked_regime": 0,
                   "position_open": 0, "same_bar_reentry": 0}
    position_open_until = None

    for row in df.itertuples(index=False):
        ts = getattr(row, "touched_at")
        sess = getattr(row, "session_date")
        year = getattr(row, "year")

        if year not in DEV_YEARS:
            skip_counts["blocked_reserved_year"] += 1
            continue

        minutes_elapsed = minutes_since_session_start(ts, sess)
        if not window_allows(WINDOW_BLOCKS, minutes_elapsed):
            skip_counts["blocked_window"] += 1
            continue

        if not regime_allow_fn(row):
            skip_counts["blocked_regime"] += 1
            continue

        if position_open_until is not None and ts < position_open_until:
            skip_counts["position_open"] += 1
            continue
        if position_open_until is not None and ts == position_open_until:
            skip_counts["same_bar_reentry"] += 1
            continue

        side = getattr(row, "side")
        sign = 1.0 if side == "lower" else -1.0
        entry_price = getattr(row, "entry_price")
        cutoff_ts = getattr(row, "forced_liquidation_ts")
        tp_dist = getattr(row, "tp_dist_stage2")
        sl_dist = getattr(row, "sl_dist_stage2")

        pnl, reason, exit_ts, audit = s3.simulate_exact_r_be(
            bars, ts, cutoff_ts, entry_price, sign, tp_dist, sl_dist, **MGMT_KWARGS)

        hold_minutes = int((exit_ts - ts) / pd.Timedelta(minutes=1))
        executed.append({
            "level_id": getattr(row, "level_id"), "session_date": sess, "year": year,
            "side": side, "entry_time": ts, "exit_time": exit_ts,
            "entry_price": entry_price, "tp_dist": tp_dist, "sl_dist": sl_dist,
            "pnl_pts": pnl, "r_multiple": pnl / sl_dist, "exit_reason": reason,
            "hold_minutes": hold_minutes,
        })
        position_open_until = exit_ts

    return pd.DataFrame(executed), skip_counts


def summarize(executed, dev_years=DEV_YEARS):
    dev = executed[executed["year"].isin(dev_years)]
    out = {"n_trades": len(dev)}
    if len(dev) == 0:
        return out
    pnl, r = dev["pnl_pts"], dev["r_multiple"]
    out.update({
        "net_pts": round(float(pnl.sum()), 2), "PF": round(profit_factor(pnl), 4),
        "avg_R": round(float(r.mean()), 4), "max_dd_pts": round(max_drawdown(pnl), 2),
        "max_dd_R": round(max_drawdown(r), 4),
    })
    counts = dev["exit_reason"].value_counts().to_dict()
    for k in ("TP", "SL", "BE", "LOCK", "cutoff"):
        out[f"n_{k}"] = int(counts.get(k, 0))
    tp_only = dev[dev["exit_reason"] == "TP"]
    out["true_tp_win_rate"] = round(len(tp_only) / len(dev), 4)
    for side, s in dev.groupby("side"):
        out[f"{side}_n"] = len(s)
        out[f"{side}_net_pts"] = round(float(s["pnl_pts"].sum()), 2)
    yearly = {}
    for yr, s in dev.groupby("year"):
        yearly[int(yr)] = {"n": len(s), "net_pts": round(float(s["pnl_pts"].sum()), 2),
                            "PF": round(profit_factor(s["pnl_pts"]), 4)}
    out["yearly"] = yearly
    ex2026 = dev[dev["year"] != 2026]
    if len(ex2026):
        out["ex_2026_net_pts"] = round(float(ex2026["pnl_pts"].sum()), 2)
        out["ex_2026_PF"] = round(profit_factor(ex2026["pnl_pts"]), 4)
    return out


def build_master_with_regime(out_dir, bars_arg):
    master = build_master_table(out_dir)
    master["conventional_mfe_pts"] = master["mfe"].clip(lower=0)
    master["conventional_mae_pts"] = (-master["mae"]).clip(lower=0)
    frozen = fit_frozen_formula(master, 0.50, 0.50, DEV_YEARS)
    full_df = apply_frozen_formula(master, frozen)
    regime = pd.read_csv(os.path.join(REPO_ROOT, out_dir, "stage4_regime_features.csv"))
    regime = regime[["level_id", "garch_variance", "garch_percentile",
                     "hmm2_state", "hmm2_prob", "hmm3_state", "hmm3_prob"]]
    full_df = full_df.merge(regime, on="level_id", how="left")
    full_df["touched_at"] = pd.to_datetime(full_df["touched_at"], utc=True)
    full_df["forced_liquidation_ts"] = pd.to_datetime(full_df["forced_liquidation_ts"], utc=True)
    return full_df


def no_filter(row):
    return True


def garch_bucket_filter(lo_pct, hi_pct, keep):
    def fn(row):
        p = getattr(row, "garch_percentile")
        if p is None or (isinstance(p, float) and np.isnan(p)):
            return False
        if p < lo_pct:
            bucket = "LOW"
        elif p > hi_pct:
            bucket = "HIGH"
        else:
            bucket = "MID"
        return bucket in keep
    return fn


def hmm_filter(col_state, keep_states):
    def fn(row):
        s = getattr(row, col_state)
        if s is None or (isinstance(s, float) and np.isnan(s)):
            return False
        return s in keep_states
    return fn


def hmm_confidence_diag(col_prob, min_conf):
    def fn(row):
        p = getattr(row, col_prob)
        if p is None or (isinstance(p, float) and np.isnan(p)):
            return False
        return p >= min_conf
    return fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = args.out_dir

    bars = load_1m_ohlcv(args.bars)
    full_df = build_master_with_regime(out_dir, args.bars)

    candidates = {"no_filter": no_filter}
    # GARCH primary (33/67) + robustness (25/75, 40/60)
    for lo, hi, tag in [(33, 67, "3367"), (25, 75, "2575"), (40, 60, "4060")]:
        candidates[f"garch_LOW_only_{tag}"] = garch_bucket_filter(lo, hi, {"LOW"})
        candidates[f"garch_MID_only_{tag}"] = garch_bucket_filter(lo, hi, {"MID"})
        candidates[f"garch_HIGH_only_{tag}"] = garch_bucket_filter(lo, hi, {"HIGH"})
        candidates[f"garch_exclude_LOW_{tag}"] = garch_bucket_filter(lo, hi, {"MID", "HIGH"})
        candidates[f"garch_exclude_HIGH_{tag}"] = garch_bucket_filter(lo, hi, {"LOW", "MID"})

    candidates["hmm2_LOW_only"] = hmm_filter("hmm2_state", {"LOW_VOL"})
    candidates["hmm2_HIGH_only"] = hmm_filter("hmm2_state", {"HIGH_VOL"})

    for st in ("LOW_VOL", "MID_VOL", "HIGH_VOL"):
        candidates[f"hmm3_{st}_only"] = hmm_filter("hmm3_state", {st})
        others = {"LOW_VOL", "MID_VOL", "HIGH_VOL"} - {st}
        candidates[f"hmm3_exclude_{st}"] = hmm_filter("hmm3_state", others)

    rows = []
    for name, fn in candidates.items():
        executed, skip = run_gated_replay(bars, full_df, fn)
        executed.to_csv(os.path.join(REPO_ROOT, out_dir, f"stage4_ledger_{name}.csv"), index=False)
        summ = summarize(executed)
        row = {"candidate": name, "skip_counts": json.dumps(skip)}
        row.update({k: v for k, v in summ.items() if k != "yearly"})
        row["yearly_json"] = json.dumps(summ.get("yearly", {}))
        rows.append(row)
        print(f"{name}: n={summ.get('n_trades')} net={summ.get('net_pts')} PF={summ.get('PF')}", file=sys.stderr)

    # HMM confidence diagnostics (reported separately, not new candidates)
    conf_rows = []
    for col_state, col_prob, label in [("hmm2_state", "hmm2_prob", "hmm2"), ("hmm3_state", "hmm3_prob", "hmm3")]:
        for min_conf in (0.55, 0.65):
            fn = hmm_confidence_diag(col_prob, min_conf)
            executed, skip = run_gated_replay(bars, full_df, fn)
            summ = summarize(executed)
            conf_rows.append({"model": label, "min_confidence": min_conf,
                               "n_trades": summ.get("n_trades"), "net_pts": summ.get("net_pts"),
                               "PF": summ.get("PF")})

    cand_df = pd.DataFrame(rows)
    cand_df.to_csv(os.path.join(REPO_ROOT, out_dir, "stage4_candidate_summary.csv"), index=False)
    pd.DataFrame(conf_rows).to_csv(os.path.join(REPO_ROOT, out_dir, "stage4_hmm_confidence_diagnostic.csv"), index=False)

    print(cand_df[["candidate", "n_trades", "net_pts", "PF"]].to_string())


if __name__ == "__main__":
    main()
