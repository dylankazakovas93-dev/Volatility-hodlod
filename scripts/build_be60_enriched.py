#!/usr/bin/env python3
"""Rebuild the BE60 SAL-A ledger with extra per-trade diagnostics needed for an
honest win-rate split:

  mae          - max adverse excursion (pts, <=0)
  mfe          - max favourable excursion (pts, >=0)
  uw60         - was the trade underwater at the min-60 checkpoint?
                 (close of bar BE_BARS-1 on the wrong side of entry)
  be_dd        - True only for BE exits that fired while underwater at min 60
                 (an instant-fire "rescued loss"). BE exits that came from a
                 profit state and later pulled back to entry are be_dd=False
                 (a "given-up winner").

Everything else (level math, caps, SAL-A grouping) is identical to
scripts/nq_oos_2019.py so the ledger reconciles with the canonical one.

Usage:
    python3 scripts/build_be60_enriched.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
        --out  data/nq_be60_sala_enriched_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch

LINE_DAYS = 20
SL_CAP = 200.0
BE_BARS = 60


def entry_allowed(ts):
    et = ts.tz_convert("America/New_York")
    m = et.hour * 60 + et.minute
    return not (11 * 60 <= m < 15 * 60)


def session_date(ts):
    et = ts.tz_convert("America/New_York")
    return ((et + pd.Timedelta(days=1)) if et.hour >= 19 else et).strftime("%Y-%m-%d")


def session_cutoff(touched_at):
    et = touched_at.tz_convert("America/New_York")
    d = et.strftime("%Y-%m-%d")
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


def simulate_be60(path, entry, sign, tp, sl):
    """BE60 instant. Returns (pnl, exit_type, mae, mfe, uw60).

    uw60 = state at the min-60 checkpoint (close of bar BE_BARS-1 on the wrong
    side of entry). None if the trade resolved before reaching bar BE_BARS.
    """
    if path.empty:
        return 0.0, "empty", 0.0, 0.0, None
    target = entry + sign * tp
    orig_stop = entry - sign * sl
    hi = path["high"].values
    lo = path["low"].values
    cl = path["close"].values
    n = len(hi)
    mae = 0.0
    mfe = 0.0
    uw60 = None
    for i in range(n):
        h, l = float(hi[i]), float(lo[i])
        # excursions in signed pts (favourable >=0, adverse <=0)
        fav = sign * (h - entry) if sign > 0 else sign * (l - entry)
        adv = sign * (l - entry) if sign > 0 else sign * (h - entry)
        mfe = max(mfe, fav)
        mae = min(mae, adv)
        # capture checkpoint state once, at the first bar where BE is live
        if i >= BE_BARS and uw60 is None:
            prev_close = float(cl[i - 1])
            uw60 = (prev_close < entry) if sign > 0 else (prev_close > entry)
        stop = orig_stop if i < BE_BARS else entry
        if sign > 0:
            if l <= stop:
                return sign * float(stop - entry), ("BE" if i >= BE_BARS else "SL"), mae, mfe, uw60
            if h >= target:
                return tp, "TP", mae, mfe, uw60
        else:
            if h >= stop:
                return sign * float(stop - entry), ("BE" if i >= BE_BARS else "SL"), mae, mfe, uw60
            if l <= target:
                return tp, "TP", mae, mfe, uw60
    return sign * (float(cl[-1]) - entry), "cutoff", mae, mfe, uw60


def sal_be_aware(df, pnl_col, exit_col):
    """SAL-A: BE scratches (0 pts) do NOT stop the session; only real losses do."""
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row[pnl_col] < -0.1 and row[exit_col] != "BE":
                    lost = True
    return pd.DataFrame(kept) if kept else pd.DataFrame()


def build(bars, vxn):
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvls = list(levels.itertuples(index=False))
    recs = []
    for i, lv in enumerate(lvls):
        expiry = lvls[i + LINE_DAYS].created_at if i + LINE_DAYS < len(lvls) else bars.index[-1]
        search = bars.loc[lv.created_at: expiry]
        for side, col in (("upper", lv.upper_level), ("lower", lv.lower_level)):
            lvl = float(col)
            ft = _first_touch(search, lvl)
            if ft is None or not entry_allowed(ft):
                continue
            anchor = prev_completed_range(ranges, ft)
            if anchor is None:
                continue
            co = session_cutoff(ft)
            if co is None:
                continue
            path = bars.loc[ft: co].iloc[1:]
            if path.empty:
                continue
            cap = min(1.5 * anchor, SL_CAP)
            sign = -1.0 if side == "upper" else 1.0
            pnl, ex, mae, mfe, uw60 = simulate_be60(path, lvl, sign, cap, cap)
            be_dd = bool(ex == "BE" and uw60 is True)
            recs.append({
                "sess_date": session_date(ft),
                "year": pd.Timestamp(session_date(ft)).year,
                "side": side,
                "touched_at": ft,
                "level": lvl,
                "anchor": anchor,
                "cap": cap,
                "pnl_be60": pnl,
                "exit_be60": ex,
                "mae": round(mae, 3),
                "mfe": round(mfe, 3),
                "uw60": uw60 if uw60 is not None else "",
                "be_dd": be_dd,
            })
    return pd.DataFrame(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    raw = build(bars, vxn)
    kept = sal_be_aware(raw, "pnl_be60", "exit_be60")

    # cross-check against canonical ledger
    canon = pd.read_csv("data/nq_be60_sala_ledger_2018_2026.csv")
    print(f"enriched kept n={len(kept)}  canonical n={len(canon)}  net={kept['pnl_be60'].sum():.1f}")
    be = kept[kept["exit_be60"] == "BE"]
    print(f"  BE total={len(be)}  be_dd(underwater@60)={int(be['be_dd'].sum())}  "
          f"be_profit={int((~be['be_dd']).sum())}")

    kept.to_csv(args.out, index=False)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
