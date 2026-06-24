#!/usr/bin/env python3
"""Level-to-level test: both TP and SL defined by nearest live levels.

SHORT (from upper): TP = nearest live lower_level below entry
                    SL = nearest live upper_level above entry
LONG  (from lower): TP = nearest live upper_level above entry
                    SL = nearest live lower_level below entry

Tested in 4 variants:
  1. with_cutoff, no BE         — pure level-to-level, exit at 15:00 if neither hit
  2. with_cutoff, BE@45         — same + conditional BE at bar 45
  3. multiday_5d, no BE         — hold up to 5 trading days
  4. multiday_5d, BE@45         — same + conditional BE

1 trade at a time throughout.

Usage:
    python3 scripts/nq_level_to_level.py \
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


def find_level(entry_price, side, direction, lvls, ft):
    """Find nearest live level.
    side: "upper" or "lower" (which side the entry is from)
    direction: "target" or "stop"
    """
    candidates = []
    for j, lv in enumerate(lvls):
        if lv.created_at > ft:
            break
        exp_idx = j + B.LINE_DAYS
        if exp_idx < len(lvls) and lvls[exp_idx].created_at <= ft:
            continue
        if side == "upper":
            if direction == "target":
                ll = float(lv.lower_level)
                if ll < entry_price:
                    candidates.append(ll)
            else:
                ul = float(lv.upper_level)
                if ul > entry_price:
                    candidates.append(ul)
        else:
            if direction == "target":
                ul = float(lv.upper_level)
                if ul > entry_price:
                    candidates.append(ul)
            else:
                ll = float(lv.lower_level)
                if ll < entry_price:
                    candidates.append(ll)
    if not candidates:
        return None
    if (side == "upper" and direction == "target") or (side == "lower" and direction == "stop"):
        return max(candidates)
    else:
        return min(candidates)


def build_entries(bars, vxn):
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = B.bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    entries = []
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
            sign = -1.0 if side == "upper" else 1.0
            target = find_level(lvl, side, "target", lvls, ft)
            stop = find_level(lvl, side, "stop", lvls, ft)
            if target is None or stop is None:
                continue
            tgt_dist = abs(target - lvl)
            sl_dist = abs(stop - lvl)
            if sl_dist < 5 or tgt_dist < 5:
                continue
            entries.append({
                "ft": ft, "lvl": lvl, "side": side, "sign": sign,
                "target": target, "stop_level": stop,
                "tgt_dist": tgt_dist, "sl_dist": sl_dist,
                "rr": tgt_dist / sl_dist,
                "sd": B.session_date(ft),
                "yr": pd.Timestamp(B.session_date(ft)).year,
            })
    return sorted(entries, key=lambda e: e["ft"])


def sim_l2l(path, entry, sign, target_level, stop_level, use_be, be_bars=BE_BARS):
    if path.empty:
        return 0.0, "cutoff", None
    hi = path["high"].values
    lo = path["low"].values
    op = path["open"].values
    cl = path["close"].values
    times = path.index
    armed = checked = False
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if use_be and i >= be_bars:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry) if sign > 0 else (o <= entry)
        stp = stop_level
        if use_be and armed:
            stp = entry
        if sign > 0:
            if l <= stp:
                pnl = stp - entry
                ex = "BE" if (use_be and armed) else "SL"
                return pnl, ex, times[i]
            if h >= target_level:
                return target_level - entry, "TGT", times[i]
        else:
            if h >= stp:
                pnl = entry - stp
                ex = "BE" if (use_be and armed) else "SL"
                return pnl, ex, times[i]
            if l <= target_level:
                return entry - target_level, "TGT", times[i]
    pnl = sign * (float(cl[-1]) - entry)
    return pnl, "cutoff", times[-1]


def run_mode(entries, bars, cutoff, use_be):
    records = []
    pos_exit = None
    for e in entries:
        ft = e["ft"]
        if pos_exit is not None and ft <= pos_exit:
            continue
        if cutoff:
            co = B.session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft:co].iloc[1:]
        else:
            end = ft + pd.Timedelta(days=7)
            path = bars.loc[ft:end].iloc[1:]
        if path.empty:
            continue
        pnl, ex, exit_time = sim_l2l(path, e["lvl"], e["sign"], e["target"], e["stop_level"], use_be)
        pos_exit = exit_time
        records.append({
            "sd": e["sd"], "yr": e["yr"], "ft": ft, "exit_time": exit_time,
            "side": e["side"], "entry": e["lvl"],
            "target": e["target"], "stop_level": e["stop_level"],
            "tgt_dist": e["tgt_dist"], "sl_dist": e["sl_dist"], "rr": e["rr"],
            "pnl": pnl, "exit": ex,
        })
    return pd.DataFrame(records)


def pf(s):
    g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def maxdd(s):
    e = s.cumsum()
    return float((e - e.cummax()).min())


def report(df, label):
    if df.empty:
        print(f"\n{label}: no trades")
        return
    years = sorted(df["yr"].unique())
    p = df["pnl"]
    ex = df["exit"].value_counts()
    print(f"\n{label}")
    print(f"  n={len(df)}  net={p.sum():.0f}  PF={pf(p):.3f}  maxDD={maxdd(p):.0f}")
    print(f"  exits: TGT={ex.get('TGT',0)} SL={ex.get('SL',0)} BE={ex.get('BE',0)} cutoff={ex.get('cutoff',0)}")
    print(f"  avg target dist: {df['tgt_dist'].mean():.1f}  avg SL dist: {df['sl_dist'].mean():.1f}  avg R:R: {df['rr'].mean():.2f}")
    tgt_rate = ex.get('TGT', 0) / len(df) * 100
    print(f"  TGT hit rate: {tgt_rate:.1f}%")
    print(f"\n  {'Year':>6} {'n':>5} {'net':>9} {'PF':>7} {'maxDD':>8} {'TGT':>5} {'SL':>5} {'BE':>5} {'cut':>5}")
    for yr in years:
        sub = df[df["yr"] == yr]
        sp = sub["pnl"]
        sex = sub["exit"].value_counts()
        print(f"  {yr:>6} {len(sub):>5} {sp.sum():>9.0f} {pf(sp):>7.3f} {maxdd(sp):>8.0f} "
              f"{sex.get('TGT',0):>5} {sex.get('SL',0):>5} {sex.get('BE',0):>5} {sex.get('cutoff',0):>5}")
    print(f"  {'ALL':>6} {len(df):>5} {p.sum():>9.0f} {pf(p):>7.3f} {maxdd(p):>8.0f} "
          f"{ex.get('TGT',0):>5} {ex.get('SL',0):>5} {ex.get('BE',0):>5} {ex.get('cutoff',0):>5}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    entries = build_entries(bars, vxn)
    print(f"potential entries (with both target+stop levels): {len(entries)}")
    edf = pd.DataFrame(entries)
    print(f"  avg target dist: {edf['tgt_dist'].mean():.1f}  avg SL dist: {edf['sl_dist'].mean():.1f}  avg R:R: {edf['rr'].mean():.2f}")

    configs = [
        (True, False, "LEVEL-TO-LEVEL | session cutoff, no BE"),
        (True, True, "LEVEL-TO-LEVEL | session cutoff, BE@45"),
        (False, False, "LEVEL-TO-LEVEL | multi-day 5d, no BE"),
        (False, True, "LEVEL-TO-LEVEL | multi-day 5d, BE@45"),
    ]
    for cutoff, use_be, label in configs:
        df = run_mode(entries, bars, cutoff, use_be)
        report(df, label)


if __name__ == "__main__":
    main()
