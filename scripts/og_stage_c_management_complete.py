"""Stage C completion: confirm/reselect BE via a proper bar-count-family
neighborhood test (per docs/OG_STAGE_C_MANAGEMENT.md provisional be_bars=60
flag). Holds constant: SAL off, CANONICAL 11:00-15:00 blocked window, target
fixed at 1.0R, no HMM. Family under test: no-BE, BE30/45/60/75/90 plus a
labeled diagnostic-only BE45+2pt-lock reference (NOT eligible for selection).

Outputs:
  outputs/og_build_years/stage_c_management_complete.csv
  docs/OG_STAGE_C_MANAGEMENT_COMPLETE.md (written separately)
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.og_build_variant_engine import filter_build_years, OG_BUILD_YEARS
from src.og_management_variants import run_variant_managed
from src.metrics import profit_factor, max_drawdown

CACHE = os.path.join(REPO_ROOT, "outputs", "og_build_years", "_cache.pkl")
OUT = os.path.join(REPO_ROOT, "outputs", "og_build_years")
CANONICAL_WINDOW = (11 * 60, 15 * 60)

CANDIDATES = {
    "noBE":            dict(mode="none"),
    "BE30":            dict(mode="barcount", be_bars=30),
    "BE45":            dict(mode="barcount", be_bars=45),
    "BE60":            dict(mode="barcount", be_bars=60),
    "BE75":            dict(mode="barcount", be_bars=75),
    "BE90":            dict(mode="barcount", be_bars=90),
}


def _lock2pt_managed(bars, touched_at, cutoff, entry_fill, sign, cap):
    """BE45 + lock 2 points once armed (diagnostic reference only): identical
    timing mechanism to barcount BE45 (arm-check via bar open at i==45) but
    the armed stop locks in 2 points of profit instead of exact breakeven."""
    touch_row = bars.loc[touched_at]
    orig_stop = entry_fill - sign * cap
    h0, l0 = float(touch_row["high"]), float(touch_row["low"])
    hit_stop = (l0 <= orig_stop) if sign > 0 else (h0 >= orig_stop)
    if hit_stop:
        return sign * (orig_stop - entry_fill), "SL", touched_at
    rest = bars.loc[touched_at: cutoff].iloc[1:]
    if rest.empty:
        return sign * (float(touch_row["close"]) - entry_fill), "cutoff", touched_at
    target = entry_fill + sign * cap
    hi, lo, op, cl = (rest["high"].values, rest["low"].values, rest["open"].values, rest["close"].values)
    idx = rest.index
    n = len(hi)
    be_bars = 45
    armed = checked = False
    for i in range(n):
        h, l = float(hi[i]), float(lo[i])
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry_fill) if sign > 0 else (o <= entry_fill)
            stop = entry_fill + sign * 2.0 if armed else orig_stop
        if sign > 0:
            if l <= stop:
                return sign * (stop - entry_fill), ("LOCK" if (i >= be_bars and armed) else "SL"), idx[i]
            if h >= target:
                return cap, "TP", idx[i]
        else:
            if h >= stop:
                return sign * (stop - entry_fill), ("LOCK" if (i >= be_bars and armed) else "SL"), idx[i]
            if l <= target:
                return cap, "TP", idx[i]
    return sign * (float(cl[-1]) - entry_fill), "cutoff", (idx[-1] if n else touched_at)


def run_diagnostic_lock2pt(bars, ranges, events):
    import src.og_management_variants as omv
    orig = omv.simulate_managed

    def patched(bars_, touched_at, cutoff, entry_fill, sign, cap, **kw):
        return _lock2pt_managed(bars_, touched_at, cutoff, entry_fill, sign, cap)

    omv.simulate_managed = patched
    try:
        summary, ex_df = run_variant_managed(
            bars, ranges, events, mgmt_kwargs={}, sal_enabled=False,
            blocked_window=CANONICAL_WINDOW, hmm_gate=None)
    finally:
        omv.simulate_managed = orig
    return summary, ex_df


def hold_time_minutes(sub):
    dt = (pd.to_datetime(sub["exit_time"]) - pd.to_datetime(sub["entry_time"])).dt.total_seconds() / 60.0
    return dt


def compute_full_metrics(label, by):
    if by is None or len(by) == 0:
        return None
    by = by.copy()
    by["cap_norm_pnl"] = by["pnl"] / by["cap"]
    by["hold_min"] = hold_time_minutes(by)

    def yr_row(sub, yr_label, n_years=1):
        n = len(sub)
        pnl = sub["pnl"]
        capr = sub["cap_norm_pnl"]
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        avg_w = float(wins.mean()) if len(wins) else 0.0
        avg_l = float(losses.mean()) if len(losses) else 0.0
        payoff = (avg_w / abs(avg_l)) if avg_l not in (0, None) and avg_l != 0 else None
        exit_counts = sub["exit_reason"].value_counts().to_dict()
        hm = sub["hold_min"]
        return {
            "candidate": label, "year": yr_label, "n_trades": n,
            "net_pts": round(float(pnl.sum()), 2),
            "PF_pts": round(profit_factor(pnl), 4),
            "avg_pts_per_trade": round(float(pnl.mean()), 3) if n else 0.0,
            "cap_norm_R_total": round(float(capr.sum()), 4),
            "cap_norm_R_avg": round(float(capr.mean()), 4) if n else 0.0,
            "max_dd_pts": round(max_drawdown(pnl), 2) if n else 0.0,
            "max_dd_R": round(max_drawdown(capr), 4) if n else 0.0,
            "win_rate": round(float((pnl > 0).mean()), 4) if n else 0.0,
            "avg_winner_pts": round(avg_w, 3),
            "avg_loser_pts": round(avg_l, 3),
            "payoff_ratio": round(payoff, 3) if payoff is not None else None,
            "n_TP": int(exit_counts.get("TP", 0)),
            "n_SL": int(exit_counts.get("SL", 0)),
            "n_BE": int(exit_counts.get("BE", 0) + exit_counts.get("LOCK", 0) + exit_counts.get("SCRATCH", 0)),
            "n_cutoff": int(exit_counts.get("cutoff", 0)),
            "trades_per_year": round(n / n_years, 2),
            "hold_median_min": round(float(hm.median()), 1) if n else None,
            "hold_mean_min": round(float(hm.mean()), 1) if n else None,
            "hold_p25_min": round(float(hm.quantile(.25)), 1) if n else None,
            "hold_p75_min": round(float(hm.quantile(.75)), 1) if n else None,
        }

    rows = []
    for yr in sorted(by["year"].unique()):
        sub = by[by["year"] == yr]
        rows.append(yr_row(sub, int(yr)))
    rows.append(yr_row(by, "ALL", n_years=4))
    ex2026 = by[by["year"] != 2026]
    if len(ex2026):
        rows.append(yr_row(ex2026, "ALL_ex2026", n_years=3))
    yearly_net = by.groupby("year")["pnl"].sum()
    if len(yearly_net) > 1:
        best_year = yearly_net.idxmax()
        ex_best = by[by["year"] != best_year]
        rows.append(yr_row(ex_best, f"ALL_ex_best_year({int(best_year)})", n_years=len(yearly_net) - 1))
    return rows


def main():
    with open(CACHE, "rb") as f:
        c = pickle.load(f)
    bars, ranges, events = c["bars"], c["ranges"], c["events"]

    all_rows = []
    raw = {}

    for label, mgmt_kwargs in CANDIDATES.items():
        summary, ex_df = run_variant_managed(
            bars, ranges, events, mgmt_kwargs=mgmt_kwargs, sal_enabled=False,
            blocked_window=CANONICAL_WINDOW, hmm_gate=None)
        by = filter_build_years(ex_df)
        by.to_csv(os.path.join(OUT, f"stage_c_complete_{label}_build_years_trades.csv"), index=False)
        rows = compute_full_metrics(label, by)
        if rows:
            all_rows.extend(rows)
        raw[label] = {"mgmt_kwargs": mgmt_kwargs, "summary": summary, "n": int(len(by))}
        print(label, "n=", len(by), "net=", round(float(by["pnl"].sum()), 2) if len(by) else 0)

    summary, ex_df = run_diagnostic_lock2pt(bars, ranges, events)
    by = filter_build_years(ex_df)
    label = "BE45_lock2pt_DIAGNOSTIC_ONLY"
    by.to_csv(os.path.join(OUT, "stage_c_diagnostic_BE45_lock2pt_build_years_trades.csv"), index=False)
    rows = compute_full_metrics(label, by)
    if rows:
        all_rows.extend(rows)
    raw[label] = {"mgmt_kwargs": "diagnostic_only_not_eligible", "summary": summary, "n": int(len(by))}
    print(label, "n=", len(by), "net=", round(float(by["pnl"].sum()), 2) if len(by) else 0)

    df = pd.DataFrame(all_rows)
    df.to_csv(os.path.join(OUT, "stage_c_management_complete.csv"), index=False)
    with open(os.path.join(OUT, "stage_c_management_complete_raw.json"), "w") as f:
        json.dump(raw, f, indent=2, default=str)
    print("\nWrote outputs/og_build_years/stage_c_management_complete.csv")


if __name__ == "__main__":
    main()
