#!/usr/bin/env python3
"""Stage 1 section 9-12: the 980 preregistered simple TP/SL candidates.

S1 = previous completed 30-min range
S2 = ATR(14) on completed 60-min bars
S3 = previous completed research-session range
S4 = sqrt(S1 * S2)

S_adjusted = S * clip(RVOL_60^gamma, 0.80, 1.25), gamma in {-0.30,-0.15,0,0.15,0.30}
TP = round_up_tick(a * S_adjusted), a in {0.50,0.75,1.00,1.25,1.50,1.75,2.00}
SL = round_down_tick(b * S_adjusted), b in same set
-> 4 * 5 * 7 * 7 = 980 candidates.

Every candidate is run ONCE as a single continuous chronological one-
position replay over all qualifying 2018-2026 signals (2026 rows are
tagged but excluded from any training/selection use downstream); walk-
forward candidate selection is then a matter of slicing this same trade
ledger by year, which is valid because the replay's causal chronology
never depends on which years are later used for "training" vs "test" --
the trading rule itself (fixed a/b/gamma per candidate) does not change
across years.

Usage:
    python3 scripts/run_stage1_simple_surface.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --out-dir outputs
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from scripts.stage1_engine import round_tp, round_sl, run_replay  # noqa: E402

GAMMAS = [-0.30, -0.15, 0.00, 0.15, 0.30]
MULTS = [0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00]
CLIP_BOUNDS = (0.80, 1.25)
SCALES = ["S1_range30m", "S2_atr60m", "S3_prevsessrange", "S4_geomean"]


def build_master_table(out_dir):
    excursions = pd.read_parquet(os.path.join(out_dir, "stage1_corrected_excursions.parquet"))
    features = pd.read_csv(os.path.join(out_dir, "stage0_features.csv"))
    rvol = pd.read_parquet(os.path.join(out_dir, "stage1_session_anchored_rvol.parquet"))

    m = excursions.merge(features, on="level_id", suffixes=("", "_feat"))
    m = m.merge(rvol.drop(columns=["touched_at"]), on="level_id")

    m["S1_range30m"] = m["range_30m"]
    m["S2_atr60m"] = m["atr14_60m"]
    m["S3_prevsessrange"] = m["prev_session_range"]
    m["S4_geomean"] = np.sqrt(m["S1_range30m"].clip(lower=0) * m["S2_atr60m"].clip(lower=0))
    m["rvol60_primary"] = m["rvol_60m_hist20_session_anchored"]

    m["touched_at"] = pd.to_datetime(m["touched_at"], utc=True)
    m["forced_liquidation_ts"] = pd.to_datetime(m["forced_liquidation_ts"], utc=True)
    return m


def candidate_id(scale, gamma, a, b):
    return f"simple|scale={scale}|gamma={gamma:+.2f}|a={a:.2f}|b={b:.2f}"


def yearly_breakdown(executed):
    if executed.empty:
        return []
    out = []
    for yr, s in executed.groupby("year"):
        out.append({
            "year": int(yr), "n": len(s),
            "net_pts": round(float(s["pnl_after_cost"].sum()), 2),
            "PF": round(profit_factor(s["pnl_after_cost"]), 4),
            "avg_R": round(float(s["r_multiple"].mean()), 4),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    ap.add_argument("--cost", type=float, default=1.0)
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    bars = load_1m_ohlcv(args.bars)
    master = build_master_table(out_dir)
    master_dev = master  # all years included; 2018-2025 filtering happens downstream

    rows = []
    total = len(SCALES) * len(GAMMAS) * len(MULTS) * len(MULTS)
    done = 0
    for scale in SCALES:
        for gamma in GAMMAS:
            rvol_factor = np.clip(master_dev["rvol60_primary"].fillna(1.0) ** gamma, *CLIP_BOUNDS)
            s_adj = master_dev[scale] * rvol_factor
            for a in MULTS:
                tp_dist = round_tp(a * s_adj)
                sl_dist_base = s_adj  # recompute per b below
                for b in MULTS:
                    sl_dist = round_sl(b * s_adj)
                    touches = master_dev.assign(tp_dist_stage1=tp_dist, sl_dist_stage1=sl_dist)
                    touches = touches.dropna(subset=[scale, "tp_dist_stage1", "sl_dist_stage1"])
                    executed, skipped = run_replay(bars, touches, "tp_dist_stage1", "sl_dist_stage1", cost_pts=args.cost)

                    cid = candidate_id(scale, gamma, a, b)
                    pnl = executed["pnl_after_cost"] if len(executed) else pd.Series(dtype=float)
                    r = executed["r_multiple"] if len(executed) else pd.Series(dtype=float)
                    rows.append({
                        "candidate_id": cid, "family": "simple", "scale": scale, "gamma": gamma,
                        "a_tp_mult": a, "b_sl_mult": b,
                        "qualifying_touches": len(touches), "executed": len(executed),
                        "skipped_position_open": skipped,
                        "TP": int((executed["exit_reason"] == "TP").sum()) if len(executed) else 0,
                        "SL": int((executed["exit_reason"] == "SL").sum()) if len(executed) else 0,
                        "cutoff": int((executed["exit_reason"] == "cutoff").sum()) if len(executed) else 0,
                        "win_rate": float((pnl > 0).mean()) if len(pnl) else None,
                        "net_pts": round(float(pnl.sum()), 2) if len(pnl) else 0.0,
                        "avg_pnl": round(float(pnl.mean()), 4) if len(pnl) else None,
                        "median_pnl": round(float(pnl.median()), 4) if len(pnl) else None,
                        "avg_R": round(float(r.mean()), 4) if len(r) else None,
                        "median_R": round(float(r.median()), 4) if len(r) else None,
                        "PF_pts": round(profit_factor(pnl), 4) if len(pnl) else None,
                        "PF_R": round(profit_factor(r), 4) if len(r) else None,
                        "max_dd_pts": round(max_drawdown(pnl), 2) if len(pnl) else None,
                        "max_dd_R": round(max_drawdown(r), 4) if len(r) else None,
                        "yearly_json": json.dumps(yearly_breakdown(executed)),
                    })
                    done += 1
        print(f"scale {scale} done ({done}/{total})", file=sys.stderr)

    cand_df = pd.DataFrame(rows).sort_values("candidate_id").reset_index(drop=True)
    out_path = os.path.join(out_dir, "stage1_simple_all_candidates.csv")
    cand_df.to_csv(out_path, index=False)

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

    summary = {
        "research_commit": git_sha(),
        "n_candidates": len(cand_df),
        "expected_n_candidates": 980,
        "cost_pts": args.cost,
        "output_sha256": sha256_file(out_path),
        "reproduction_command": (
            f"python3 scripts/run_stage1_simple_surface.py --bars {args.bars} --out-dir {args.out_dir} --cost {args.cost}"
        ),
    }
    with open(os.path.join(out_dir, "stage1_simple_surface_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
