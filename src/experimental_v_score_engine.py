"""EXPERIMENTAL -- NOT part of the frozen baseline. Do not treat any result
from this module as validated, and do not merge it into src/strict_engine.py.

Adds a causal "V-Score" entry gate on top of the full frozen strict-engine
mechanics (anchor/cap sizing, conditional BE, time-aware SAL, session
windows, touch-bar stop-first handling, oldest-level-first simultaneous
ordering) -- unlike the toy skeleton this was originally proposed as, this
reuses the actual verified state machine from src/strict_engine.py so the
V-Score gate is the ONLY new variable, not a different backtest engine.

V-Score definition (causal, no lookahead): for the 15 bars strictly
BEFORE the touch bar,
    v_score = abs(close[-1] - open[0]) / sum(volume)
A trade is only taken if v_score >= v_score_threshold.

The threshold is fixed BEFORE looking at any result on this dataset (not
fit to 2026 or any other slice) -- see V_SCORE_THRESHOLDS below and
docs/EXPERIMENTAL_V_SCORE.md for the stated rationale. This module reports
results at each preset threshold as an illustrative sweep, not a
data-driven optimization; no threshold here is presented as "selected."

Usage:
    python3 -m src.experimental_v_score_engine \
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

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv, load_gvz_daily  # noqa: E402
from src.level_generation import NQ_PARAMS, generate_levels  # noqa: E402
from src.metrics import profit_factor, max_drawdown, max_loss_streak  # noqa: E402
from src.strict_engine import (  # noqa: E402
    LINE_DAYS, SL_CAP, BE_BARS,
    entry_allowed, session_date, session_cutoff, bar_ranges, prev_completed_range,
    physical_touches, touch_is_clean, simulate_from_touch,
)

# Fixed in advance -- not derived from this dataset. Chosen only to span a
# plausible range of "how much price moved per unit volume in the last 15
# minutes" without having looked at the distribution first.
V_SCORE_THRESHOLDS = [0.0, 0.01, 0.05, 0.1]

V_SCORE_LOOKBACK_BARS = 15


def causal_v_score(bars, touch_positional_idx):
    """V-score from the 15 bars strictly before the touch bar. Returns 0.0
    if fewer than 15 prior bars exist (matches the original proposal's
    `if current_idx < 15: return 0.0` guard)."""
    if touch_positional_idx < V_SCORE_LOOKBACK_BARS:
        return 0.0
    window = bars.iloc[touch_positional_idx - V_SCORE_LOOKBACK_BARS: touch_positional_idx]
    price_delta = abs(float(window["close"].iloc[-1]) - float(window["open"].iloc[0]))
    volume_sum = float(window["volume"].sum()) if "volume" in window.columns else 0.0
    return price_delta / volume_sum if volume_sum > 0 else 0.0


def run_strict_with_v_score_gate(bars, ranges, events, v_score_threshold, tie_order="age"):
    """Identical state machine to src.strict_engine.run_strict, with one
    addition: after all frozen eligibility/SAL/position/simultaneous-touch
    gates pass and a candidate is chosen, an additional causal V-Score check
    can still reject the trade -- the level is consumed either way (a
    V-Score-rejected touch does not become eligible again, matching the
    "once touched, always consumed" rule)."""
    touched = [e for e in events if e["touched_at"] is not None]

    for e in touched:
        pos = bars.index.get_indexer([e["touched_at"]])[0]
        e["_bar_pos"] = pos
        e["prior_close"] = float(bars["close"].iloc[pos - 1]) if pos > 0 else float(bars["close"].iloc[pos])
        e["dist_prior_close"] = abs(e["level"] - e["prior_close"])

    groups = defaultdict(list)
    for e in touched:
        groups[e["touched_at"]].append(e)

    executed, skip_counts = [], defaultdict(int)
    v_score_rejected = 0
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

        v_score = causal_v_score(bars, chosen["_bar_pos"])
        if v_score < v_score_threshold:
            v_score_rejected += 1
            # No position is opened -- pos_exit_time is left untouched (it is
            # already either None or a past timestamp, since we only reach
            # here after the position_open/same_bar_reentry checks passed).
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
            "anchor": anchor, "cap": cap, "v_score": v_score,
            "exit_reason": ex, "pnl": pnl,
        })
        pos_exit_time = exit_ts
        if pnl < -0.1 and ex != "BE":
            sal_armed_at = exit_ts

    ex_df = pd.DataFrame(executed)
    summary = {"v_score_threshold": v_score_threshold, "v_score_rejected": v_score_rejected,
               "executed": len(ex_df)}
    if len(ex_df):
        pnl = ex_df["pnl"]
        exs = ex_df["exit_reason"].value_counts()
        summary.update({
            "net_pts": round(float(pnl.sum()), 2),
            "PF": round(profit_factor(pnl), 4),
            "TP": int(exs.get("TP", 0)), "SL": int(exs.get("SL", 0)),
            "BE": int(exs.get("BE", 0)), "cutoff": int(exs.get("cutoff", 0)),
            "max_drawdown": round(max_drawdown(pnl), 2),
        })
        yearly = {int(yr): round(float(s["pnl"].sum()), 2) for yr, s in ex_df.groupby("year")}
        summary["negative_years"] = sorted(y for y, v in yearly.items() if v < 0)
    return summary, ex_df


def _assert_invariants(ex_df, total_physical_touches):
    """Genuine invariants -- corrected from the original proposal, which
    conflated the eligible-candidate gate (1,841) with the raw physical
    touch population (3,486). The correct bound on ANY attempted-trade
    count is the physical touch population, not the post-gate 1,841."""
    assert len(ex_df) <= total_physical_touches, (
        f"executed count {len(ex_df)} exceeds total physical touches {total_physical_touches}"
    )
    if len(ex_df) > 1:
        ordered = ex_df.sort_values("entry_time").reset_index(drop=True)
        entry = pd.to_datetime(ordered["entry_time"], utc=True)
        exit_ = pd.to_datetime(ordered["exit_time"], utc=True)
        for i in range(1, len(ordered)):
            assert entry.iloc[i] >= exit_.iloc[i - 1], (
                f"overlap detected: trade {i-1} exits {exit_.iloc[i-1]} but "
                f"trade {i} enters {entry.iloc[i]}"
            )


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

    print(f"total physical touches: {total_physical_touches}")
    print(f"V-score thresholds swept (fixed in advance, not fit to any year): {V_SCORE_THRESHOLDS}\n")

    results = {}
    for threshold in V_SCORE_THRESHOLDS:
        summary, ex_df = run_strict_with_v_score_gate(bars, ranges, [dict(e) for e in events], threshold)
        _assert_invariants(ex_df, total_physical_touches)
        results[str(threshold)] = summary
        ex_df.to_csv(os.path.join(out_dir, f"v_score_{threshold}_executed.csv"), index=False)
        print(json.dumps(summary, indent=2))

    with open(os.path.join(out_dir, "v_score_sweep_summary.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\noutputs written to {out_dir}/")
    print("\nREMINDER: this is an experimental, unauthorized-for-baseline sweep.")
    print("No threshold above is presented as selected/optimal -- see docs/EXPERIMENTAL_V_SCORE.md.")


if __name__ == "__main__":
    main()
