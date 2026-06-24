#!/usr/bin/env python3
"""Fixed-point trailing stop after TP engagement.

Proposal from pink: when price reaches the normal TP level (+cap), DON'T
close. Instead, engage a trailing stop N points behind price. If price
keeps running, you capture the extension. If it pulls back N points from
the best price post-engagement, you exit there.

Everything before engagement is unchanged cond@45 (SL, BE@45, SAL).

Sweeps trail distance: 50, 75, 100, 125, 150 points.

Usage:
    python3 scripts/nq_trail_fixed.py \
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


def cond_plain(t, be_bars=BE_BARS):
    """Baseline cond@45: close at TP."""
    e, sg, c = t["e"], t["sg"], t["cap"]
    tgt, orig = e + sg * c, e - sg * c
    hi, lo, op = t["hi"], t["lo"], t["op"]
    cl = t["cl"]
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


def trail_fixed(t, trail_pts, be_bars=BE_BARS):
    """After price reaches +cap, trail `trail_pts` behind price instead of closing."""
    e, sg, c = t["e"], t["sg"], t["cap"]
    tgt, orig = e + sg * c, e - sg * c
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
                    continue
            else:
                if h >= stp:
                    return sg * (stp - e), ("BE" if (i >= be_bars and armed) else "SL")
                if l <= tgt:
                    engaged = True
                    best = l
                    continue
        else:
            if sg > 0:
                if h > best:
                    best = h
                ts = best - trail_pts
                if l <= ts:
                    return ts - e, "TR"
            else:
                if l < best:
                    best = l
                ts = best + trail_pts
                if h >= ts:
                    return e - ts, "TR"
    return sg * (cl[-1] - e), ("cutoff_eng" if engaged else "cutoff")


def apply_sal(trades, simfn):
    rows = [{"sd": t["sd"], "yr": t["yr"], "ta": t["ta"], "p": simfn(t)[0], "ex": simfn(t)[1]} for t in trades]
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

    base = apply_sal(trades, cond_plain)
    base_net, base_pf, base_dd = base["p"].sum(), pf(base["p"]), maxdd(base["p"])
    base_ex = base["ex"].value_counts()
    print(f"BASELINE cond@45: n={len(base)} net={base_net:.0f} PF={base_pf:.3f} maxDD={base_dd:.0f} "
          f"TP={base_ex.get('TP',0)} SL={base_ex.get('SL',0)} BE={base_ex.get('BE',0)} cut={base_ex.get('cutoff',0)}\n")

    trail_pts_list = [50, 75, 100, 125, 150]
    print(f"{'trail':>6} {'n':>5} {'net':>9} {'PF':>6} {'maxDD':>8} {'TR':>5} {'SL':>5} {'BE':>5} {'cut':>5} {'cEng':>5}"
          f"   {'dNet':>8} {'dDD':>7}")
    for tp in trail_pts_list:
        k = apply_sal(trades, lambda t, _tp=tp: trail_fixed(t, _tp))
        p = k["p"]
        ex = k["ex"].value_counts()
        net, p_pf, dd = p.sum(), pf(p), maxdd(p)
        print(f"{tp:>5}p {len(k):>5} {net:>9.0f} {p_pf:>6.3f} {dd:>8.0f} "
              f"{ex.get('TR',0):>5} {ex.get('SL',0):>5} {ex.get('BE',0):>5} "
              f"{ex.get('cutoff',0):>5} {ex.get('cutoff_eng',0):>5}"
              f"   {net-base_net:>+8.0f} {dd-base_dd:>+7.0f}")

    # Year-by-year for the 100pt trail (pink's specific proposal)
    print(f"\n--- 100pt trail year-by-year ---")
    k100 = apply_sal(trades, lambda t: trail_fixed(t, 100))
    base_yr = {yr: base[base["yr"]==yr]["p"] for yr in sorted(base["yr"].unique())}
    print(f"{'Year':>6} {'n':>5} {'net':>9} {'PF':>6} {'base_net':>9} {'delta':>8}")
    for yr in sorted(k100["yr"].unique()):
        sub = k100[k100["yr"]==yr]["p"]
        bn = base_yr[yr].sum()
        print(f"{yr:>6} {len(sub):>5} {sub.sum():>9.0f} {pf(sub):>6.3f} {bn:>9.0f} {sub.sum()-bn:>+8.0f}")
    p = k100["p"]
    print(f"{'ALL':>6} {len(k100):>5} {p.sum():>9.0f} {pf(p):>6.3f} {base_net:>9.0f} {p.sum()-base_net:>+8.0f}")


if __name__ == "__main__":
    main()
