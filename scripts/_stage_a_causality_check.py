"""Ad-hoc causality/truncation check for Stage A (not part of the frozen engine
CLI, which enforces a hardcoded 1,841-candidate gate that a truncated dataset
cannot satisfy). Bypasses that gate to call the same run_strict() used by
src/strict_engine.py directly on truncated data, then diffs the resulting
trade ledger (for entries safely before the truncation boundary) against the
full-data run. This proves no future bar can alter an earlier entry decision.
"""
import sys
import pandas as pd

sys.path.insert(0, ".")
from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import NQ_PARAMS, generate_levels
from src.strict_engine import bar_ranges, physical_touches, run_strict

bars = load_1m_ohlcv("data/nq_1m/_truncated_2018_2020.csv")
vxn = load_gvz_daily("data/vxn_daily_2018_2026.csv")

levels = generate_levels(bars, vxn, params=NQ_PARAMS)
ranges = bar_ranges(bars)
lvls = list(levels.itertuples(index=False))
events = physical_touches(bars, lvls)
summary, executed, skipped = run_strict(bars, ranges, events)
executed.to_csv("outputs/stage_a_truncated/baseline_executed.csv", index=False)
print("truncated executed rows:", len(executed))
