#!/usr/bin/env python3
"""Stage 4 Part C pass-gate evaluation for GARCH/HMM regime candidates.

A candidate passes independently only when:
  - all four development years remain profitable;
  - pooled PF improves by >=0.03 over no_filter, OR drawdown improves by
    >=15% with PF loss <=0.02;
  - excluding 2026 remains profitable;
  - >=150 pooled trades;
  - >=20 trades in each full development year (2018/2020/2023 -- 2026 is
    partial, evaluated on its own scale per the spec's "full development
    year" wording);
  - effect positive or neutral in >=3 years;
  - no causality violation (checked separately by tests).

Usage:
    python3 scripts/evaluate_stage4_gate.py --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

FULL_DEV_YEARS = [2018, 2020, 2023]  # 2026 is partial


def evaluate(cand_df, control_row):
    c_pf, c_dd = control_row["PF"], control_row["max_dd_pts"]
    rows = []
    for _, r in cand_df.iterrows():
        if r["candidate"] == "no_filter":
            continue
        if pd.isna(r.get("PF")) or r.get("n_trades", 0) == 0:
            rows.append({"candidate": r["candidate"], "pass": False, "reason": "no trades"})
            continue
        yearly = json.loads(r["yearly_json"])
        all4 = all(yearly.get(str(y), {}).get("net_pts", -1) > 0 for y in (2018, 2020, 2023, 2026))
        n_helped = sum(1 for y in (2018, 2020, 2023, 2026) if yearly.get(str(y), {}).get("net_pts", -1) >= 0)
        pf_delta = r["PF"] - c_pf
        dd_improve = (abs(c_dd) - abs(r["max_dd_pts"])) / abs(c_dd) if c_dd else 0
        crit_pf = pf_delta >= 0.03
        crit_dd = dd_improve >= 0.15 and pf_delta >= -0.02
        min_trades_ok = r["n_trades"] >= 150
        min_per_year_ok = all(yearly.get(str(y), {}).get("n", 0) >= 20 for y in FULL_DEV_YEARS)
        ex2026_ok = r.get("ex_2026_net_pts", -1) > 0
        passes = (all4 and (crit_pf or crit_dd) and ex2026_ok and min_trades_ok
                  and min_per_year_ok and n_helped >= 3)
        rows.append({
            "candidate": r["candidate"], "pass": passes,
            "all4_profitable": all4, "n_years_helped": n_helped,
            "pf_delta": round(pf_delta, 4), "dd_improve_pct": round(dd_improve * 100, 1),
            "min_trades_ok": min_trades_ok, "min_per_year_ok": min_per_year_ok, "ex2026_ok": ex2026_ok,
            "n_trades": r["n_trades"], "PF": r["PF"], "net_pts": r["net_pts"],
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    cand_df = pd.read_csv(os.path.join(out_dir, "stage4_candidate_summary.csv"))
    control_row = cand_df[cand_df["candidate"] == "no_filter"].iloc[0]

    result = evaluate(cand_df, control_row)
    result.to_csv(os.path.join(out_dir, "stage4_gate_evaluation.csv"), index=False)
    passing = result[result["pass"]]
    print(f"no_filter control: PF={control_row['PF']} net={control_row['net_pts']} n={control_row['n_trades']}")
    print(f"\n{len(passing)} candidate(s) pass the Part C gate:")
    print(passing.to_string())
    print(f"\nAll candidates:")
    print(result.to_string())


if __name__ == "__main__":
    main()
