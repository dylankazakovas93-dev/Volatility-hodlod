"""Grid search over GC (gold futures) level-generation parameters, graded by
raw MAE/MFE excursion quality rather than net PF -- a level-generation
question ("does this parameterization put price on the favorable side of
the level more than the adverse side"), decoupled from the strategy's
position-management/exit system (SAL, single-position, simultaneous-touch
collisions). This intentionally does NOT modify src/level_generation.py or
src/strict_engine.py -- it only calls their unmodified functions
(generate_levels, physical_touches, bar_ranges, prev_completed_range,
session_cutoff) with different InstrumentParams.

EXCURSION DEFINITION (declared, not mixed with other definitions -- see
docs/gc_mae_mfe_study/LABEL_DEFINITION.md for the full contract): for every
PHYSICAL TOUCH (not just executed trades -- position-management skips like
SAL/simultaneous-collision/position-open are about capital allocation, not
about whether the level itself was a good price, so they're excluded here
by design), measure MAE/MFE points from the touch bar (inclusive) through
session_cutoff(touched_at) inclusive -- the same fixed, pre-declared,
non-adaptive 15:00 ET (or next-session 15:00 ET) prop-firm flat time
already used everywhere else in this repo. This is Definition C
(pre-declared-event excursion) in the label contract: the horizon is fixed
in advance by clock time, not by price action, so it introduces no
lookahead beyond "the trade would have been flattened by the prop-firm
deadline" -- a fact already known at entry.

R-normalization uses cap = min(1.5*anchor, SL_CAP), the stop distance
already knowable at entry (identical formula used by the frozen engine).
"""
from __future__ import annotations

import itertools
import json
import os
import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import GC_PARAMS, generate_levels
from src.strict_engine import bar_ranges, physical_touches, prev_completed_range, session_cutoff, SL_CAP

BARS_PATH = "data/gc_1m/gc_continuous_2023_2026_1m.csv"
VOL_PATH = "data/vxn_daily_2018_2026.csv"  # VXN was the best-performing vol feed for GC in the prior cross-asset study

SIGMA_MULTS = [0.5, 0.75, 1.0, 1.15, 1.35, 1.5, 1.75, 2.0]   # baseline = 1.15
OFFSET_PCTS = [0.0, 0.01, 0.02, 0.03, 0.05, 0.08]             # baseline = 0.02
IB_MINUTES = [15, 30, 45]                                      # baseline = 30

OUT_DIR = "outputs/gc_level_gen_grid"
os.makedirs(OUT_DIR, exist_ok=True)


def excursion_for_combo(bars, ranges, vol_series, sigma_mult, offset_pct, ib_minutes):
    params = replace(GC_PARAMS, sigma_mult=sigma_mult, offset_pct=offset_pct, ib_minutes=ib_minutes,
                      fixed_offset=None)  # GC uses percent-of-sigma offset, not NQ's fixed points
    levels = generate_levels(bars, vol_series, params=params, rth_start="09:30", rth_end="16:00")
    lvls = list(levels.itertuples(index=False))
    if not lvls:
        return None

    events = physical_touches(bars, lvls)
    touched = [e for e in events if e["touched_at"] is not None]

    rows = []
    for e in touched:
        ts = e["touched_at"]
        anchor = prev_completed_range(ranges, ts)
        if anchor is None:
            continue
        cutoff = session_cutoff(ts)
        if cutoff is None:
            continue
        cap = min(1.5 * anchor, SL_CAP)
        if cap <= 0:
            continue
        path = bars.loc[ts:cutoff]
        if path.empty:
            continue
        entry = e["level"]
        sign = -1.0 if e["side"] == "upper" else 1.0
        path_high = float(path["high"].max())
        path_low = float(path["low"].min())
        if sign > 0:  # long (lower-level touch)
            mfe_pts = max(0.0, path_high - entry)
            mae_pts = max(0.0, entry - path_low)
        else:  # short (upper-level touch)
            mfe_pts = max(0.0, entry - path_low)
            mae_pts = max(0.0, path_high - entry)
        rows.append({"mae_pts": mae_pts, "mfe_pts": mfe_pts, "mae_R": mae_pts / cap, "mfe_R": mfe_pts / cap})

    if not rows:
        return None
    df = pd.DataFrame(rows)
    return {
        "n_touches": len(df),
        "n_levels": len(lvls),
        "median_mae_R": float(df["mae_R"].median()),
        "median_mfe_R": float(df["mfe_R"].median()),
        "p75_mae_R": float(df["mae_R"].quantile(0.75)),
        "p75_mfe_R": float(df["mfe_R"].quantile(0.75)),
        "mean_mae_R": float(df["mae_R"].mean()),
        "mean_mfe_R": float(df["mfe_R"].mean()),
        "excursion_asymmetry_median": float(df["mfe_R"].median() - df["mae_R"].median()),
        "excursion_asymmetry_mean": float(df["mfe_R"].mean() - df["mae_R"].mean()),
        "frac_mfe_gt_mae": float((df["mfe_R"] > df["mae_R"]).mean()),
    }


def main():
    t0 = time.time()
    bars = load_1m_ohlcv(BARS_PATH)
    ranges = bar_ranges(bars)
    vol_series = load_gvz_daily(VOL_PATH)
    print(f"bars loaded: {len(bars)} rows, {time.time() - t0:.1f}s")

    combos = list(itertools.product(SIGMA_MULTS, OFFSET_PCTS, IB_MINUTES))
    print(f"grid size: {len(combos)} combos "
          f"({len(SIGMA_MULTS)} sigma_mult x {len(OFFSET_PCTS)} offset_pct x {len(IB_MINUTES)} ib_minutes)")

    results = []
    for i, (sm, op, ibm) in enumerate(combos):
        t1 = time.time()
        r = excursion_for_combo(bars, ranges, vol_series, sm, op, ibm)
        dt = time.time() - t1
        if r is None:
            print(f"[{i+1}/{len(combos)}] sigma={sm} offset={op} ib={ibm}: no touches ({dt:.1f}s)")
            continue
        row = {"sigma_mult": sm, "offset_pct": op, "ib_minutes": ibm, **r, "seconds": round(dt, 2)}
        results.append(row)
        if (i + 1) % 12 == 0 or i == 0:
            print(f"[{i+1}/{len(combos)}] sigma={sm} offset={op} ib={ibm} "
                  f"n={r['n_touches']} asym_med={r['excursion_asymmetry_median']:.4f} ({dt:.1f}s)")

    df = pd.DataFrame(results).sort_values("excursion_asymmetry_median", ascending=False).reset_index(drop=True)
    df.to_csv(os.path.join(OUT_DIR, "grid_results.csv"), index=False)

    print(f"\ntotal time: {time.time() - t0:.1f}s, {len(df)} combos with touches")
    print("\n=== TOP 10 by median MFE_R - MAE_R (excursion towards our side) ===")
    print(df.head(10).to_string(index=False))
    print("\n=== BOTTOM 5 ===")
    print(df.tail(5).to_string(index=False))

    baseline = df[(df["sigma_mult"] == 1.15) & (df["offset_pct"] == 0.02) & (df["ib_minutes"] == 30)]
    if len(baseline):
        print("\n=== BASELINE (sigma=1.15, offset=0.02, ib=30) ===")
        print(baseline.to_string(index=False))


if __name__ == "__main__":
    main()
