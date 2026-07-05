#!/usr/bin/env python3
"""Stage 0 dataset B: one-position, cutoff-only executable control replay.

No TP, no SL, no BE, no SAL, no time-of-day entry filter. Physical first
touches are processed in strict chronological order; a touch is skipped
(consumed, never retried) if a position is already open. Every executed
trade exits only at its session's 15:59 ET forced-liquidation bar close.

This is NOT the independent signal-path dataset (dataset A) -- it is a
complete chronological replay, so which touches get skipped depends on
how long the *previous* trade stayed open, exactly like the verified
strict engine's one-position rule.

Usage:
    python3 scripts/run_stage0_control_replay.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
        --out-dir outputs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv, load_gvz_daily  # noqa: E402
from src.level_generation import NQ_PARAMS, generate_levels  # noqa: E402
from src.strict_engine import physical_touches  # noqa: E402
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from scripts.build_signal_paths import (  # noqa: E402
    gap_or_liquidation_bar, forced_liquidation_ts, research_session_date,
)


def run_control_replay(bars, touched_events):
    events = sorted(touched_events, key=lambda e: e["touched_at"])
    executed = []
    skip_counts = {"gap": 0, "liquidation_bar": 0, "no_valid_path": 0, "position_open": 0, "same_bar_reentry": 0}

    position_open_until = None

    for e in events:
        ts = e["touched_at"]
        cls = gap_or_liquidation_bar(ts)
        if cls != "active":
            skip_counts[cls] += 1
            continue

        if position_open_until is not None and ts < position_open_until:
            skip_counts["position_open"] += 1
            continue
        if position_open_until is not None and ts == position_open_until:
            skip_counts["same_bar_reentry"] += 1
            continue

        cutoff_ts = forced_liquidation_ts(ts)
        side = e["side"]
        level = e["level"]
        sign = 1.0 if side == "lower" else -1.0  # lower touch = long

        touch_row = bars.loc[ts]
        clean = bool(touch_row["low"] <= level <= touch_row["high"])
        entry_price = level if clean else float(touch_row["close"])

        path = bars.loc[ts:cutoff_ts].iloc[1:]
        if path.empty:
            skip_counts["no_valid_path"] += 1
            continue

        exit_price = float(path["close"].iloc[-1])
        pnl = sign * (exit_price - entry_price)
        sess = research_session_date(ts)

        executed.append({
            "level_id": e["level_id"], "session_date": sess, "year": pd.Timestamp(sess).year,
            "side": side, "entry_time": ts, "exit_time": path.index[-1],
            "entry_price": entry_price, "exit_price": exit_price,
            "pnl": pnl, "exit_reason": "cutoff",
        })
        position_open_until = path.index[-1]

    return pd.DataFrame(executed), skip_counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()

    out_dir = os.path.join(REPO_ROOT, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)
    touched = [e for e in events if e["touched_at"] is not None]

    executed, skip_counts = run_control_replay(bars, touched)
    executed.to_csv(os.path.join(out_dir, "stage0_control_executed.csv"), index=False)

    pnl = executed["pnl"] if len(executed) else pd.Series(dtype=float)
    summary = {
        "physical_touches": len(touched),
        "executed": len(executed),
        "skip_counts": skip_counts,
        "net_pts": round(float(pnl.sum()), 2) if len(pnl) else 0.0,
        "PF": round(profit_factor(pnl), 4) if len(pnl) else None,
        "win_rate": round(float((pnl > 0).mean()), 4) if len(pnl) else None,
        "max_drawdown": round(max_drawdown(pnl), 2) if len(pnl) else None,
        "avg_trade": round(float(pnl.mean()), 3) if len(pnl) else None,
    }
    if len(executed):
        yearly = []
        for yr, s in executed.groupby("year"):
            yearly.append({"year": int(yr), "n": len(s), "net_pts": round(float(s["pnl"].sum()), 2)})
        summary["yearly"] = yearly
        summary["negative_years"] = [y["year"] for y in yearly if y["net_pts"] < 0]

    def sha256_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def git_sha():
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
        except Exception:
            return None

    summary["research_commit"] = git_sha()
    summary["data_hashes"] = {"bars": sha256_file(args.bars), "vxn": sha256_file(args.vxn)}
    summary["reproduction_command"] = (
        f"python3 scripts/run_stage0_control_replay.py --bars {args.bars} --vxn {args.vxn} --out-dir {args.out_dir}"
    )
    with open(os.path.join(out_dir, "stage0_control_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
