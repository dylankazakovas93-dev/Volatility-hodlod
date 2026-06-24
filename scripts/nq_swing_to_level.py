#!/usr/bin/env python3
"""Swing test: hold trade until price reaches the nearest opposite-side level.

Instead of TP = +cap, the target is the nearest live level on the other side:
  SHORT (from upper) → target = nearest live lower_level below entry
  LONG  (from lower) → target = nearest live upper_level above entry

SL and BE@45 unchanged. Only 1 trade at a time (next entry blocked until
current trade exits).

Three modes tested:
  1. with_cutoff:  exit at 15:00 ET if target not hit (same-session only)
  2. multiday_5d:  hold up to 5 trading days (~7 calendar days)
  3. multiday_20d: hold up to 20 trading days (~28 calendar days)

Usage:
    python3 scripts/nq_swing_to_level.py \
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


def find_target(entry_price, side, lvls, ft):
    """Nearest opposite-side level that's live at time ft."""
    candidates = []
    for j, lv in enumerate(lvls):
        if lv.created_at > ft:
            break
        exp_idx = j + B.LINE_DAYS
        if exp_idx < len(lvls) and lvls[exp_idx].created_at <= ft:
            continue
        if side == "upper":
            ll = float(lv.lower_level)
            if ll < entry_price:
                candidates.append(ll)
        else:
            ul = float(lv.upper_level)
            if ul > entry_price:
                candidates.append(ul)
    if not candidates:
        return None
    return max(candidates) if side == "upper" else min(candidates)


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
            cap = min(1.5 * anchor, B.SL_CAP)
            sign = -1.0 if side == "upper" else 1.0
            target = find_target(lvl, side, lvls, ft)
            if target is None:
                continue
            entries.append({
                "ft": ft, "lvl": lvl, "side": side, "sign": sign,
                "cap": cap, "target": target, "anchor": anchor,
                "sd": B.session_date(ft),
                "yr": pd.Timestamp(B.session_date(ft)).year,
                "tgt_dist": abs(target - lvl),
            })
    return sorted(entries, key=lambda e: e["ft"])


def sim_to_level(path, entry, sign, cap, target_level, be_bars=BE_BARS):
    """Walk path bar-by-bar: SL at cap, BE@45, TP at target_level."""
    if path.empty:
        return 0.0, "cutoff", None
    orig_stop = entry - sign * cap
    hi = path["high"].values
    lo = path["low"].values
    op = path["open"].values
    cl = path["close"].values
    times = path.index
    armed = checked = False
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if i < be_bars:
            stp = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry) if sign > 0 else (o <= entry)
            stp = entry if armed else orig_stop
        if sign > 0:
            if l <= stp:
                pnl = sign * (stp - entry)
                return pnl, ("BE" if (i >= be_bars and armed) else "SL"), times[i]
            if h >= target_level:
                return target_level - entry, "TGT", times[i]
        else:
            if h >= stp:
                pnl = sign * (stp - entry)
                return pnl, ("BE" if (i >= be_bars and armed) else "SL"), times[i]
            if l <= target_level:
                return entry - target_level, "TGT", times[i]
    pnl = sign * (float(cl[-1]) - entry)
    return pnl, "cutoff", times[-1]


def run_mode(entries, bars, mode):
    records = []
    pos_exit = None
    for e in entries:
        ft = e["ft"]
        if pos_exit is not None and ft <= pos_exit:
            continue
        if mode == "cutoff":
            co = B.session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft:co].iloc[1:]
        elif mode == "5d":
            end = ft + pd.Timedelta(days=7)
            path = bars.loc[ft:end].iloc[1:]
        elif mode == "20d":
            end = ft + pd.Timedelta(days=28)
            path = bars.loc[ft:end].iloc[1:]
        else:
            continue
        if path.empty:
            continue
        pnl, ex, exit_time = sim_to_level(path, e["lvl"], e["sign"], e["cap"], e["target"])
        pos_exit = exit_time
        records.append({
            "sd": e["sd"], "yr": e["yr"], "ft": ft, "exit_time": exit_time,
            "side": e["side"], "entry": e["lvl"], "target": e["target"],
            "cap": e["cap"], "pnl": pnl, "exit": ex, "tgt_dist": e["tgt_dist"],
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
    print(f"  avg target dist: {df['tgt_dist'].mean():.1f} pts  median: {df['tgt_dist'].median():.1f}")
    if len(df[df['exit']=='TGT']) > 0:
        tgt_trades = df[df['exit']=='TGT']
        hold_mins = (tgt_trades['exit_time'] - tgt_trades['ft']).dt.total_seconds() / 60
        print(f"  TGT avg hold: {hold_mins.mean():.0f} min  median: {hold_mins.median():.0f} min  max: {hold_mins.max():.0f} min")
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
    print(f"potential entries (with target): {len(entries)}")

    for mode in ("cutoff", "5d", "20d"):
        df = run_mode(entries, bars, mode)
        labels = {"cutoff": "WITH SESSION CUTOFF (15:00 ET, 1 trade at a time)",
                  "5d": "MULTI-DAY 5d MAX HOLD (1 trade at a time)",
                  "20d": "MULTI-DAY 20d MAX HOLD (1 trade at a time)"}
        report(df, labels[mode])


if __name__ == "__main__":
    main()
