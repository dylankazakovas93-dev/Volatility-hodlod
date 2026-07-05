"""EXPERIMENTAL -- NOT part of the frozen baseline. Do not treat any result
from this module as validated, and do not merge it into src/strict_engine.py.

Adds a causal "Anchor-Flow Divergence" entry gate on top of the full frozen
strict-engine mechanics (anchor/cap sizing, conditional BE, time-aware SAL,
session windows, touch-bar stop-first handling, oldest-level-first
simultaneous ordering). Same integration pattern as
src/experimental_v_score_engine.py: the real verified state machine is
reused, and the gate is the only new variable.

Gate logic (as proposed): only take the fade if the 15-minute approach is
moving AGAINST the 60-minute anchor direction (an "exhausted move" fading
into the level), and skip it if the 15m flow agrees with the 60m anchor
(a "breakout momentum" move). No threshold to fit -- this is a directional
sign comparison, not a magnitude cutoff.

Correction from the original proposal: the proposed code referenced
`df['close'].iloc[current_idx]` (the touch bar's OWN close) in both the
60m anchor and 15m flow calculations. Using a bar's own close to decide
whether to enter on that same bar is a same-bar look-ahead -- the bar
hasn't finished yet at the moment of touch. This implementation instead
anchors both legs to `iloc[touch_idx - 1]` (the last fully-closed bar
strictly before the touch), which is the same "no information from the
bar you're acting on" standard the rest of this engine already holds
itself to (see src/strict_engine.py's touch-bar stop-first handling for
the same principle applied elsewhere).

    anchor_direction = close[touch_idx - 61] - close[touch_idx - 1]   # 60m lookback, ending at last closed bar
    flow_direction    = close[touch_idx - 15] - close[touch_idx - 1]   # 15m lookback, ending at last closed bar
    coherent = sign(anchor_direction) != sign(flow_direction)          # trade only if flow opposes anchor

Usage:
    python3 -m src.experimental_anchor_flow_engine \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
        --out-dir outputs_experimental
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv, load_gvz_daily  # noqa: E402
from src.level_generation import NQ_PARAMS, generate_levels  # noqa: E402
from src.metrics import profit_factor, max_drawdown, max_loss_streak  # noqa: E402
from src.strict_engine import (  # noqa: E402
    SL_CAP,
    entry_allowed, session_date, session_cutoff, bar_ranges, prev_completed_range,
    physical_touches, touch_is_clean, simulate_from_touch,
)

ANCHOR_LOOKBACK_BARS = 60
FLOW_LOOKBACK_BARS = 15


def is_regime_coherent(bars, touch_positional_idx):
    """True if the 15m approach is moving AGAINST the 60m anchor (an
    exhausted-move fade setup) -- i.e. the trade is allowed. False if the
    15m flow agrees with the 60m anchor (a breakout-momentum move) -- the
    trade is skipped. Both legs end at the last fully-closed bar strictly
    before the touch bar (touch_idx - 1), never the touch bar itself."""
    if touch_positional_idx < ANCHOR_LOOKBACK_BARS + 1:
        return False  # not enough history -- conservative default: skip
    closes = bars["close"].to_numpy()
    ref_idx = touch_positional_idx - 1
    anchor_direction = closes[ref_idx - ANCHOR_LOOKBACK_BARS] - closes[ref_idx]
    flow_direction = closes[ref_idx - FLOW_LOOKBACK_BARS] - closes[ref_idx]
    if anchor_direction == 0 or flow_direction == 0:
        return False  # no clear direction on one leg -- conservative default: skip
    return np.sign(anchor_direction) != np.sign(flow_direction)


def run_strict_with_anchor_flow_gate(bars, ranges, events, tie_order="age"):
    touched = [e for e in events if e["touched_at"] is not None]

    for e in touched:
        pos = bars.index.get_indexer([e["touched_at"]])[0]
        e["_bar_pos"] = pos
        e["prior_close"] = float(bars["close"].iloc[pos - 1]) if pos > 0 else float(bars["close"].iloc[pos])
        e["dist_prior_close"] = abs(e["level"] - e["prior_close"])

    groups = defaultdict(list)
    for e in touched:
        groups[e["touched_at"]].append(e)

    executed = []
    skip_counts = defaultdict(int)
    incoherent_rejected = 0
    pos_exit_time = None
    sal_session = None
    sal_armed_at = None

    for ts in sorted(groups.keys()):
        group = groups[ts]

        anchor = prev_completed_range(ranges, ts)
        if anchor is None:
            skip_counts["no_anchor"] += len(group)
            continue
        if not entry_allowed(ts):
            skip_counts["blocked_time"] += len(group)
            continue
        cutoff = session_cutoff(ts)
        if cutoff is None:
            skip_counts["no_cutoff"] += len(group)
            continue

        sess = session_date(ts)
        if sess != sal_session:
            sal_session = sess
            sal_armed_at = None
        if sal_armed_at is not None and ts >= sal_armed_at:
            skip_counts["SAL"] += len(group)
            continue

        if pos_exit_time is not None and ts < pos_exit_time:
            skip_counts["position_open"] += len(group)
            continue
        if pos_exit_time is not None and ts == pos_exit_time:
            skip_counts["same_bar_reentry"] += len(group)
            continue

        if len(group) > 1:
            ordered = sorted(group, key=lambda e: (e["created_at"], e["side"]))
            chosen, losers = ordered[0], ordered[1:]
            skip_counts["simultaneous_collision"] += len(losers)
        else:
            chosen = group[0]

        if not is_regime_coherent(bars, chosen["_bar_pos"]):
            incoherent_rejected += 1
            continue

        sign = -1.0 if chosen["side"] == "upper" else 1.0
        cap = min(1.5 * anchor, SL_CAP)
        clean = touch_is_clean(bars, ts, chosen["level"])
        fill = chosen["level"] if clean else float(bars.loc[ts, "close"])
        pnl, ex, exit_ts = simulate_from_touch(bars, ts, cutoff, fill, sign, cap)

        year = pd.Timestamp(sess).year
        executed.append({
            "level_id": chosen["level_id"], "session_date": sess, "year": year,
            "side": chosen["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": fill, "exit_price": fill + sign * pnl,
            "anchor": anchor, "cap": cap,
            "exit_reason": ex, "pnl": pnl,
        })
        pos_exit_time = exit_ts
        if pnl < -0.1 and ex != "BE":
            sal_armed_at = exit_ts

    ex_df = pd.DataFrame(executed)
    summary = {"incoherent_rejected": incoherent_rejected, "executed": len(ex_df)}
    if len(ex_df):
        pnl = ex_df["pnl"]
        exs = ex_df["exit_reason"].value_counts()
        summary.update({
            "net_pts": round(float(pnl.sum()), 2),
            "PF": round(profit_factor(pnl), 4),
            "TP": int(exs.get("TP", 0)), "SL": int(exs.get("SL", 0)),
            "BE": int(exs.get("BE", 0)), "cutoff": int(exs.get("cutoff", 0)),
            "max_drawdown": round(max_drawdown(pnl), 2),
            "max_loss_streak": max_loss_streak(ex_df["exit_reason"].tolist(), pnl.tolist()),
        })
        yearly = []
        for yr, s in ex_df.groupby("year"):
            yearly.append({"year": int(yr), "n": len(s), "net_pts": round(float(s["pnl"].sum()), 2),
                           "PF": round(profit_factor(s["pnl"]), 4)})
        summary["yearly"] = yearly
        summary["negative_years"] = sorted(y["year"] for y in yearly if y["net_pts"] < 0)
    return summary, ex_df


def _assert_invariants(ex_df, total_physical_touches):
    assert len(ex_df) <= total_physical_touches
    if len(ex_df) > 1:
        ordered = ex_df.sort_values("entry_time").reset_index(drop=True)
        entry = pd.to_datetime(ordered["entry_time"], utc=True)
        exit_ = pd.to_datetime(ordered["exit_time"], utc=True)
        for i in range(1, len(ordered)):
            assert entry.iloc[i] >= exit_.iloc[i - 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", default="outputs_experimental")
    args = ap.parse_args()

    out_dir = os.path.join(REPO_ROOT, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)
    total_physical_touches = sum(1 for e in events if e["touched_at"] is not None)

    summary, ex_df = run_strict_with_anchor_flow_gate(bars, ranges, events)
    _assert_invariants(ex_df, total_physical_touches)

    print(f"total physical touches: {total_physical_touches}")
    print(json.dumps({k: v for k, v in summary.items() if k != "yearly"}, indent=2))
    print("\nannual:")
    for y in summary.get("yearly", []):
        print(f"  {y['year']}: n={y['n']:3d}  net={y['net_pts']:>+9.2f}  PF={y['PF']:.4f}")

    ex_df.to_csv(os.path.join(out_dir, "anchor_flow_executed.csv"), index=False)
    with open(os.path.join(out_dir, "anchor_flow_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\noutputs written to {out_dir}/")
    print("\nREMINDER: this is an experimental, unauthorized-for-baseline gate.")
    print("Not evidence of an improvement without fold gates + walk-forward. See docs/EXPERIMENTAL_ANCHOR_FLOW.md.")


if __name__ == "__main__":
    main()
