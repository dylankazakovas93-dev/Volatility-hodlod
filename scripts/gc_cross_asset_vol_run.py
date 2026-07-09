"""GC (gold futures) run of the same frozen engine internals used everywhere
else in this repo (generate_levels / physical_touches / run_strict --
src/strict_engine.py, zero logic changes), using GC_PARAMS
(sigma_mult=1.15, offset_pct=0.02, ib_minutes=30 -- percent-of-sigma offset,
not NQ's fixed-points offset) instead of NQ_PARAMS, against each of the 5
vol-index feeds from the earlier NQ cross-asset experiment.

No NQ-specific sanity gate applies here (the 1,841-candidate gate and
build_eligible_candidates() both hardcode NQ_PARAMS) -- skipped entirely,
this is a different instrument. SL_CAP (200.0 pts, from strict_engine.py) is
inherited unchanged from the NQ config per this repo's "canonical_unchanged"
convention; on GC's price scale it rarely binds (GC's 1h ranges are a few
points wide vs SL_CAP=200), so in practice it's close to a no-op here --
flagged, not modified.

Bars loaded once, reused across all 5 vol-index runs.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import GC_PARAMS, generate_levels
from src.strict_engine import bar_ranges, physical_touches, run_strict
import pandas as pd

BARS_PATH = "data/gc_1m/gc_continuous_2023_2026_1m.csv"
VOL_FILES = {
    "VXN": "data/vxn_daily_2018_2026.csv",
    "VIX": "data/cross_asset_vol/vix_daily_2018_2026.csv",
    "GVZ": "data/cross_asset_vol/gvz_daily_2018_2026.csv",
    "OVX": "data/cross_asset_vol/ovx_daily_2018_2026.csv",
    "RVX": "data/cross_asset_vol/rvx_daily_2018_2026.csv",
}

OUT_DIR = "outputs/gc_cross_asset_vol"
os.makedirs(OUT_DIR, exist_ok=True)


def main():
    t0 = time.time()
    bars = load_1m_ohlcv(BARS_PATH)
    ranges = bar_ranges(bars)
    print(f"GC bars loaded: {len(bars)} rows, {time.time() - t0:.1f}s")

    for vol_name, vol_path in VOL_FILES.items():
        t1 = time.time()
        vol_series = load_gvz_daily(vol_path)
        levels = generate_levels(bars, vol_series, params=GC_PARAMS)
        lvls = list(levels.itertuples(index=False))
        events = physical_touches(bars, lvls)
        summary, executed, skipped = run_strict(bars, ranges, events)

        out_dir = os.path.join(OUT_DIR, vol_name.lower())
        os.makedirs(out_dir, exist_ok=True)
        executed.to_csv(os.path.join(out_dir, "executed.csv"), index=False)
        skipped.to_csv(os.path.join(out_dir, "skipped.csv"), index=False)
        pd.DataFrame(summary["yearly"]).to_csv(os.path.join(out_dir, "yearly.csv"), index=False)
        with open(os.path.join(out_dir, "summary.json"), "w") as f:
            json.dump({"vol": vol_name, "n_levels": len(lvls), "result": summary}, f, indent=2, default=str)

        r = summary
        print(
            f"[{vol_name}] n_levels={len(lvls):<5} executed={r['executed']:<5} "
            f"net_pts={r['net_pts']:>9.2f} PF={r['PF']:.4f} win={r['win_rate']*100:5.2f}% "
            f"dd={r['max_drawdown']:>9.2f} ({time.time() - t1:.1f}s)"
        )

    print(f"\ntotal time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
