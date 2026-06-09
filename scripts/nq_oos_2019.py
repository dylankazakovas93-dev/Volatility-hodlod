#!/usr/bin/env python3
"""2019 out-of-sample test for the locked NQ level-fade strategy.

Locked config (tp_sl_cap200):
    TP = SL = min(1.5 x previous completed 1h range, 200)   # 1:1 RR
    Entry 19:00 -> 11:00 ET, skip 11:00-15:00 ET
    Session SAL: first real loss in 19:00->15:00 session stops entries

Runs two variants and prints year-by-year stats with 2019 as a fresh OOS year:
    1. Standard      - no stop adjustment
    2. BE60 SAL-A    - stop -> entry after 60 one-minute bars;
                       BE scratches (0 pts) do NOT trigger SAL.

Usage:
    python3 scripts/nq_oos_2019.py \
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
RR = 1.0
BE_BARS = 60

# 2019 is the new OOS year; 2022 & 2020 were the prior OOS years.
OOS_YEARS = {2019, 2020, 2022}


# ── session / entry helpers (identical to nq_reconcile_configs.py) ──────────────

def entry_allowed(ts: pd.Timestamp) -> bool:
    et = ts.tz_convert("America/New_York")
    m = et.hour * 60 + et.minute
    return not (11 * 60 <= m < 15 * 60)


def session_date(ts: pd.Timestamp) -> str:
    et = ts.tz_convert("America/New_York")
    if et.hour >= 19:
        return (et + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return et.strftime("%Y-%m-%d")


def session_cutoff(touched_at: pd.Timestamp) -> pd.Timestamp | None:
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


def bar_ranges(bars: pd.DataFrame) -> pd.Series:
    r = bars.resample("60min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return r["high"] - r["low"]


def prev_completed_range(ranges: pd.Series, ts: pd.Timestamp) -> float | None:
    prev = ts.floor("60min") - pd.Timedelta(minutes=60)
    v = ranges.get(prev)
    return float(v) if v is not None and not pd.isna(v) and v > 0 else None


# ── exit simulators ─────────────────────────────────────────────────────────────

def simulate_standard(path: pd.DataFrame, entry: float, sign: float, tp: float, sl: float):
    """Fixed TP/SL, 1:1. Returns (pnl, exit_type)."""
    if path.empty:
        return 0.0, "empty"
    target = entry + sign * tp
    stop = entry - sign * sl
    hi = path["high"].values
    lo = path["low"].values
    cl = path["close"].values
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if sign > 0:
            if l <= stop:
                return -sl, "SL"
            if h >= target:
                return tp, "TP"
        else:
            if h >= stop:
                return -sl, "SL"
            if l <= target:
                return tp, "TP"
    return sign * (float(cl[-1]) - entry), "cutoff"


def simulate_be60(path: pd.DataFrame, entry: float, sign: float, tp: float, sl: float):
    """Stop moves to entry after BE_BARS one-minute bars. Returns (pnl, exit_type)."""
    if path.empty:
        return 0.0, "empty"
    target = entry + sign * tp
    orig_stop = entry - sign * sl
    hi = path["high"].values
    lo = path["low"].values
    cl = path["close"].values
    n = len(hi)
    for i in range(n):
        h, l = float(hi[i]), float(lo[i])
        stop = orig_stop if i < BE_BARS else entry
        if sign > 0:
            if l <= stop:
                return sign * float(stop - entry), ("BE" if i >= BE_BARS else "SL")
            if h >= target:
                return tp, "TP"
        else:
            if h >= stop:
                return sign * float(stop - entry), ("BE" if i >= BE_BARS else "SL")
            if l <= target:
                return tp, "TP"
    return sign * (float(cl[-1]) - entry), "cutoff"


# ── SAL variants ─────────────────────────────────────────────────────────────────

def sal_standard(df: pd.DataFrame, pnl_col: str) -> pd.DataFrame:
    """Stop after first real loss (<0)."""
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                if row[pnl_col] < -0.1:
                    lost = True
    return pd.DataFrame(kept) if kept else pd.DataFrame()


def sal_be_aware(df: pd.DataFrame, pnl_col: str, exit_col: str) -> pd.DataFrame:
    """SAL-A: BE scratches (0 pts) do NOT stop the session; only real losses do."""
    kept = []
    for _, day in df.sort_values("touched_at").groupby("sess_date"):
        lost = False
        for _, row in day.iterrows():
            if not lost:
                kept.append(row.to_dict())
                is_real_loss = row[pnl_col] < -0.1 and row[exit_col] != "BE"
                if is_real_loss:
                    lost = True
    return pd.DataFrame(kept) if kept else pd.DataFrame()


# ── stats ────────────────────────────────────────────────────────────────────────

def profit_factor(s: pd.Series) -> float:
    g = float(s[s > 0].sum())
    l = float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def max_drawdown(s: pd.Series) -> float:
    eq = s.cumsum()
    return float((eq - eq.cummax()).min()) if not s.empty else 0.0


def max_streak(s: pd.Series) -> int:
    streak = best = 0
    for v in s:
        streak = streak + 1 if v < -0.1 else 0
        best = max(best, streak)
    return best


def sortino(daily: pd.Series) -> float:
    if daily.empty:
        return 0.0
    dn = daily[daily < 0]
    dstd = float(dn.std(ddof=0)) if len(dn) else 0.0
    return float(daily.mean()) / dstd * np.sqrt(252) if dstd > 0 else float("inf")


def sharpe_ann(daily: pd.Series) -> float:
    if daily.empty or daily.std(ddof=0) == 0:
        return 0.0
    return float(daily.mean()) / float(daily.std(ddof=0)) * np.sqrt(252)


# ── build raw ledger ─────────────────────────────────────────────────────────────

def build_ledger(bars: pd.DataFrame, vxn: pd.Series) -> pd.DataFrame:
    all_levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars)
    lvl_list = list(all_levels.itertuples(index=False))
    records = []
    for i, lv in enumerate(lvl_list):
        expiry = lvl_list[i + LINE_DAYS].created_at if i + LINE_DAYS < len(lvl_list) else bars.index[-1]
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
            ps, es = simulate_standard(path, lvl, sign, cap, cap)
            pb, eb = simulate_be60(path, lvl, sign, cap, cap)
            records.append({
                "sess_date": session_date(ft),
                "year": pd.Timestamp(session_date(ft)).year,
                "side": side,
                "touched_at": ft,
                "level": lvl,
                "anchor": anchor,
                "cap": cap,
                "pnl_standard": ps, "exit_standard": es,
                "pnl_be60": pb, "exit_be60": eb,
            })
    return pd.DataFrame(records)


def year_table(kept: pd.DataFrame, pnl_col: str, exit_col: str, label: str, all_years: list[int]) -> None:
    print(f"\n{'─' * 90}")
    print(f"  {label}")
    print(f"{'─' * 90}")
    print(f"  {'Year':6} {'Tag':4} {'n':>5} {'net':>10} {'PF':>7} {'tWR':>7} "
          f"{'TP':>4} {'SL':>4} {'BE':>4} {'maxDD':>9} {'st':>3} {'Sortino':>8} {'aSharpe':>8}")
    for yr in all_years:
        sub = kept[kept["year"] == yr]
        if sub.empty:
            print(f"  {yr:6} {'OOS' if yr in OOS_YEARS else 'IS':4} {'—':>5}")
            continue
        pts = sub[pnl_col]
        tp = (sub[exit_col] == "TP").sum()
        sl = (sub[exit_col] == "SL").sum()
        be = (sub[exit_col] == "BE").sum()
        twr = tp / (tp + sl) * 100 if (tp + sl) else 0.0
        daily = sub.groupby("sess_date")[pnl_col].sum()
        tag = "OOS" if yr in OOS_YEARS else "IS"
        print(f"  {yr:6} {tag:4} {len(pts):>5} {pts.sum():>10.1f} {profit_factor(pts):>7.3f} "
              f"{twr:>6.1f}% {tp:>4} {sl:>4} {be:>4} {max_drawdown(pts):>9.1f} {max_streak(pts):>3} "
              f"{sortino(daily):>8.2f} {sharpe_ann(daily):>8.2f}")
    # ALL row
    pts = kept[pnl_col]
    tp = (kept[exit_col] == "TP").sum()
    sl = (kept[exit_col] == "SL").sum()
    be = (kept[exit_col] == "BE").sum()
    twr = tp / (tp + sl) * 100 if (tp + sl) else 0.0
    daily = kept.groupby("sess_date")[pnl_col].sum()
    print(f"  {'ALL':6} {'':4} {len(pts):>5} {pts.sum():>10.1f} {profit_factor(pts):>7.3f} "
          f"{twr:>6.1f}% {tp:>4} {sl:>4} {be:>4} {max_drawdown(pts):>9.1f} {max_streak(pts):>3} "
          f"{sortino(daily):>8.2f} {sharpe_ann(daily):>8.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    print("Loading data …")
    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    print(f"  bars {bars.index[0]} -> {bars.index[-1]}  ({len(bars):,})")

    print("Building raw ledger (lineDays=20) …")
    raw = build_ledger(bars, vxn)
    all_years = sorted(raw["year"].unique())
    print(f"  raw touches (before SAL): {len(raw)}   years: {all_years}")

    std = sal_standard(raw, "pnl_standard")
    be = sal_be_aware(raw, "pnl_be60", "exit_be60")

    year_table(std, "pnl_standard", "exit_standard",
               "STANDARD  (TP=SL=min(1.5xanchor,200), SAL after first loss)", all_years)
    year_table(be, "pnl_be60", "exit_be60",
               "BE60 SAL-A  (stop->entry after 60 bars, BE != loss for SAL)", all_years)

    print()


if __name__ == "__main__":
    main()
