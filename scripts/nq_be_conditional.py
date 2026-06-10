#!/usr/bin/env python3
"""Compare three stop-management variants on the locked NQ config, 2018-2026:

  1. Standard         - fixed TP/SL, no adjustment
  2. BE60 (instant)   - at bar 60 stop jumps to entry; if already underwater it
                        fires immediately (the variant we tested before)
  3. BE60-cond        - at bar 60 BE arms ONLY if the trade is NOT in drawdown at
                        the checkpoint (close of bar 59 on the profit side of
                        entry). If underwater at minute 60, keep the original full
                        stop and let the trade play out.

All use SAL-A for the BE variants (a BE scratch != loss, session keeps trading);
Standard uses plain stop-after-first-loss.

Usage:
  python3 scripts/nq_be_conditional.py \
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

LINE_DAYS = 20
SL_CAP = 200.0
BE_BARS = 60
OOS_YEARS = {2018, 2019, 2020, 2022}


# ── session helpers ─────────────────────────────────────────────────────────────

def entry_allowed(ts):
    et = ts.tz_convert("America/New_York"); m = et.hour * 60 + et.minute
    return not (11 * 60 <= m < 15 * 60)


def session_date(ts):
    et = ts.tz_convert("America/New_York")
    return ((et + pd.Timedelta(days=1)) if et.hour >= 19 else et).strftime("%Y-%m-%d")


def session_cutoff(touched_at):
    et = touched_at.tz_convert("America/New_York"); d = et.strftime("%Y-%m-%d")
    co = pd.Timestamp(f"{d} 15:00", tz="America/New_York")
    re = pd.Timestamp(f"{d} 19:00", tz="America/New_York")
    if et < co:
        return co.tz_convert(touched_at.tz)
    if et >= re:
        nxt = et.normalize() + pd.Timedelta(days=1)
        return pd.Timestamp(f"{nxt.date()} 15:00", tz="America/New_York").tz_convert(touched_at.tz)
    return None


def bar_ranges(bars):
    r = bars.resample("60min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return r["high"] - r["low"]


def prev_completed_range(ranges, ts):
    prev = ts.floor("60min") - pd.Timedelta(minutes=60)
    v = ranges.get(prev)
    return float(v) if v is not None and not pd.isna(v) and v > 0 else None


# ── exit simulators ─────────────────────────────────────────────────────────────

def sim_standard(path, entry, sign, tp, sl):
    if path.empty:
        return 0.0, "empty"
    tgt = entry + sign * tp; stp = entry - sign * sl
    hi = path["high"].values; lo = path["low"].values; cl = path["close"].values
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if sign > 0:
            if l <= stp: return -sl, "SL"
            if h >= tgt: return tp, "TP"
        else:
            if h >= stp: return -sl, "SL"
            if l <= tgt: return tp, "TP"
    return sign * (float(cl[-1]) - entry), "cutoff"


def sim_be60_instant(path, entry, sign, tp, sl):
    """At bar BE_BARS, stop jumps to entry unconditionally."""
    if path.empty:
        return 0.0, "empty"
    tgt = entry + sign * tp; orig = entry - sign * sl
    hi = path["high"].values; lo = path["low"].values; cl = path["close"].values
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        stp = orig if i < BE_BARS else entry
        if sign > 0:
            if l <= stp: return sign * float(stp - entry), ("BE" if i >= BE_BARS else "SL")
            if h >= tgt: return tp, "TP"
        else:
            if h >= stp: return sign * float(stp - entry), ("BE" if i >= BE_BARS else "SL")
            if l <= tgt: return tp, "TP"
    return sign * (float(cl[-1]) - entry), "cutoff"


def sim_be60_cond(path, entry, sign, tp, sl):
    """At bar BE_BARS, arm BE ONLY if the trade is not in drawdown at the
    checkpoint (close of bar BE_BARS-1 on the profit side of entry). If
    underwater at the checkpoint, keep the original full stop for the rest of
    the trade (behaves like Standard from there)."""
    if path.empty:
        return 0.0, "empty"
    tgt = entry + sign * tp; orig = entry - sign * sl
    hi = path["high"].values; lo = path["low"].values; cl = path["close"].values
    n = len(hi)
    armed = False; checked = False
    for i in range(n):
        h, l = float(hi[i]), float(lo[i])
        if i < BE_BARS:
            stp = orig
        else:
            if not checked:
                prev_close = float(cl[i - 1])           # close of bar BE_BARS-1
                armed = (prev_close >= entry) if sign > 0 else (prev_close <= entry)
                checked = True
            stp = entry if armed else orig
        if sign > 0:
            if l <= stp:
                return sign * float(stp - entry), ("BE" if (i >= BE_BARS and armed) else "SL")
            if h >= tgt: return tp, "TP"
        else:
            if h >= stp:
                return sign * float(stp - entry), ("BE" if (i >= BE_BARS and armed) else "SL")
            if l <= tgt: return tp, "TP"
    return sign * (float(cl[-1]) - entry), "cutoff"


# ── SAL ─────────────────────────────────────────────────────────────────────────

def sal_standard(df, pnl_col):
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row[pnl_col] < -0.1: lost = True
    return pd.DataFrame(kept) if kept else pd.DataFrame()


def sal_be_aware(df, pnl_col, exit_col):
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row[pnl_col] < -0.1 and row[exit_col] != "BE": lost = True
    return pd.DataFrame(kept) if kept else pd.DataFrame()


# ── stats ────────────────────────────────────────────────────────────────────────

def pf(s):
    g = float(s[s > 0].sum()); l = float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def mdd(s):
    eq = s.cumsum(); return float((eq - eq.cummax()).min()) if not s.empty else 0.0


def streak(s):
    st = best = 0
    for v in s:
        st = st + 1 if v < -0.1 else 0; best = max(best, st)
    return best


def twr(tp, sl):
    return tp / (tp + sl) * 100 if (tp + sl) else 0.0


# ── build ────────────────────────────────────────────────────────────────────────

def build(bars, vxn):
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    recs = []
    for i, lv in enumerate(lvls):
        expiry = lvls[i + LINE_DAYS].created_at if i + LINE_DAYS < len(lvls) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col); ft = _first_touch(search, lvl)
            if ft is None or not entry_allowed(ft): continue
            anchor = prev_completed_range(ranges, ft)
            if anchor is None: continue
            co = session_cutoff(ft)
            if co is None: continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty: continue
            cap = min(1.5 * anchor, SL_CAP); sign = -1.0 if side == "upper" else 1.0
            ps, es = sim_standard(path, lvl, sign, cap, cap)
            pi, ei = sim_be60_instant(path, lvl, sign, cap, cap)
            pc, ec = sim_be60_cond(path, lvl, sign, cap, cap)
            recs.append({
                "sess_date": session_date(ft), "year": pd.Timestamp(session_date(ft)).year,
                "side": side, "touched_at": ft, "level": lvl, "anchor": anchor, "cap": cap,
                "pnl_std": ps, "exit_std": es,
                "pnl_inst": pi, "exit_inst": ei,
                "pnl_cond": pc, "exit_cond": ec,
            })
    return pd.DataFrame(recs)


def ytable(kept, pcol, ecol, label, years):
    print(f"\n{'─'*92}")
    print(f"  {label}")
    print(f"{'─'*92}")
    print(f"  {'Year':6} {'Tag':4} {'n':>5} {'net':>10} {'PF':>7} {'tWR':>7} "
          f"{'TP':>4} {'SL':>4} {'BE':>4} {'maxDD':>9} {'st':>3}")
    for yr in years:
        sub = kept[kept["year"] == yr]
        if sub.empty:
            print(f"  {yr:6} {'OOS' if yr in OOS_YEARS else 'IS':4} {'—':>5}"); continue
        p = sub[pcol]; tp = (sub[ecol] == "TP").sum(); sl = (sub[ecol] == "SL").sum(); be = (sub[ecol] == "BE").sum()
        tag = "OOS" if yr in OOS_YEARS else "IS"
        print(f"  {yr:6} {tag:4} {len(p):>5} {p.sum():>10.1f} {pf(p):>7.3f} {twr(tp,sl):>6.1f}% "
              f"{tp:>4} {sl:>4} {be:>4} {mdd(p):>9.1f} {streak(p):>3}")
    p = kept[pcol]; tp = (kept[ecol] == "TP").sum(); sl = (kept[ecol] == "SL").sum(); be = (kept[ecol] == "BE").sum()
    print(f"  {'ALL':6} {'':4} {len(p):>5} {p.sum():>10.1f} {pf(p):>7.3f} {twr(tp,sl):>6.1f}% "
          f"{tp:>4} {sl:>4} {be:>4} {mdd(p):>9.1f} {streak(p):>3}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True); ap.add_argument("--vxn", required=True)
    args = ap.parse_args()
    bars = load_1m_ohlcv(args.bars); vxn = load_gvz_daily(args.vxn)
    print("Building raw ledger …")
    raw = build(bars, vxn)
    years = sorted(raw["year"].unique())
    print(f"  raw touches: {len(raw)}")

    std = sal_standard(raw, "pnl_std")
    inst = sal_be_aware(raw, "pnl_inst", "exit_inst")
    cond = sal_be_aware(raw, "pnl_cond", "exit_cond")

    ytable(std, "pnl_std", "exit_std", "STANDARD (no adjustment)", years)
    ytable(inst, "pnl_inst", "exit_inst", "BE60 INSTANT (stop->entry at bar60, fires even if underwater)", years)
    ytable(cond, "pnl_cond", "exit_cond", "BE60-COND (arm BE only if NOT in drawdown at bar60)", years)

    # Verify Trade 1 under cond
    print(f"\n{'='*60}\nTrade-1 sanity (2025-06-12 20:05 ET, was underwater at min60):")
    t1 = raw[(raw["touched_at"] >= "2025-06-12 20:00") & (raw["touched_at"] < "2025-06-12 20:10")]
    for _, r in t1.iterrows():
        print(f"  std={r['exit_std']}({r['pnl_std']:+.1f})  "
              f"inst={r['exit_inst']}({r['pnl_inst']:+.1f})  "
              f"cond={r['exit_cond']}({r['pnl_cond']:+.1f})")
    print()


if __name__ == "__main__":
    main()
