"""One-time setup for the OG build-four-years pipeline: loads bars/vxn,
builds levels and physical-touch events (shared across all Stage B/C/D/E
variants -- these are structural/causal artifacts, not outcome metrics), and
caches them to pickle so each stage script doesn't repeat the expensive
level-generation / touch-detection pass.

Also builds a causal 60-minute-bar return series used later for the Stage D
HMM gate (again, purely an input feature -- no strategy-outcome computation
happens here).
"""
import os
import pickle
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import NQ_PARAMS, generate_levels
from src.strict_engine import bar_ranges, physical_touches

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")


def main():
    bars = load_1m_ohlcv(os.path.join(REPO_ROOT, "data/nq_1m/nq_continuous_2018_2026_1m.csv"))
    vxn = load_gvz_daily(os.path.join(REPO_ROOT, "data/vxn_daily_2018_2026.csv"))

    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump({"bars": bars, "ranges": ranges, "events": events, "levels": levels}, f)
    print(f"cached {len(events)} touch events (levels={len(levels)}) -> {CACHE}")


if __name__ == "__main__":
    main()
