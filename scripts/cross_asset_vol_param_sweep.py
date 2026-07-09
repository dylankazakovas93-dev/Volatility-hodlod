"""Slim, non-exhaustive sensitivity sweep over level-generation params
(sigma_mult, fixed_offset) for each of the 5 daily vol-index feeds (VXN plus
the 4 cross-asset substitutes from the earlier experiment). Not a grid
search / optimization run: a small, pre-fixed 3x3 grid per vol measure (9
combos x 5 measures = 45 runs), meant only to check whether the earlier
single-shot VXN-tuned-params result for VIX/GVZ/OVX/RVX was an artifact of
using VXN's own sigma_mult=1.25/fixed_offset=15.75, or whether it holds up
across a broad-but-shallow neighborhood of those two params. No other
mechanic (ib_minutes, RR, BE, SAL, entry window) is touched -- same frozen
run_strict()/physical_touches() as everywhere else in this repo.

Bars are loaded once and reused across all 45 runs (the per-run cost in the
CLI is dominated by re-parsing the 205MB bars file and re-hashing it; both
are skipped here since content doesn't change between runs).
"""
import json
import os
import sys
import time
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import NQ_PARAMS, generate_levels
from src.strict_engine import bar_ranges, physical_touches, run_strict

BARS_PATH = "data/nq_1m/nq_continuous_2018_2026_1m.csv"
VOL_FILES = {
    "VXN": "data/vxn_daily_2018_2026.csv",
    "VIX": "data/cross_asset_vol/vix_daily_2018_2026.csv",
    "GVZ": "data/cross_asset_vol/gvz_daily_2018_2026.csv",
    "OVX": "data/cross_asset_vol/ovx_daily_2018_2026.csv",
    "RVX": "data/cross_asset_vol/rvx_daily_2018_2026.csv",
}

SIGMA_MULTS = [0.5, 1.25, 2.0]      # baseline = 1.25
FIXED_OFFSETS = [0.0, 15.75, 30.0]  # baseline = 15.75

OUT_DIR = "outputs/cross_asset_vol_param_sweep"
os.makedirs(OUT_DIR, exist_ok=True)


def run_one(bars, ranges, vol_series, sigma_mult, fixed_offset):
    params = replace(NQ_PARAMS, sigma_mult=sigma_mult, fixed_offset=fixed_offset)
    levels = generate_levels(bars, vol_series, params=params)
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)
    summary, executed, skipped = run_strict(bars, ranges, events)
    return {
        "n_levels": len(lvls),
        "executed": summary["executed"],
        "net_pts": summary["net_pts"],
        "PF": summary["PF"],
        "win_rate": summary["win_rate"],
        "max_drawdown": summary["max_drawdown"],
    }


def main():
    t0 = time.time()
    print("loading bars (once)...")
    bars = load_1m_ohlcv(BARS_PATH)
    ranges = bar_ranges(bars)
    print(f"  bars loaded in {time.time() - t0:.1f}s")

    all_rows = []
    for vol_name, vol_path in VOL_FILES.items():
        vol_series = load_gvz_daily(vol_path)
        for sm in SIGMA_MULTS:
            for fo in FIXED_OFFSETS:
                t1 = time.time()
                r = run_one(bars, ranges, vol_series, sm, fo)
                dt = time.time() - t1
                row = {"vol": vol_name, "sigma_mult": sm, "fixed_offset": fo, **r, "seconds": round(dt, 2)}
                all_rows.append(row)
                is_baseline = " <- baseline" if (sm == 1.25 and fo == 15.75) else ""
                print(
                    f"[{vol_name}] sigma_mult={sm:<5} fixed_offset={fo:<6} "
                    f"n={r['executed']:<5} net={r['net_pts']:>9.2f} PF={r['PF']:.4f} "
                    f"dd={r['max_drawdown']:>9.2f} ({dt:.1f}s){is_baseline}"
                )

    with open(os.path.join(OUT_DIR, "sweep_results.json"), "w") as f:
        json.dump(all_rows, f, indent=2, default=str)

    print(f"\ntotal time: {time.time() - t0:.1f}s")
    print(f"wrote {len(all_rows)} rows to {OUT_DIR}/sweep_results.json")


if __name__ == "__main__":
    main()
