#!/usr/bin/env python3
"""Does widening the SL (keeping TP = cap fixed) "solve" the MAE-tail issue?

Motivation: for TP-only trades in cond@45, median MAE is ~26% of cap but the
p90/max reach ~75-99% of cap -- i.e. a tail of eventual winners come within a
hair of the stop before reversing. The question: if we give every trade
~30% more room on the SL side (SL = 1.3 x cap) while leaving TP = cap
unchanged, does that "rescue" enough of those near-miss winners to be a net
positive, or does it just make every real loss bigger?

Mechanics: identical to cond@45 (BE@45 still arms -> stop = entry, unaffected
by SL width) EXCEPT orig_stop = entry - sign * (sl_mult * cap) instead of
entry - sign * cap. TP stays at entry + sign * cap.

Sweeps sl_mult over 1.0 (baseline) .. 1.5.

Usage:
    python3 scripts/nq_wide_sl_test.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch
import scripts.build_be60_enriched as B

BE_BARS = 45


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


def sim(t, sl_mult, be_bars=BE_BARS):
    e, sg, c = t["e"], t["sg"], t["cap"]
    tgt = e + sg * c
    orig_stop = e - sg * (c * sl_mult)
    hi, lo, op, cl = t["hi"], t["lo"], t["op"], t["cl"]
    armed = chk = False
    for i in range(len(hi)):
        h, l = hi[i], lo[i]
        if i < be_bars:
            stp = orig_stop
        else:
            if not chk:
                chk = True
                o = op[i]
                armed = (o >= e) if sg > 0 else (o <= e)
            stp = e if armed else orig_stop
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


def apply_sal(trades, sl_mult):
    rows = []
    for t in trades:
        p, ex = sim(t, sl_mult)
        rows.append({"sd": t["sd"], "yr": t["yr"], "ta": t["ta"], "p": p, "ex": ex})
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
    print(f"raw trades: {len(trades)}\n")

    mults = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
    base = None
    print(f"{'SL=mult*cap':>11} {'n':>5} {'net':>9} {'PF':>6} {'maxDD':>8} {'TP':>5} {'SL':>5} {'BE':>5} {'cut':>5}"
          f"   {'dNet':>8} {'dDD':>7}")
    for m in mults:
        k = apply_sal(trades, m)
        p = k["p"]
        ex = k["ex"].value_counts()
        net, p_pf, dd = p.sum(), pf(p), maxdd(p)
        if base is None:
            base = (net, dd)
        dnet, ddd = net - base[0], dd - base[1]
        print(f"{m:>11.1f} {len(k):>5} {net:>9.0f} {p_pf:>6.3f} {dd:>8.0f} "
              f"{ex.get('TP', 0):>5} {ex.get('SL', 0):>5} {ex.get('BE', 0):>5} {ex.get('cutoff', 0):>5}"
              f"   {dnet:>+8.0f} {ddd:>+7.0f}")


if __name__ == "__main__":
    main()
