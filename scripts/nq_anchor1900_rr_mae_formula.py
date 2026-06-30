#!/usr/bin/env python3
"""For the 19:00-anchor candidate (sigma=1.0, offset=0, ib=90):
  1. RR sweep -- tighten SL to frac*cap, TP stays cap, fine grid (0.05 steps).
  2. MAE/MFE distribution -- same diagnostic as nq_mae_analysis.py, run
     against this trade set (ALL trades, TP-only, SL-only).
  3. Fit a quadratic to net(frac) from the sweep and solve for the
     expectancy-maximizing frac analytically (vertex of the parabola),
     then sanity-check the fitted optimum against the actual swept points.

Usage:
    python3 scripts/nq_anchor1900_rr_mae_formula.py \
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
from volgen.levels import InstrumentParams, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B

RTH_START, RTH_END = "19:00", "01:30"
PARAMS = InstrumentParams(sigma_mult=1.00, offset_pct=0.0, ib_minutes=90, fixed_offset=0.0)
BE_BARS = 45


def build_trades(bars, vxn):
    levels = generate_levels(bars, vxn, params=PARAMS, rth_start=RTH_START, rth_end=RTH_END)
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


def sim(t, sl_frac, tp_frac=1.0, be_bars=BE_BARS):
    """cond@45, TP=tp_frac*cap, SL=sl_frac*cap. Tracks MAE/MFE (points)."""
    e, sg, c = t["e"], t["sg"], t["cap"]
    target = e + sg * tp_frac * c
    orig_stop = e - sg * sl_frac * c
    hi, lo, op, cl = t["hi"], t["lo"], t["op"], t["cl"]
    armed = checked = False
    mae = mfe = 0.0
    for i in range(len(hi)):
        h, l = hi[i], lo[i]
        adverse = (e - l) if sg > 0 else (h - e)
        favorable = (h - e) if sg > 0 else (e - l)
        if adverse > mae:
            mae = adverse
        if favorable > mfe:
            mfe = favorable
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= e) if sg > 0 else (o <= e)
            stop = e if armed else orig_stop
        if sg > 0:
            if l <= stop:
                return sg * (stop - e), ("BE" if (i >= be_bars and armed) else "SL"), mae, mfe
            if h >= target:
                return tp_frac * c, "TP", mae, mfe
        else:
            if h >= stop:
                return sg * (stop - e), ("BE" if (i >= be_bars and armed) else "SL"), mae, mfe
            if l <= target:
                return tp_frac * c, "TP", mae, mfe
    return sg * (float(cl[-1]) - e), "cutoff", mae, mfe


def apply_sal(trades, results):
    rows = [{"sd": t["sd"], "yr": t["yr"], "ta": t["ta"], "p": r[0], "ex": r[1], "mae": r[2], "mfe": r[3]}
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
    return pd.DataFrame(kept)


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
    print(f"raw touches (pre-SAL): {len(trades)}\n")

    # ---- 1. RR sweep ----
    fracs = np.round(np.arange(0.10, 1.05, 0.05), 2)
    sweep = []
    for frac in fracs:
        res = [sim(t, frac) for t in trades]
        k = apply_sal(trades, res)
        p = k["p"]
        ex = k["ex"].value_counts()
        net = float(p.sum())
        sweep.append({"frac": frac, "rr": round(1.0 / frac, 2), "n": len(k), "net": net,
                       "PF": pf(p), "maxDD": maxdd(p), "expectancy": net / len(k) if len(k) else 0.0,
                       "TP": int(ex.get("TP", 0)), "SL": int(ex.get("SL", 0)),
                       "BE": int(ex.get("BE", 0)), "cut": int(ex.get("cutoff", 0))})

    sdf = pd.DataFrame(sweep)
    print("=== RR sweep (TP=cap fixed, SL=frac*cap) ===")
    print(f"{'frac':>5} {'RR':>6} {'n':>5} {'net':>9} {'PF':>7} {'maxDD':>8} {'expct':>7} "
          f"{'TP':>5} {'SL':>5} {'BE':>5} {'cut':>5}")
    for _, r in sdf.iterrows():
        print(f"{r['frac']:>5.2f} {r['rr']:>6.2f} {int(r['n']):>5} {r['net']:>9.0f} {r['PF']:>7.3f} "
              f"{r['maxDD']:>8.0f} {r['expectancy']:>7.2f} {int(r['TP']):>5} {int(r['SL']):>5} "
              f"{int(r['BE']):>5} {int(r['cut']):>5}")

    best_swept = sdf.loc[sdf["net"].idxmax()]
    print(f"\nbest swept by net: frac={best_swept['frac']:.2f} (RR={best_swept['rr']:.2f}) "
          f"net={best_swept['net']:.0f} PF={best_swept['PF']:.3f}")

    # ---- 2. Fit a quadratic to net(frac) and solve for the vertex ----
    a, b, c = np.polyfit(sdf["frac"], sdf["net"], 2)
    print(f"\n=== Fitted formula: net(frac) = {a:.1f}*frac^2 + {b:.1f}*frac + {c:.1f} ===")
    if a < 0:
        frac_star = -b / (2 * a)
        net_star = a * frac_star**2 + b * frac_star + c
        print(f"d(net)/d(frac) = 0 at frac* = {frac_star:.3f}  (predicted net = {net_star:.0f})")
        print(f"  -> implied SL distance = {frac_star:.3f} x cap, RR = {1/frac_star:.2f} : 1 (SL:TP)")
    else:
        print("fit is convex (a >= 0) -- no interior maximum, net(frac) is monotonic over this range; "
              "the swept-optimum above is the real answer, not the fit.")

    r2 = 1 - np.sum((sdf["net"] - np.polyval([a, b, c], sdf["frac"]))**2) / np.sum((sdf["net"] - sdf["net"].mean())**2)
    print(f"  R^2 of fit = {r2:.3f}")

    # ---- 3. MAE/MFE distribution at native 1:1 (frac=1.0) ----
    base_res = [sim(t, 1.0) for t in trades]
    base = apply_sal(trades, base_res)

    def summarize(df, label):
        if df.empty:
            print(f"\n{label}: no trades")
            return
        print(f"\n{label} (n={len(df)})")
        print(f"{'':>10} {'mean':>7} {'med':>7} {'p75':>7} {'p90':>7} {'max':>7}")
        print(f"{'MAE pts':>10} {df['mae'].mean():>7.1f} {df['mae'].median():>7.1f} "
              f"{df['mae'].quantile(.75):>7.1f} {df['mae'].quantile(.90):>7.1f} {df['mae'].max():>7.1f}")
        print(f"{'MFE pts':>10} {df['mfe'].mean():>7.1f} {df['mfe'].median():>7.1f} "
              f"{df['mfe'].quantile(.75):>7.1f} {df['mfe'].quantile(.90):>7.1f} {df['mfe'].max():>7.1f}")

    summarize(base, "ALL TRADES -- MAE/MFE (1:1 baseline at this anchor)")
    summarize(base[base["ex"] == "TP"], "TP-ONLY")
    summarize(base[base["ex"] == "SL"], "SL-ONLY (how close losers got to target before stopping)")


if __name__ == "__main__":
    main()
