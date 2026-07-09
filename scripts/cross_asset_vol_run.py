"""Ad-hoc driver for the cross-asset-volatility experiment: run the frozen,
unmodified engine internals (src/strict_engine.py's run_strict, generate_levels,
etc. -- no logic touched) with a substitute daily vol-index CSV in place of
VXN. Not part of the frozen CLI, which enforces a hardcoded 1,841-candidate
gate that only the VXN-derived level set satisfies by construction; any
other index shifts sigma_day and therefore which sessions/touches are
eligible, so that gate can't apply here. This script reports the eligible
count instead of gating on it -- everything else is identical to
src/strict_engine.py::main().
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_1m_ohlcv, load_gvz_daily
from src.level_generation import NQ_PARAMS, generate_levels
from src.strict_engine import build_eligible_candidates, bar_ranges, physical_touches, run_strict, git_sha, sha256_file
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vol", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    vol = load_gvz_daily(args.vol)

    eligible = build_eligible_candidates(bars, vol)
    print(f"raw eligible candidates: {len(eligible)}  (VXN baseline: 1841, informational only -- not gated)")
    eligible.to_csv(os.path.join(args.out_dir, "eligible.csv"), index=False)

    levels = generate_levels(bars, vol, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    events = physical_touches(bars, lvls)
    pd.DataFrame(events).to_csv(os.path.join(args.out_dir, "physical_touches.csv"), index=False)

    summary, executed, skipped = run_strict(bars, ranges, events)
    print(json.dumps({k: v for k, v in summary.items() if k != "yearly"}, indent=2))

    executed.to_csv(os.path.join(args.out_dir, "executed.csv"), index=False)
    skipped.to_csv(os.path.join(args.out_dir, "skipped.csv"), index=False)
    pd.DataFrame(summary["yearly"]).to_csv(os.path.join(args.out_dir, "yearly.csv"), index=False)

    manifest = {
        "code_commit": git_sha(),
        "data_hashes": {"bars": sha256_file(args.bars), "vol": sha256_file(args.vol)},
        "eligible_count": len(eligible),
        "result": summary,
    }
    with open(os.path.join(args.out_dir, "summary.json"), "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    print(f"\noutputs written to {args.out_dir}/")


if __name__ == "__main__":
    main()
