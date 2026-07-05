#!/usr/bin/env python3
"""Stage 1 section 20: causal-roll sensitivity series.

Rebuilds the NQ continuous series using a strictly pre-day-causal roll
rule: day D's active contract is the standard quarterly contract with the
highest total volume on the previous completed UTC trading day that has
data (never day D's own volume). Excludes calendar spreads, preserves
unadjusted prices. Any day where the prior day's winner posts zero bars on
day D falls back deterministically to day D's own actual highest-volume
contract for that day, and every such fallback is logged explicitly.

Usage:
    python3 scripts/run_stage1_causal_roll.py \
        --raw <5 decompressed raw csvs via --raw repeated> \
        --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

STANDARD_CONTRACT_RE = r"^NQ[HMUZ]\d$"


def build_daily_volume(raw_paths):
    parts = []
    for p in raw_paths:
        raw = pd.read_csv(p, usecols=["ts_event", "open", "high", "low", "close", "volume", "symbol"])
        raw["ts_event"] = pd.to_datetime(raw["ts_event"], utc=True)
        raw["date"] = raw["ts_event"].dt.date
        standard = raw[raw["symbol"].str.match(STANDARD_CONTRACT_RE)].copy()
        parts.append(standard)
    full = pd.concat(parts).sort_values("ts_event").reset_index(drop=True)
    daily_volume = full.groupby(["date", "symbol"])["volume"].sum().reset_index()
    return full, daily_volume


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="append", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    full, daily_volume = build_daily_volume(args.raw)

    winner_by_day = (
        daily_volume.loc[daily_volume.groupby("date")["volume"].idxmax()]
        [["date", "symbol"]].rename(columns={"symbol": "winner"})
        .sort_values("date").reset_index(drop=True)
    )
    winner_by_day["prior_day_winner"] = winner_by_day["winner"].shift(1)

    dates_with_data = set(full["date"].unique())
    symbols_present_by_day = full.groupby("date")["symbol"].apply(set)

    fallback_log = []
    causal_winner = []
    for _, row in winner_by_day.iterrows():
        d, own_winner, prior_winner = row["date"], row["winner"], row["prior_day_winner"]
        if pd.isna(prior_winner):
            causal_winner.append(own_winner)
            fallback_log.append({"date": str(d), "reason": "no_prior_day", "used": own_winner})
            continue
        present = symbols_present_by_day.get(d, set())
        if prior_winner in present:
            causal_winner.append(prior_winner)
        else:
            causal_winner.append(own_winner)
            fallback_log.append({"date": str(d), "reason": "prior_winner_absent",
                                  "prior_winner": prior_winner, "fallback_used": own_winner})

    winner_by_day["causal_contract"] = causal_winner
    merged = full.merge(winner_by_day[["date", "causal_contract"]], on="date")
    kept = merged[merged["symbol"] == merged["causal_contract"]].sort_values("ts_event")
    kept = kept.drop_duplicates(subset="ts_event")
    result = kept[["ts_event", "open", "high", "low", "close", "volume", "symbol"]].rename(
        columns={"ts_event": "timestamp", "symbol": "contract"})
    result["roll_day"] = (result["contract"] != result["contract"].shift(1)).astype(int)
    if len(result):
        result.iloc[0, result.columns.get_loc("roll_day")] = 0

    out_path = os.path.join(out_dir, "nq_causal_roll_2018_2026_1m.csv")
    result.to_csv(out_path, index=False)

    # compare selected contract per day against the original (same-day) rule
    changed_days = int((winner_by_day["winner"] != winner_by_day["causal_contract"]).sum())

    summary = {
        "rows": len(result),
        "days": len(winner_by_day),
        "changed_selected_contract_days": changed_days,
        "n_fallbacks": len(fallback_log),
        "fallback_log_path": "stage1_causal_roll_fallbacks.json",
        "output_path": out_path,
    }
    with open(os.path.join(out_dir, "stage1_causal_roll_fallbacks.json"), "w") as f:
        json.dump(fallback_log, f, indent=2, default=str)
    with open(os.path.join(out_dir, "stage1_causal_roll_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
