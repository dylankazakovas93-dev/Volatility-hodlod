#!/usr/bin/env python3
"""Percentage-based trailing stop grid sweep after TP engagement.

Two parameters, both scaled to cap:
  trail_frac: trailing distance as fraction of cap (0.1 = tight, 1.0 = loose)
              At engagement (1*cap), initial locked profit = (1 - trail_frac) * cap.
              As price extends, stop ratchets up behind best price by trail_frac*cap.
              Example: trail_frac=1.0, price at 3*cap → stop at 2*cap (pink's "300%→200%")
  hard_exit:  hard target as multiple of cap (e.g., 3.0 = close at 3*cap profit).
              None = no hard target, trail only until stopped or cutoff.

Grid: 10 trail_frac values × 11 hard_exit values = 110 configs.
Pre-engagement: identical to locked cond@45 (SL, BE@45, SAL unchanged).

Usage:
    python3 scripts/nq_trail_pct_grid.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B

BE_BARS = 45
OOS_YEARS = {2018, 2019, 2020, 2022}


def build_trades(bars, vxn):
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = B.bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    trades = []
    for i, lv in enumerate(lvls):
        expiry = lvls[i + B.LINE_DAYS].created_at if i + B.LINE_DAYS < len(lvls) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col)
            ft = _first_touch(search, lvl)
            if ft is None or not B.entry_allowed(ft):
                continue
            anchor = B.prev_completed_range(ranges, ft)
            if anchor is None:
                continue
            co = B.session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue
            cap = min(1.5 * anchor, B.SL_CAP)
            sg = -1.0 if side == "upper" else 1.0
            trades.append({
                "sd": B.session_date(ft), "yr": pd.Timestamp(B.session_date(ft)).year, "ta": ft,
                "e": lvl, "sg": sg, "cap": cap,
                "hi": path["high"].values.astype(float), "lo": path["low"].values.astype(float),
                "op": path["open"].values.astype(float), "cl": path["close"].values.astype(float),
            })
    return trades


def sim_trail(t, trail_frac, hard_exit, be_bars=BE_BARS):
    e, sg, c = t["e"], t["sg"], t["cap"]
    tgt = e + sg * c
    orig = e - sg * c
    trail_d = trail_frac * c
    hard = e + sg * hard_exit * c if hard_exit else None
    hi, lo, op, cl = t["hi"], t["lo"], t["op"], t["cl"]
    armed = chk = engaged = False
    best = 0.0
    for i in range(len(hi)):
        h, l = hi[i], lo[i]
        if not engaged:
            if i < be_bars:
                stp = orig
            else:
                if not chk:
                    chk = True
                    armed = (op[i] >= e) if sg > 0 else (op[i] <= e)
                stp = e if armed else orig
            if sg > 0:
                if l <= stp:
                    return sg * (stp - e), ("BE" if (i >= be_bars and armed) else "SL")
                if h >= tgt:
                    engaged = True
                    best = h
                    if hard and best >= hard:
                        return hard_exit * c, "HX"
                    continue
            else:
                if h >= stp:
                    return sg * (stp - e), ("BE" if (i >= be_bars and armed) else "SL")
                if l <= tgt:
                    engaged = True
                    best = l
                    if hard and best <= hard:
                        return hard_exit * c, "HX"
                    continue
        else:
            if sg > 0:
                if h > best:
                    best = h
                if hard and best >= hard:
                    return hard_exit * c, "HX"
                ts = best - trail_d
                if l <= ts:
                    return ts - e, "TR"
            else:
                if l < best:
                    best = l
                if hard and best <= hard:
                    return hard_exit * c, "HX"
                ts = best + trail_d
                if h >= ts:
                    return e - ts, "TR"
    return sg * (cl[-1] - e), ("cutoff_eng" if engaged else "cutoff")


def sim_baseline(t, be_bars=BE_BARS):
    e, sg, c = t["e"], t["sg"], t["cap"]
    tgt, orig = e + sg * c, e - sg * c
    hi, lo, op, cl = t["hi"], t["lo"], t["op"], t["cl"]
    armed = chk = False
    for i in range(len(hi)):
        h, l = hi[i], lo[i]
        if i < be_bars:
            stp = orig
        else:
            if not chk:
                chk = True
                armed = (op[i] >= e) if sg > 0 else (op[i] <= e)
            stp = e if armed else orig
        if sg > 0:
            if l <= stp:
                return sg * (stp - e), ("BE" if (i >= be_bars and armed) else "SL")
            if h >= tgt:
                return c, "TP"
        else:
            if h >= stp:
                return sg * (stp - e), ("BE" if (i >= be_bars and armed) else "SL")
            if l <= tgt:
                return c, "TP"
    return sg * (cl[-1] - e), "cutoff"


def run_sal(trades, results):
    rows = [{"sd": t["sd"], "yr": t["yr"], "ta": t["ta"], "p": r[0], "ex": r[1]}
            for t, r in zip(trades, results)]
    df = pd.DataFrame(rows).sort_values("ta")
    kept = []
    for _, day in df.groupby("sd"):
        lost = False
        for _, r in day.iterrows():
            if not lost:
                kept.append(r.to_dict())
                if r["p"] < -0.1 and r["ex"] != "BE":
                    lost = True
    return pd.DataFrame(kept).sort_values("ta").reset_index(drop=True)


def pf(s):
    g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def maxdd(s):
    e = s.cumsum()
    return float((e - e.cummax()).min())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    trades = build_trades(bars, vxn)
    print(f"raw trades: {len(trades)}")

    # Baseline
    base_res = [sim_baseline(t) for t in trades]
    base = run_sal(trades, base_res)
    base_net = base["p"].sum()
    base_pf = pf(base["p"])
    base_dd = maxdd(base["p"])
    base_by_yr = {yr: float(base[base["yr"] == yr]["p"].sum()) for yr in sorted(base["yr"].unique())}
    years = sorted(base["yr"].unique())
    print(f"BASELINE: n={len(base)} net={base_net:.0f} PF={base_pf:.3f} maxDD={base_dd:.0f}\n")

    # Grid
    trail_fracs = np.round(np.arange(0.1, 1.05, 0.1), 2)
    hard_exits = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 5.0, None]
    print(f"sweeping {len(trail_fracs)} trail_fracs x {len(hard_exits)} hard_exits = {len(trail_fracs)*len(hard_exits)} configs\n")

    results = []
    for tf in trail_fracs:
        for hx in hard_exits:
            res = [sim_trail(t, tf, hx) for t in trades]
            k = run_sal(trades, res)
            p = k["p"]
            net, p_pf, dd = p.sum(), pf(p), maxdd(p)
            yr_wins = sum(1 for yr in years if float(k[k["yr"]==yr]["p"].sum()) > base_by_yr.get(yr, 0))
            oos_delta = sum(float(k[k["yr"]==yr]["p"].sum()) - base_by_yr.get(yr, 0)
                           for yr in years if yr in OOS_YEARS)
            ex = k["ex"].value_counts()
            results.append({
                "trail": tf, "hard": hx if hx else "none",
                "n": len(k), "net": net, "PF": p_pf, "maxDD": dd,
                "dNet": net - base_net, "dDD": dd - base_dd,
                "yr_won": yr_wins, "yr_tot": len(years), "oos_d": oos_delta,
                "TR": ex.get("TR", 0), "HX": ex.get("HX", 0),
                "SL": ex.get("SL", 0), "BE": ex.get("BE", 0),
            })

    rdf = pd.DataFrame(results)

    # Full grid sorted by PF descending
    rdf_sorted = rdf.sort_values("PF", ascending=False)
    print(f"{'trail':>6} {'hard':>5} {'n':>5} {'net':>9} {'PF':>6} {'maxDD':>8} {'dNet':>8} {'dDD':>7} "
          f"{'yrsW':>5} {'oosΔ':>8} {'TR':>5} {'HX':>5} {'SL':>5} {'BE':>5}")
    for _, r in rdf_sorted.iterrows():
        hx_str = f"{r['hard']:.1f}" if r['hard'] != 'none' else ' none'
        print(f"{r['trail']:>5.0%} {hx_str:>5} {int(r['n']):>5} {r['net']:>9.0f} {r['PF']:>6.3f} {r['maxDD']:>8.0f} "
              f"{r['dNet']:>+8.0f} {r['dDD']:>+7.0f} "
              f"{int(r['yr_won']):>3}/{int(r['yr_tot'])} {r['oos_d']:>+8.0f} "
              f"{int(r['TR']):>5} {int(r['HX']):>5} {int(r['SL']):>5} {int(r['BE']):>5}")

    # Top 10 by net
    print(f"\n--- TOP 10 by NET (baseline net={base_net:.0f}) ---")
    for _, r in rdf.nlargest(10, "net").iterrows():
        hx_str = f"{r['hard']:.1f}" if r['hard'] != 'none' else 'none'
        print(f"  trail={r['trail']:.0%} hard={hx_str:>4}  net={r['net']:>9.0f} PF={r['PF']:.3f} "
              f"maxDD={r['maxDD']:.0f} yrs={int(r['yr_won'])}/{int(r['yr_tot'])} oosΔ={r['oos_d']:+.0f}")

    # Top 10 by PF where dDD >= 0 (no DD regression)
    safe = rdf[rdf["dDD"] >= 0]
    if len(safe) > 0:
        print(f"\n--- TOP 10 by PF where maxDD does NOT worsen (n={len(safe)} configs qualify) ---")
        for _, r in safe.nlargest(10, "PF").iterrows():
            hx_str = f"{r['hard']:.1f}" if r['hard'] != 'none' else 'none'
            print(f"  trail={r['trail']:.0%} hard={hx_str:>4}  net={r['net']:>9.0f} PF={r['PF']:.3f} "
                  f"maxDD={r['maxDD']:.0f} yrs={int(r['yr_won'])}/{int(r['yr_tot'])} oosΔ={r['oos_d']:+.0f}")

    # Top 10 by years won then net
    print(f"\n--- TOP 10 by ROBUSTNESS (years beaten, then net) ---")
    for _, r in rdf.sort_values(["yr_won","net"], ascending=[False,False]).head(10).iterrows():
        hx_str = f"{r['hard']:.1f}" if r['hard'] != 'none' else 'none'
        print(f"  trail={r['trail']:.0%} hard={hx_str:>4}  net={r['net']:>9.0f} PF={r['PF']:.3f} "
              f"maxDD={r['maxDD']:.0f} yrs={int(r['yr_won'])}/{int(r['yr_tot'])} oosΔ={r['oos_d']:+.0f}")


if __name__ == "__main__":
    main()
