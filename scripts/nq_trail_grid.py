#!/usr/bin/env python3
"""Grid sweep for a trail-after-TP overlay on the locked cond@45 config.

Mechanics being tested:
  - Trade runs exactly like cond@45 (TP=SL=cap, BE@45 if green) UNTIL price
    first reaches +1.0cap (the normal TP level). At that point, instead of
    closing, the trade "engages":
      - stop moves to +trail_pct * cap  (a giveback, NOT all the way to 0)
      - target moves out to +(1+ext) * cap
  - If price pulls back to the trail stop first  -> exit at +trail_pct*cap
  - If price extends to the new target first     -> exit at +(1+ext)*cap
  - If session ends with trade still engaged     -> mark-to-close

Everything before engagement (SL, BE, normal SAL) is untouched, so the loss
side / worst-day / worst-session profile is identical to baseline cond@45.

Usage:
    python3 scripts/nq_trail_grid.py \
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


def cond_plain(t, be_bars=BE_BARS):
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
                o = op[i]
                armed = (o >= e) if sg > 0 else (o <= e)
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


def trail_outcome(t, trail_pct, ext, be_bars=BE_BARS):
    e, sg, c = t["e"], t["sg"], t["cap"]
    tgt, orig = e + sg * c, e - sg * c
    trail, xt = e + sg * trail_pct * c, e + sg * (1 + ext) * c
    hi, lo, op, cl = t["hi"], t["lo"], t["op"], t["cl"]
    armed = chk = engaged = False
    for i in range(len(hi)):
        h, l = hi[i], lo[i]
        if not engaged:
            if i < be_bars:
                stp = orig
            else:
                if not chk:
                    chk = True
                    o = op[i]
                    armed = (o >= e) if sg > 0 else (o <= e)
                stp = e if armed else orig
            if sg > 0:
                if l <= stp:
                    return sg * (stp - e), ("BE" if (i >= be_bars and armed) else "SL")
                if h >= tgt:
                    engaged = True
                    continue
            else:
                if h >= stp:
                    return sg * (stp - e), ("BE" if (i >= be_bars and armed) else "SL")
                if l <= tgt:
                    engaged = True
                    continue
        else:
            if sg > 0:
                if l <= trail:
                    return trail_pct * c, "TR"
                if h >= xt:
                    return (1 + ext) * c, "XT"
            else:
                if h >= trail:
                    return trail_pct * c, "TR"
                if l <= xt:
                    return (1 + ext) * c, "XT"
    return sg * (cl[-1] - e), ("cutoff_eng" if engaged else "cutoff")


def apply_sal(trades, simfn):
    rows = [{"sd": t["sd"], "yr": t["yr"], "ta": t["ta"], "p": simfn(t)[0]} for t in trades]
    df = pd.DataFrame(rows).sort_values("ta")
    kept = []
    for _, day in df.groupby("sd"):
        lost = False
        for _, r in day.iterrows():
            if not lost:
                kept.append(r.to_dict())
                if r["p"] < -0.1:
                    lost = True
    return pd.DataFrame(kept).sort_values("ta").reset_index(drop=True)


def maxdd(s):
    e = s.cumsum()
    return float((e - e.cummax()).min())


def pf(s):
    g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    trades = build_trades(bars, vxn)
    print(f"raw trades: {len(trades)}")

    base = apply_sal(trades, cond_plain)
    years = sorted(base["yr"].unique())
    base_by_yr = {yr: base[base["yr"] == yr]["p"] for yr in years}
    base_net, base_pf, base_dd = base["p"].sum(), pf(base["p"]), maxdd(base["p"])
    print(f"\nBASELINE cond@45: n={len(base)} net={base_net:.0f} PF={base_pf:.3f} maxDD={base_dd:.0f}\n")

    trails = [0.5, 0.6, 0.7, 0.8, 0.9]
    exts = [0.2, 0.3, 0.4, 0.5, 0.6]

    results = []
    for trail_pct in trails:
        for ext in exts:
            tr = apply_sal(trades, lambda t, tp=trail_pct, ex=ext: trail_outcome(t, tp, ex))
            net, p, dd = tr["p"].sum(), pf(tr["p"]), maxdd(tr["p"])
            # robustness: count years where this config's net beats baseline's net
            wins = 0
            oos_delta = 0.0
            for yr in years:
                d = tr[tr["yr"] == yr]["p"].sum() - base_by_yr[yr].sum()
                if d > 0:
                    wins += 1
                if yr in OOS_YEARS:
                    oos_delta += d
            results.append({
                "trail": trail_pct, "ext": ext, "net": net, "PF": p, "maxDD": dd,
                "delta_net": net - base_net, "delta_dd": dd - base_dd,
                "years_won": wins, "years_total": len(years), "oos_delta": oos_delta,
            })

    rdf = pd.DataFrame(results)
    rdf = rdf.sort_values(["years_won", "delta_net"], ascending=[False, False])
    print(f"{'trail':>6} {'ext':>5} {'net':>9} {'PF':>6} {'maxDD':>8} {'dNet':>8} {'dDD':>7} {'yrsWon':>7} {'oosΔ':>8}")
    for _, r in rdf.iterrows():
        print(f"{r['trail']:>6.0%} {r['ext']:>5.0%} {r['net']:>9.0f} {r['PF']:>6.2f} {r['maxDD']:>8.0f} "
              f"{r['delta_net']:>+8.0f} {r['delta_dd']:>+7.0f} {int(r['years_won']):>4}/{int(r['years_total'])} "
              f"{r['oos_delta']:>+8.0f}")


if __name__ == "__main__":
    main()
