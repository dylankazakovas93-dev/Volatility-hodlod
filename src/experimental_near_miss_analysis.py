"""EXPERIMENTAL -- curiosity/diagnostic only. NOT part of the frozen baseline.

Two parts:

1. DESCRIPTIVE: for every level side that the strict touch rule never
   actually touches (touched_at is None within its live window), find its
   closest approach distance to price, expressed in units of a causal
   3-minute ATR(14) measured at the moment of closest approach. Reports how
   often "near misses" happen and how close they typically get.

2. EXPERIMENTAL VARIANT: for a few preset ATR-tolerance thresholds (fixed
   before looking at any result), simulate what happens if those near
   misses are treated as entry triggers -- filled at the ACTUAL price
   reached (not the pristine level, since a resting limit order at the
   level would never have filled), then run through the identical frozen
   engine (anchor/cap sizing, conditional BE, time-aware SAL, session
   windows). This is a materially different, riskier order design (an
   early/anticipatory entry, not "the same trade happening more often") --
   labeled as such, not glossed over.

Usage:
    python3 -m src.experimental_near_miss_analysis \
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
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from src.strict_engine import (  # noqa: E402
    LINE_DAYS, SL_CAP,
    entry_allowed, session_date, session_cutoff, bar_ranges, prev_completed_range,
    touch_is_clean, simulate_from_touch,
)

# Fixed in advance, not fit to any result.
ATR_TOLERANCE_MULTIPLES = [0.25, 0.5, 1.0]
ATR_PERIOD_BARS_3M = 14  # simple rolling mean of true range over 14 x 3-minute bars


def build_causal_atr_3m(bars_1m):
    """3-minute bars, simple rolling-mean True Range ATR(14). Returns a
    Series indexed by the 3-minute bar's OWN start time; callers must look
    up the most recent bar strictly ending before their reference
    timestamp to stay causal (see atr_as_of)."""
    b3 = bars_1m.resample("3min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    prev_close = b3["close"].shift(1)
    tr = pd.concat([
        b3["high"] - b3["low"],
        (b3["high"] - prev_close).abs(),
        (b3["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(ATR_PERIOD_BARS_3M).mean()
    return atr, b3.index


def atr_as_of(atr_series, atr_index, ts):
    """Most recent 3-minute ATR value from a bar that has FULLY CLOSED
    strictly before `ts` (causal -- never uses the still-forming 3m bar)."""
    bucket_start = ts.floor("3min")
    if ts < bucket_start + pd.Timedelta(minutes=3):
        ref_start = bucket_start - pd.Timedelta(minutes=3)
    else:
        ref_start = bucket_start
    pos = atr_index.searchsorted(ref_start, side="right") - 1
    if pos < 0:
        return None
    val = atr_series.iloc[pos]
    return float(val) if pd.notna(val) else None


def find_closest_approach(bars_1m, window, level_value):
    """For an untouched level side, the minimum |price - level| distance
    reached across its live window, and the timestamp it happened at."""
    if window.empty:
        return None, None
    lo, hi = window["low"].to_numpy(), window["high"].to_numpy()
    dist_from_below = level_value - hi   # positive if level still above the high reached
    dist_from_above = lo - level_value   # positive if level still below the low reached
    dist = np.minimum(np.where(dist_from_below > 0, dist_from_below, np.inf),
                       np.where(dist_from_above > 0, dist_from_above, np.inf))
    idx = int(np.argmin(dist))
    min_dist = float(dist[idx])
    if not np.isfinite(min_dist):
        return None, None
    return min_dist, window.index[idx]


def analyze(bars_1m, lvls, atr_series, atr_index):
    """Returns list of dicts, one per level side: touched_at (None if never
    touched), and for untouched sides, closest_dist / closest_ts / atr_at_ts."""
    n = len(lvls)
    from src.strict_engine import first_touch
    rows = []
    for i, lv in enumerate(lvls):
        expiry = lvls[i + LINE_DAYS].created_at if i + LINE_DAYS < n else bars_1m.index[-1]
        window = bars_1m.loc[lv.created_at: expiry]
        window = window[(window.index > lv.created_at) & (window.index < expiry)]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            level_value = float(col)
            row = {"level_id": f"{i}_{side}", "session_date": lv.session_date,
                   "created_at": lv.created_at, "side": side, "level": level_value}
            if window.empty:
                rows.append(row)
                continue
            touched_at = first_touch(window, level_value)
            if touched_at is not None:
                row["touched_at"] = touched_at
                rows.append(row)
                continue
            min_dist, closest_ts = find_closest_approach(bars_1m, window, level_value)
            row["touched_at"] = None
            row["closest_dist"] = min_dist
            row["closest_ts"] = closest_ts
            if min_dist is not None:
                row["atr_at_closest"] = atr_as_of(atr_series, atr_index, closest_ts)
                if row["atr_at_closest"] and row["atr_at_closest"] > 0:
                    row["dist_in_atr"] = min_dist / row["atr_at_closest"]
            rows.append(row)
    return rows


def run_with_near_miss_entries(bars_1m, ranges, level_rows, tolerance_atr):
    """Same causal state machine as src.strict_engine.run_strict, with
    synthetic near-miss entries added for untouched levels whose closest
    approach was within `tolerance_atr` ATR(3m,14). Fill price = the actual
    extreme price reached (not the pristine level -- a resting limit there
    never would have filled)."""
    events = []
    for r in level_rows:
        if r.get("touched_at") is not None:
            events.append({"level_id": r["level_id"], "session_date": r["session_date"],
                            "created_at": r["created_at"], "side": r["side"], "level": r["level"],
                            "touched_at": r["touched_at"], "fill_override": None})
        elif r.get("dist_in_atr") is not None and r["dist_in_atr"] <= tolerance_atr:
            events.append({"level_id": r["level_id"], "session_date": r["session_date"],
                            "created_at": r["created_at"], "side": r["side"], "level": r["level"],
                            "touched_at": r["closest_ts"], "fill_override": "closest"})

    for e in events:
        pos = bars_1m.index.get_indexer([e["touched_at"]])[0]
        e["_bar_pos"] = pos

    groups = defaultdict(list)
    for e in events:
        groups[e["touched_at"]].append(e)

    executed = []
    pos_exit_time = None
    sal_session = None
    sal_armed_at = None

    for ts in sorted(groups.keys()):
        group = groups[ts]
        anchor = prev_completed_range(ranges, ts)
        if anchor is None:
            continue
        if not entry_allowed(ts):
            continue
        cutoff = session_cutoff(ts)
        if cutoff is None:
            continue
        sess = session_date(ts)
        if sess != sal_session:
            sal_session = sess
            sal_armed_at = None
        if sal_armed_at is not None and ts >= sal_armed_at:
            continue
        if pos_exit_time is not None and ts < pos_exit_time:
            continue
        if pos_exit_time is not None and ts == pos_exit_time:
            continue

        ordered = sorted(group, key=lambda e: (e["created_at"], e["side"]))
        chosen = ordered[0]

        sign = -1.0 if chosen["side"] == "upper" else 1.0
        cap = min(1.5 * anchor, SL_CAP)
        if chosen["fill_override"] == "closest":
            row = bars_1m.loc[ts]
            fill = float(row["high"]) if sign > 0 else float(row["low"])
        else:
            clean = touch_is_clean(bars_1m, ts, chosen["level"])
            fill = chosen["level"] if clean else float(bars_1m.loc[ts, "close"])

        pnl, ex, exit_ts = simulate_from_touch(bars_1m, ts, cutoff, fill, sign, cap)
        year = pd.Timestamp(sess).year
        executed.append({
            "level_id": chosen["level_id"], "session_date": sess, "year": year,
            "side": chosen["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": fill, "is_near_miss_entry": chosen["fill_override"] == "closest",
            "anchor": anchor, "cap": cap, "exit_reason": ex, "pnl": pnl,
        })
        pos_exit_time = exit_ts
        if pnl < -0.1 and ex != "BE":
            sal_armed_at = exit_ts

    ex_df = pd.DataFrame(executed)
    summary = {"tolerance_atr": tolerance_atr, "executed": len(ex_df)}
    if len(ex_df):
        pnl = ex_df["pnl"]
        exs = ex_df["exit_reason"].value_counts()
        summary.update({
            "net_pts": round(float(pnl.sum()), 2), "PF": round(profit_factor(pnl), 4),
            "TP": int(exs.get("TP", 0)), "SL": int(exs.get("SL", 0)),
            "BE": int(exs.get("BE", 0)), "cutoff": int(exs.get("cutoff", 0)),
            "max_drawdown": round(max_drawdown(pnl), 2),
            "near_miss_trades": int(ex_df["is_near_miss_entry"].sum()),
            "near_miss_pnl": round(float(ex_df.loc[ex_df["is_near_miss_entry"], "pnl"].sum()), 2),
        })
        yearly = {int(yr): round(float(s["pnl"].sum()), 2) for yr, s in ex_df.groupby("year")}
        summary["negative_years"] = sorted(y for y, v in yearly.items() if v < 0)
    return summary, ex_df


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
    lvls = list(levels.itertuples(index=False))
    ranges = bar_ranges(bars)

    print("Computing causal 3-minute ATR(14)...")
    atr_series, atr_index = build_causal_atr_3m(bars)

    print("Scanning every level side for touches / closest-approach distances...")
    rows = analyze(bars, lvls, atr_series, atr_index)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, "near_miss_analysis.csv"), index=False)

    touched = df["touched_at"].notna()
    untouched = df[~touched]
    with_dist = untouched.dropna(subset=["dist_in_atr"])

    print(f"\ntotal level sides: {len(df)}")
    print(f"touched: {touched.sum()}   untouched: {len(untouched)}")
    print(f"untouched with a valid ATR-scaled distance: {len(with_dist)}")
    print("\ndist_in_atr distribution (untouched levels):")
    print(with_dist["dist_in_atr"].describe())

    print("\n=== DESCRIPTIVE: near-miss frequency by tolerance ===")
    for k in ATR_TOLERANCE_MULTIPLES:
        n_within = (with_dist["dist_in_atr"] <= k).sum()
        print(f"  within {k} ATR: {n_within} untouched levels "
              f"({n_within/len(df):.1%} of all level sides, "
              f"{n_within/len(untouched):.1%} of untouched ones)")

    print("\n=== EXPERIMENTAL VARIANT: near-miss entries added, full engine re-run ===")
    baseline_summary = None
    results = {}
    for k in [None] + ATR_TOLERANCE_MULTIPLES:
        if k is None:
            summary, ex_df = run_with_near_miss_entries(bars, ranges, rows, tolerance_atr=-1)
            baseline_summary = summary
            label = "control (tolerance=-1, no near-miss entries added)"
        else:
            summary, ex_df = run_with_near_miss_entries(bars, ranges, rows, tolerance_atr=k)
            label = f"tolerance={k} ATR"
        results[label] = summary
        ex_df.to_csv(os.path.join(out_dir, f"near_miss_variant_{k}_executed.csv"), index=False)
        print(f"\n--- {label} ---")
        print(json.dumps({kk: vv for kk, vv in summary.items() if kk != "yearly"}, indent=2))

    with open(os.path.join(out_dir, "near_miss_summary.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\noutputs written to {out_dir}/")


if __name__ == "__main__":
    main()
